"""Real footage cutaways from the NASA Image and Video Library (no key; NASA media is generally public domain, credited anyway).

A beat may carry  "footage": "orbital debris"  (what to look for). The clip replaces that beat's still as a moving background;
if nothing relevant is found the beat keeps its generated still, so footage is always an upgrade, never a failure.

    ensure(spec, run_dir) -> {beat_key: "vid/<key>.mp4"}   (also writes vid/credits.json)
"""
from __future__ import annotations

import json
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


def _relevant(path: Path, query: str) -> bool:
    """a vision model must confirm the clip's frame shows what was asked for; any doubt or failure = not relevant (never use unverified footage)."""
    try:
        from . import auto
        cap = cv2.VideoCapture(str(path))
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(cap.get(cv2.CAP_PROP_FRAME_COUNT) * 0.5))
        ok, f = cap.read()
        cap.release()
        if not ok:
            return False
        jpg = cv2.imencode(".jpg", cv2.resize(f, (270, 480)), [cv2.IMWRITE_JPEG_QUALITY, 80])[1].tobytes()
        out, _ = auto.ask('You check stock footage for a science explainer. Reply ONLY JSON {"relevant": true|false, "shows": "<=8 words"}. '
                          "relevant=true only if the frame clearly shows (or is an obviously fitting illustration of) the requested subject; people, interiors, aircraft cockpits, "
                          "streets and unrelated objects are NOT relevant unless requested.", f"REQUESTED SUBJECT: {query}", image=jpg)
        print(f"  footage check {query!r}: {out}", flush=True)
        return bool(out.get("relevant"))
    except Exception as e:
        print(f"  footage check failed ({e!r}); not using it", flush=True)
        return False


def fetch(query: str, dest: Path) -> dict | None:
    """first relevant NASA clip that decodes, is bright enough and moves -> dest (9:16, 540x960, 24 fps, no audio)."""
    weak = 2 if len(_terms(query)) >= 2 else 1               # a multi-word request must match on at least two words
    for item in [i for i in search(query) if i["hits"] >= weak][:6]:
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
        if dest.exists() and _usable(dest) and _relevant(dest, query):
            return {"file": dest.name, "id": item["id"], "title": item["title"][:80], "center": item["center"], "license": "NASA media (public domain)",
                    "source": f"https://images.nasa.gov/details/{item['id']}"}
        dest.unlink(missing_ok=True)
    return None


def ensure(spec: dict, run_dir: Path) -> dict[str, str]:
    """fetch footage for beats that ask for it (max 2 per Short). Never raises: no footage -> the still is used."""
    vid = run_dir / "vid"
    got, credits = {}, {}
    cj = vid / "credits.json"
    if cj.exists():
        credits = json.loads(cj.read_text())
    for b in spec["beats"]:
        q = b.get("footage")
        if not q or len(got) >= 2:
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
