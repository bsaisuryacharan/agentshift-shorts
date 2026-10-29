"""Real footage cutaways from the NASA Image and Video Library (no key; NASA media is generally public domain, credited anyway).

A beat may carry  "footage": "orbital debris"  (what to look for). The clip replaces that beat's still as a moving background;
if nothing relevant is found the beat keeps its generated still, so footage is always an upgrade, never a failure.

    ensure(spec, run_dir) -> {beat_key: "vid/<key>.mp4"}   (also writes vid/credits.json)
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import cv2
import httpx
import numpy as np

API = "https://images-api.nasa.gov/search"
SEG_S = 4.5
STOP = {"the", "and", "with", "from", "that", "this", "what", "into", "over", "nasa"}


def _terms(q: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{4,}", q.lower()) if w not in STOP}


def _query(q: str) -> list[dict]:
    r = httpx.get(API, params={"q": q, "media_type": "video"}, timeout=30)
    r.raise_for_status()
    return [it["data"][0] for it in r.json()["collection"]["items"][:15]]


INDEX = Path(__file__).resolve().parent.parent / "assets" / "motion" / "nasa_index.json"
_INDEX: list[dict] | None = None


def index() -> list[dict]:
    """~1,000 NASA Image and Video Library clips indexed by theme/keywords (built from the API, see docs/MOTION_ASSETS.md); fetched on demand."""
    global _INDEX
    if _INDEX is None:
        try:
            _INDEX = json.loads(INDEX.read_text())
        except (OSError, ValueError):
            _INDEX = []
    return _INDEX


def search_index(query: str, limit: int = 12) -> list[dict]:
    """rank the local index by query-word hits in title/keywords; the first (subject) word must appear."""
    order = [w for w in re.findall(r"[a-z]{4,}", query.lower()) if w not in STOP]
    if not order:
        return []
    need, primary = set(order), order[0]
    out = []
    for it in index():
        text = (it["t"] + " " + " ".join(it["k"])).lower()
        if primary not in text:
            continue
        hits = sum(1 for t in need if t in text)
        if hits:
            out.append({"id": it["id"], "title": it["t"], "hits": hits, "center": "NASA", "theme": it["th"]})
    return sorted(out, key=lambda x: -x["hits"])[:limit]


def search(query: str, limit: int = 12) -> list[dict]:
    """the NASA API ANDs every word, so a long phrase finds nothing: try the phrase, then word pairs, then single words,
    and rank every candidate by how many of the query's words appear in its title/description/keywords."""
    order = [w for w in re.findall(r"[a-z]{4,}", query.lower()) if w not in STOP]
    primary = order[0] if order else ""
    need = sorted(set(order), key=len, reverse=True)
    tries = [query] + [f"{a} {b}" for i, a in enumerate(need[:3]) for b in need[i + 1:4]] + need[:3]
    seen: dict[str, dict] = {}
    for q in tries:
        try:
            rows = _query(q)
        except httpx.HTTPError:
            continue
        for d in rows:
            text = (d.get("title", "") + " " + d.get("description", "")[:600] + " " + " ".join(d.get("keywords", []) or [])).lower()
            hits = sum(1 for t in need if t in text)
            head = (d.get("title", "") + " " + " ".join(d.get("keywords", []) or [])).lower()
            if hits and primary in head and d["nasa_id"] not in seen:        # the first word of the query is the subject: it must be in the title/keywords
                seen[d["nasa_id"]] = {"id": d["nasa_id"], "title": d.get("title", ""), "hits": hits, "center": d.get("center", "NASA")}
        if sum(1 for v in seen.values() if v["hits"] >= 2) >= 3:
            break
    return sorted(seen.values(), key=lambda x: -x["hits"])[:limit]


def _medium_url(nasa_id: str) -> str | None:
    r = httpx.get(f"https://images-assets.nasa.gov/video/{nasa_id}/collection.json", timeout=30)
    if r.status_code != 200:
        return None
    urls = [u.replace("http://", "https://") for u in r.json() if u.endswith("~medium.mp4")]
    return urls[0] if urls else None


def _duration(url: str) -> float:
    p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", url], capture_output=True, text=True, timeout=60)
    try:
        return float(p.stdout.strip())
    except ValueError:
        return 0.0


def _usable(path: Path) -> bool:
    """reject black/flat or frozen footage: mean brightness and frame-to-frame motion must be real."""
    cap = cv2.VideoCapture(str(path))
    prev, motion, bright, n = None, [], [], 0
    while n < 60:
        ok, f = cap.read()
        if not ok:
            break
        g = cv2.cvtColor(cv2.resize(f, (108, 192)), cv2.COLOR_BGR2GRAY).astype(np.float32)
        bright.append(g.mean())
        if prev is not None:
            motion.append(np.abs(g - prev).mean())
        prev, n = g, n + 1
    cap.release()
    return bool(bright) and float(np.mean(bright)) > 22 and bool(motion) and float(np.median(motion)) > 0.35


