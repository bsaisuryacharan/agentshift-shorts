"""Idea bank: formats, hooks and ideas that work on other Shorts channels (assets/idea_bank.json), as direction for the picker and the writer.

    python -m app.ideabank          # refresh 'recent' from the reference channels (YouTube Data API key; ~100 units per channel)

Seeded from vidIQ (titles, views, transcripts of the best Higgsfield Shorts); refreshed in the cloud by the daily insights job.
Learn the shape, never copy: titles, scripts and footage of other channels are never reused.
"""
from __future__ import annotations

import html
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "assets" / "idea_bank.json"
API = "https://www.googleapis.com/youtube/v3"


def load(path: Path = PATH) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def hint(max_chars: int = 1400, path: Path = PATH) -> str:
    """advisory paragraph for the picker and the writer: formats that break out, hook patterns, fresh breakouts from the reference channels"""
    d = load(path)
    if not d:
        return ""
    parts = []
    if d.get("formats"):
        parts.append("Formats that break out on other channels: " + "; ".join(f"{f['name']} ({f['shape']})" for f in d["formats"][:6]))
    if d.get("hooks"):
        parts.append("Hook patterns: " + " ".join(d["hooks"][:4]))
    recent = sorted(d.get("recent") or [], key=lambda r: -r.get("views", 0))[:5]
    if recent:
        parts.append("Breakouts this month on reference channels (learn the angle, never copy): " +
                     "; ".join(f"'{r['title'][:60]}' ({r['views']:,})" for r in recent))
    return " ".join(parts)[:max_chars]


def ideas(limit: int = 8, path: Path = PATH) -> list[str]:
    """titles worth learning from for the topic picker: fresh breakouts first, then the seeded ideas"""
    d = load(path)
    rows = sorted(d.get("recent") or [], key=lambda r: -r.get("views", 0)) + sorted(d.get("ideas") or [], key=lambda r: -r.get("views", 0))
    seen, out = set(), []
    for r in rows:
        if r["title"] not in seen and "format only" not in r.get("niche", ""):
            seen.add(r["title"])
            out.append(r["title"])
    return out[:limit]


def refresh(key: str | None = None, path: Path = PATH, client=httpx, days: int = 30) -> int:
    """the most-viewed Shorts of the last `days` on each reference channel -> d['recent']; returns how many were found"""
    key = key or os.environ.get("YOUTUBE_API_KEY")
    d = load(path)
    if not key or not d.get("reference_channels"):
        print("ideabank: no API key or no reference channels; skipped")
        return 0
    since = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    found: dict[str, dict] = {}
    for ch in d["reference_channels"]:
        try:
            r = client.get(f"{API}/search", params={"part": "snippet", "channelId": ch["id"], "type": "video", "videoDuration": "short", "order": "viewCount",
                                                     "publishedAfter": since, "maxResults": 5, "key": key}, timeout=25)
            r.raise_for_status()
            for it in r.json().get("items", []):
                found[it["id"]["videoId"]] = {"channel": ch["name"], "title": html.unescape(it["snippet"]["title"])}
        except (httpx.HTTPError, KeyError, ValueError) as e:
            print(f"ideabank {ch['name']}: {type(e).__name__}")
    if found:
        r = client.get(f"{API}/videos", params={"part": "statistics", "id": ",".join(list(found)[:50]), "key": key}, timeout=25)
        r.raise_for_status()
        for it in r.json().get("items", []):
            found[it["id"]]["views"] = int(it.get("statistics", {}).get("viewCount", 0))
    d["recent"] = sorted(({**v, "url": f"https://youtube.com/shorts/{k}"} for k, v in found.items() if v.get("views")), key=lambda v: -v["views"])[:30]
    d["recent_updated"] = datetime.now(UTC).isoformat(timespec="minutes")
    path.write_text(json.dumps(d, indent=1, ensure_ascii=False))
    print(f"ideabank: {len(d['recent'])} recent breakouts from {len(d['reference_channels'])} channels")
    return len(d["recent"])


if __name__ == "__main__":
    refresh()
    sys.exit(0)
