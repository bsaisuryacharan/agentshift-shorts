"""Reference Shorts the owner saves as inspiration: what they are, why they work, and how Agent Shift can reuse the idea.

    python -m app.refs add <youtube url or id> [--note "why it was saved"]     # fetch title/channel/stats/transcript/thumbnails, analyse once (free LLM), save
    python -m app.refs list

Saved under assets/references/<video id>.json (+ a small thumbnail sheet). The picker reads the owner's planned ideas first (hint + ideas()), the writer
reads the lessons (hint()); each idea is crossed off by the topic tracker once a Short on that subject exists. Learn the shape, never copy: titles,
scripts and footage of the reference are never reused. The video, its frames and its transcript are not stored (the repo is public): only metadata and our analysis.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
DIR = ROOT / "assets" / "references"
UA = {"User-Agent": "AgentShiftShorts/1.0 (https://youtube.com/@agentshiftai)"}


def video_id(s: str) -> str | None:
    m = re.search(r"(?:shorts/|watch\?v=|youtu\.be/|embed/)([A-Za-z0-9_-]{11})", s) or re.fullmatch(r"([A-Za-z0-9_-]{11})", s.strip())
    return m.group(1) if m else None


def fetch_meta(vid: str, key: str | None = None, client=httpx) -> dict:
    """title and channel from oEmbed (no key); views, likes, duration, publish date from the Data API when a key exists"""
    meta: dict = {"id": vid, "url": f"https://www.youtube.com/shorts/{vid}"}
    try:
        r = client.get("https://www.youtube.com/oembed", params={"url": f"https://www.youtube.com/watch?v={vid}", "format": "json"}, headers=UA, timeout=25)
        r.raise_for_status()
        j = r.json()
        meta.update(title=j.get("title", ""), channel=j.get("author_name", ""), channel_url=j.get("author_url", ""))
    except (httpx.HTTPError, ValueError) as e:
        print(f"refs: oEmbed failed ({type(e).__name__})", flush=True)
    key = key or os.environ.get("YOUTUBE_API_KEY")
    if key:
        try:
            r = client.get("https://www.googleapis.com/youtube/v3/videos", params={"part": "statistics,contentDetails,snippet", "id": vid, "key": key}, timeout=25)
            it = (r.json().get("items") or [None])[0]
            if it:
                st = it.get("statistics", {})
                meta.update(views=int(st.get("viewCount", 0)), likes=int(st.get("likeCount", 0)), comments=int(st.get("commentCount", 0)),
                            published=it["snippet"].get("publishedAt"), duration=it["contentDetails"].get("duration"), tags=it["snippet"].get("tags", [])[:12],
                            title=meta.get("title") or it["snippet"].get("title", ""))
        except (httpx.HTTPError, ValueError, KeyError) as e:
            print(f"refs: stats unavailable ({type(e).__name__})", flush=True)
    return meta


def fetch_transcript(vid: str) -> str:
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        return " ".join(x.text for x in YouTubeTranscriptApi().fetch(vid, languages=["en"]))[:6000]
    except Exception as e:  # noqa: BLE001 - captions may be off; the analysis then uses title and stats only
        print(f"refs: no transcript ({type(e).__name__})", flush=True)
        return ""


def save_thumbs(vid: str, client=httpx) -> bool:
    """(not used by add(): another creator's frames do not belong in a public repo) three YouTube thumbnails stitched into one local sheet"""
    try:
        import cv2
        import numpy as np
        ims = []
        for n in ("hq1", "hq2", "hq3"):
            r = client.get(f"https://i.ytimg.com/vi/{vid}/{n}.jpg", headers=UA, timeout=25)
            im = cv2.imdecode(np.frombuffer(r.content, np.uint8), cv2.IMREAD_COLOR) if r.status_code == 200 else None
            if im is not None:
                ims.append(cv2.resize(im, (int(im.shape[1] * 240 / im.shape[0]), 240)))
        if ims:
            DIR.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(DIR / f"{vid}.jpg"), np.hstack(ims), [cv2.IMWRITE_JPEG_QUALITY, 70])
        return bool(ims)
    except Exception as e:  # noqa: BLE001
        print(f"refs: thumbnails skipped ({type(e).__name__})", flush=True)
        return False


ANALYST = ("You analyse one reference YouTube Short for the channel Agent Shift (curiosity explainers: science, space, nature, history, tech and engineering, big tech news "
           "explained; 25-35 s; free tools only). Say why it works and how Agent Shift can reuse the IDEA with its own topics and its own words. Return ONLY JSON: "
           '{"topic":"what it is about","format":"the shape in 6 words","hook":"how the first 2 seconds work","structure":["beat 1 (0-5 s): ...","..."],'
           '"visual_style":"what the viewer sees","why_it_works":["3-4 reasons"],"reuse":"one sentence: the transferable idea","adaptations":["5 concrete Short topics for Agent Shift that use '
           'this shape, each a real subject with a Wikipedia article, e.g. \'How a jet engine works, taken apart part by part\'"],"avoid":"what NOT to copy"}. '
           "Adaptations must be science/space/nature/history/engineering/tech-news subjects, never product reviews, tutorials or AI-tool demos.")