def _relevant(path: Path, query: str) -> bool | None:
    """True/False = decided; None = no vision answer (the caller then requires every requested word in the clip's title).
    Offline guards run first and always: no identifiable person, no on-screen text/labels. Then a vision model must confirm the subject."""
    from . import stills
    cap = cv2.VideoCapture(str(path))
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(cap.get(cv2.CAP_PROP_FRAME_COUNT) * 0.5))
    ok, f = cap.read()
    cap.release()
    if not ok:
        return False
    if stills.has_face(f) or stills.has_text(f):
        print(f"  footage check {query!r}: rejected (person or on-screen text)", flush=True)
        return False
    try:
        from . import auto
        if stills._VISION["dead"] or stills._VISION["calls"] >= 14:
            raise RuntimeError("vision unavailable")
        stills._VISION["calls"] += 1
        jpg = cv2.imencode(".jpg", cv2.resize(f, (270, 480)), [cv2.IMWRITE_JPEG_QUALITY, 80])[1].tobytes()
        out, _ = auto.ask('You check stock footage for a science explainer. Reply ONLY JSON {"relevant": true|false, "person": true|false, "text": true|false, "shows": "<=8 words"}. '
                          "relevant=true only if the frame clearly shows (or is an obviously fitting illustration of) the requested subject; people, interiors, aircraft cockpits, "
                          "streets and unrelated objects are NOT relevant unless requested. person=true if a real face/body is prominent; text=true if readable captions/labels are prominent.",
                          f"REQUESTED SUBJECT: {query}", image=jpg, wait=False)
        print(f"  footage check {query!r}: {out}", flush=True)
        return bool(out.get("relevant")) and not out.get("person") and not out.get("text")
    except Exception as e:
        if "429" in repr(e) or "Timeout" in repr(e):
            stills._VISION["dead"] = True
        print(f"  footage check unavailable ({str(e)[:70]}); strict title match instead", flush=True)
        return None


UA = {"User-Agent": "AgentShiftShorts/1.0 (https://youtube.com/@agentshiftai)"}


def stock_candidates(query: str, client=httpx) -> list[dict]:
    """portrait stock clips from Pexels / Pixabay (free keys PEXELS_API_KEY / PIXABAY_API_KEY as secrets); [] without a key. Each: url, id, title, license, source"""
    out: list[dict] = []
    key = os.environ.get("PEXELS_API_KEY")
    if key:
        try:
            r = client.get("https://api.pexels.com/videos/search", params={"query": query, "orientation": "portrait", "size": "medium", "per_page": 8},
                           headers={**UA, "Authorization": key}, timeout=30)
            r.raise_for_status()
            for v in r.json().get("videos", []):
                files = [f for f in v.get("video_files", []) if f.get("file_type") == "video/mp4" and (f.get("height") or 0) >= (f.get("width") or 0)]
                files.sort(key=lambda f: abs((f.get("height") or 0) - 1280))
                if files and (v.get("duration") or 0) >= SEG_S + 1:
                    out.append({"url": files[0]["link"], "id": f"pexels-{v['id']}", "title": (v.get("user") or {}).get("name", "Pexels"),
                                "tags": re.sub(r"[-/]", " ", (v.get("url") or "").split("/video/")[-1]).lower(),
                                "license": "Pexels licence (free to use)", "source": v.get("url", "https://www.pexels.com")})
        except (httpx.HTTPError, ValueError, KeyError) as e:
            print(f"  pexels {query!r}: {e!r}", flush=True)
    key = os.environ.get("PIXABAY_API_KEY")
    if key:
        try:
            r = client.get("https://pixabay.com/api/videos/", params={"key": key, "q": query, "per_page": 8, "safesearch": "true"}, headers=UA, timeout=30)
            r.raise_for_status()
            for h in r.json().get("hits", []):
                m = (h.get("videos") or {}).get("medium") or (h.get("videos") or {}).get("small") or {}
                if m.get("url") and (h.get("duration") or 0) >= SEG_S + 1:
                    out.append({"url": m["url"], "id": f"pixabay-{h['id']}", "title": h.get("user", "Pixabay"), "tags": (h.get("tags") or "").lower(),
                                "license": "Pixabay licence (free to use)", "source": h.get("pageURL", "https://pixabay.com")})
        except (httpx.HTTPError, ValueError, KeyError) as e:
            print(f"  pixabay {query!r}: {e!r}", flush=True)
    return out


def _cut(url: str, dest: Path, start: float) -> bool:
    try:
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{start:.2f}", "-t", str(SEG_S), "-i", url, "-an",
                        "-vf", "scale=-2:1120,crop=540:960:(iw-540)/2:0,fps=24", "-c:v", "libx264", "-crf", "24", "-pix_fmt", "yuv420p", str(dest)],
                       check=True, timeout=180)
        return dest.exists()
    except (subprocess.SubprocessError, OSError):
        return False


def fetch_stock(query: str, dest: Path) -> dict | None:
    """first stock clip that decodes, moves, is bright enough and that the vision check confirms (no person, no text, right subject)"""
    for item in stock_candidates(query)[:5]:
        dur = _duration(item["url"])
        if dur < SEG_S + 1 or not _cut(item["url"], dest, max(0.0, min(dur * 0.25, dur - SEG_S - 0.5))):
            continue
        verdict = _relevant(dest, query) if _usable(dest) else False
        if verdict is None:                           # no vision answer: stock is keyword-searched, so a clip with no person/text is accepted
            verdict = True
        if verdict:
            return {"file": dest.name, "id": item["id"], "title": item["title"][:80], "center": "stock", "license": item["license"], "source": item["source"]}
        dest.unlink(missing_ok=True)
    return None


def fetch(query: str, dest: Path) -> dict | None:
    """first relevant NASA clip that decodes, is bright enough and moves -> dest (9:16, 540x960, 24 fps, no audio)."""
    weak = 2 if len(_terms(query)) >= 2 else 1               # a multi-word request must match on at least two words
    cands = [i for i in search_index(query) if i["hits"] >= weak]
    if len(cands) < 3:
        seen = {c["id"] for c in cands}
        cands += [i for i in search(query) if i["hits"] >= weak and i["id"] not in seen]
    for item in cands[:6]:
        url = _medium_url(item["id"])
        if not url:
            continue
        dur = _duration(url)
        if dur < SEG_S + 1:
            continue
        start = max(0.0, min(dur * 0.3, dur - SEG_S - 0.5))
        try:
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{start:.2f}", "-t", str(SEG_S), "-i", url, "-an",
                            "-vf", "scale=-2:1120,crop=540:960:(iw-540)/2:0,fps=24", "-c:v", "libx264", "-crf", "24", "-pix_fmt", "yuv420p", str(dest)],
                           check=True, timeout=180)
        except (subprocess.SubprocessError, OSError):
            continue
        verdict = _relevant(dest, query) if dest.exists() and _usable(dest) else False
        if verdict is None:                           # no vision answer: accept only if every requested word is in the clip's title
            verdict = all(w in item["title"].lower() for w in _terms(query))
        if verdict:
            return {"file": dest.name, "id": item["id"], "title": item["title"][:80], "center": item["center"], "license": "NASA media (public domain)",
                    "source": f"https://images.nasa.gov/details/{item['id']}"}
        dest.unlink(missing_ok=True)
    return fetch_stock(query, dest)


def ensure(spec: dict, run_dir: Path, need_pictures: dict[str, str] | None = None) -> dict[str, str]:
    """fetch footage for beats that ask for it (max 2 per Short), plus beats in need_pictures {key: subject} whose still could not be
    sourced (then real footage is the picture, up to 4 in total). Never raises: no footage -> the still is used."""
    vid = run_dir / "vid"
    got, credits = {}, {}
    cj = vid / "credits.json"
    if cj.exists():
        credits = json.loads(cj.read_text())
    need_pictures = need_pictures or {}
    for b in spec["beats"]:
        q = b.get("footage") or need_pictures.get(b["key"])
        if not q or len(got) >= (4 if need_pictures else 3 if (os.environ.get("PEXELS_API_KEY") or os.environ.get("PIXABAY_API_KEY")) else 2):
            continue
        vid.mkdir(parents=True, exist_ok=True)
        dest = vid / f"{b['key']}.mp4"
        try:
            if dest.exists() and _usable(dest) and credits.get(dest.name):
                meta = credits.get(dest.name)
            else:
                meta = fetch(str(q), dest)
        except (httpx.HTTPError, KeyError, ValueError, OSError) as e:
            print(f"  footage {b['key']}: {e!r}; keeping still", flush=True)
            meta = None
        if meta:
            got[b["key"]] = f"vid/{dest.name}"
            credits[dest.name] = meta
            print(f"  footage {b['key']}: {meta['id']}", flush=True)
        else:
            print(f"  footage {b['key']}: none for {q!r}; keeping still", flush=True)
    if credits:
        cj.write_text(json.dumps(credits, indent=1))
    return got