def analyse(meta: dict, transcript: str, note: str = "") -> dict:
    from . import auto
    user = (f"TITLE: {meta.get('title')}\nCHANNEL: {meta.get('channel')}\nSTATS: {meta.get('views', '?')} views, {meta.get('likes', '?')} likes, {meta.get('duration', '?')}\n"
            f"OWNER'S NOTE: {note or '(none)'}\nTRANSCRIPT:\n{transcript or '(no captions)'}")
    out, _ = auto.ask(ANALYST, user, prefer=["gemini", "groq", "openrouter"])
    return out if isinstance(out, dict) else {}


def add(url: str, note: str = "", analysis: dict | None = None, client=httpx) -> dict:
    vid = video_id(url)
    if not vid:
        raise ValueError(f"not a YouTube link or id: {url!r}")
    meta = fetch_meta(vid, client=client)
    tr = fetch_transcript(vid)
    a = analysis if analysis is not None else analyse(meta, tr, note)
    ref = {**meta, "saved": datetime.now(UTC).strftime("%Y-%m-%d"), "note": note, "analysis": a,
           "adaptations_used": []}
    DIR.mkdir(parents=True, exist_ok=True)
    (DIR / f"{vid}.json").write_text(json.dumps(ref, indent=1, ensure_ascii=False))
    return ref


def load_all(path: Path = DIR) -> list[dict]:
    out = []
    for f in sorted(path.glob("*.json")) if path.exists() else []:
        try:
            out.append(json.loads(f.read_text()))
        except ValueError:
            continue
    return sorted(out, key=lambda r: r.get("saved", ""), reverse=True)


def ideas(path: Path = DIR, limit: int = 12) -> list[str]:
    """the owner's planned ideas: adaptations of saved references not yet turned into a Short (the tracker drops the ones whose subject is covered)"""
    out = []
    for r in load_all(path):
        for a in (r.get("analysis") or {}).get("adaptations", []):
            if isinstance(a, str) and a not in r.get("adaptations_used", []) and a not in out:
                out.append(a)
    return out[:limit]


def hint(max_chars: int = 900, path: Path = DIR) -> str:
    """for the writer and the picker: the transferable idea of each saved reference, newest first"""
    rows = load_all(path)[:4]
    if not rows:
        return ""
    parts = []
    for r in rows:
        a = r.get("analysis") or {}
        if a.get("reuse"):
            parts.append(f"'{(r.get('title') or '')[:60]}' ({r.get('channel', '?')}): {a['reuse']}" + (f" Why it works: {'; '.join(a.get('why_it_works', [])[:2])}." if a.get("why_it_works") else ""))
    return ("Saved by the owner as inspiration (learn the shape, never copy): " + " | ".join(parts))[:max_chars] if parts else ""


def summary(path: Path = DIR) -> str:
    rows = load_all(path)
    if not rows:
        return "No saved references yet. Send me a Short link and say why it is useful."
    lines = []
    for r in rows[:15]:
        a = r.get("analysis") or {}
        lines.append(f"• {r.get('title', r['id'])[:70]} ({r.get('channel', '?')}, saved {r.get('saved')})\n  idea: {a.get('reuse', '(not analysed)')[:140]}")
    return "Saved references:\n" + "\n".join(lines) + f"\n\nPlanned from them: {len(ideas(path))} topic ideas."


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["add"] and len(a) >= 2:
        note = a[a.index("--note") + 1] if "--note" in a else ""
        ref = add(a[1], note)
        an = ref.get("analysis") or {}
        print(f"saved {ref['id']}: {ref.get('title')} ({ref.get('channel')})")
        print("idea:", an.get("reuse", "(no analysis: the free AI was busy; it can be added later)"))
        print("planned topics:", "; ".join(an.get("adaptations", [])[:5]))
        sys.exit(0)
    if a[:1] == ["list"]:
        print(summary())
        sys.exit(0)
    sys.exit(__doc__)


def mark_used(text: str, path: Path = DIR) -> int:
    """a Short on this subject was picked: cross off the saved adaptations that cover the same subject (shared distinctive word); returns how many"""
    from . import tracker
    mine, n = tracker._tokens(text), 0
    if not mine:
        return 0
    for f in sorted(path.glob("*.json")) if path.exists() else []:
        try:
            r = json.loads(f.read_text())
        except ValueError:
            continue
        hit = [a for a in (r.get("analysis") or {}).get("adaptations", []) if isinstance(a, str) and a not in r.get("adaptations_used", []) and mine & tracker._tokens(a)]
        if hit:
            r.setdefault("adaptations_used", []).extend(hit)
            f.write_text(json.dumps(r, indent=1, ensure_ascii=False))
            n += len(hit)
    return n
