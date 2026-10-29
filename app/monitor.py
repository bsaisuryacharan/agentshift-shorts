"""Hourly performance monitor (cloud, .github/workflows/monitor.yml): how are the uploaded Shorts doing against the target?

    python -m app.monitor

Reads every uploaded Short from state/*.json, fetches its public statistics from the YouTube Data API (YOUTUBE_API_KEY secret), appends one row per video
to data/performance.jsonl, and writes the summary (per-Short status vs the 1,000,000-view target, channel subscribers, YouTube Partner Programme progress,
lessons from the playbook) into assets/performance.json (read through insights.load()["performance"]), which the topic picker and script writer read. Private/unavailable videos are reported
as such, never as zero.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx

from . import targets

ROOT = Path(__file__).resolve().parents[1]
PERF = ROOT / "data" / "performance.jsonl"
INSIGHTS = ROOT / "assets" / "performance.json"      # its own file: the daily insights job writes insights.json, and two writers to one file collided
API = "https://www.googleapis.com/youtube/v3"
CHANNEL_ID = os.environ.get("CHANNEL_ID", "UCLlxxuBKbt7CFUXUuTh9MOg")      # Agent Shift


def uploaded_shorts(state_dir: Path = ROOT / "state") -> list[dict]:
    out = []
    for f in sorted(state_dir.glob("*.json")):
        try:
            st = json.loads(f.read_text())
        except ValueError:
            continue
        for sid, p in (st.get("projects") or {}).items():
            if p.get("uploaded", {}).get("id"):
                out.append({"spec_id": sid, "video_id": p["uploaded"]["id"], "title": p.get("title", ""), "url": p["uploaded"].get("url")})
    return out


def _secs(iso: str) -> int:
    import re
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return 0
    d, h, mi, se = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + se


def channel_shorts(key: str, channel_id: str = CHANNEL_ID, client: httpx.Client | None = None, limit: int = 50) -> list[dict]:
    """every public Short on the channel (<= 3 min), not only the ones this pipeline uploaded: the channel's real results are the learning signal"""
    c = client or httpx.Client(timeout=30)
    r = c.get(f"{API}/channels", params={"part": "contentDetails", "id": channel_id, "key": key})
    r.raise_for_status()
    items = r.json().get("items", [])
    if not items:
        return []
    uploads = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
    r = c.get(f"{API}/playlistItems", params={"part": "contentDetails", "playlistId": uploads, "maxResults": limit, "key": key})
    r.raise_for_status()
    ids = [it["contentDetails"]["videoId"] for it in r.json().get("items", [])]
    if not ids:
        return []
    r = c.get(f"{API}/videos", params={"part": "contentDetails,snippet", "id": ",".join(ids), "key": key})
    r.raise_for_status()
    return [{"spec_id": None, "video_id": v["id"], "title": v["snippet"]["title"], "url": f"https://youtube.com/shorts/{v['id']}"}
            for v in r.json().get("items", []) if 0 < _secs(v["contentDetails"].get("duration", "")) <= 180]


def fetch(video_ids: list[str], key: str, client: httpx.Client | None = None) -> dict[str, dict]:
    """statistics for public videos; ids YouTube does not return (private, deleted) are simply absent"""
    c = client or httpx.Client(timeout=30)
    out: dict[str, dict] = {}
    for i in range(0, len(video_ids), 50):
        r = c.get(f"{API}/videos", params={"part": "statistics,snippet", "id": ",".join(video_ids[i:i + 50]), "key": key})
        r.raise_for_status()
        for it in r.json().get("items", []):
            s = it.get("statistics", {})
            out[it["id"]] = {"views": int(s.get("viewCount", 0)), "likes": int(s.get("likeCount", 0)), "comments": int(s.get("commentCount", 0)),
                             "published_at": it["snippet"]["publishedAt"], "channel_id": it["snippet"]["channelId"]}
    return out


def channel_stats(channel_id: str, key: str, client: httpx.Client | None = None) -> tuple[int | None, int | None]:
    """(subscribers, total channel views); None where YouTube hides or lacks the number"""
    c = client or httpx.Client(timeout=30)
    r = c.get(f"{API}/channels", params={"part": "statistics", "id": channel_id, "key": key})
    r.raise_for_status()
    items = r.json().get("items", [])
    if not items:
        return None, None
    st = items[0]["statistics"]
    subs = None if st.get("hiddenSubscriberCount") else int(st.get("subscriberCount", 0))
    return subs, int(st["viewCount"]) if "viewCount" in st else None


def channel_subscribers(channel_id: str, key: str, client: httpx.Client | None = None) -> int | None:
    return channel_stats(channel_id, key, client)[0]


SNAP = ROOT / "data" / "channel_views.jsonl"


def snapshot(views: int | None, subs: int | None, path: Path = SNAP, now: datetime | None = None) -> None:
    """one row per run: the monthly goal is measured on total channel views (app/strategy.py)"""
    if views is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps({"ts": (now or datetime.now(UTC)).isoformat(timespec="minutes"), "views": views, "subs": subs}) + "\n")


def summarise(rows: list[dict], subscribers: int | None, now: datetime | None = None) -> dict:
    """rows: latest stats per video (see run()); returns the structure stored under insights['performance']"""
    now = now or datetime.now(UTC)
    shorts = []
    for r in rows:
        age_h = max(0.0, (now - datetime.fromisoformat(r["published_at"].replace("Z", "+00:00"))).total_seconds() / 3600)
        shorts.append({**{k: r[k] for k in ("spec_id", "video_id", "title", "views", "likes", "comments")}, **targets.status(r["views"], age_h)})
    recent = [s for s in shorts if s["age_h"] <= 24 * 90]
    views90 = sum(s["views"] for s in recent)
    best = max(shorts, key=lambda s: s["views"], default=None)
    return {"updated": now.isoformat(timespec="minutes"), "target_views_per_short": targets.TARGET["views_per_short"], "shorts": shorts[-12:],
            "best": {"title": best["title"], "views": best["views"]} if best else None,
            "ypp": targets.ypp_progress(subscribers or 0, views90, len(recent)) | {"subscribers_known": subscribers is not None},
            "on_track": sum(1 for s in shorts if s["status"] == "on_track"), "behind": sum(1 for s in shorts if s["status"] in ("behind", "far_behind"))}


def write_insights(perf: dict, path: Path = INSIGHTS) -> None:
    try:
        d = json.loads(path.read_text())
    except (OSError, ValueError):
        d = {}
    d["performance"] = perf
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(d, indent=1, ensure_ascii=False))


def run(state_dir: Path = ROOT / "state", perf_path: Path = PERF, insights_path: Path = INSIGHTS, key: str | None = None, client: httpx.Client | None = None,
        snap_path: Path | None = SNAP) -> dict:
    key = key or os.environ.get("YOUTUBE_API_KEY")
    vids = uploaded_shorts(state_dir)
    if not key:
        print("monitor: YOUTUBE_API_KEY not set")
        return {"shorts": len(vids), "error": "no api key"}
    try:
        known = {v["video_id"] for v in vids}
        vids += [v for v in channel_shorts(key, client=client) if v["video_id"] not in known]
    except (httpx.HTTPError, KeyError, ValueError) as e:
        print("monitor: channel uploads unavailable:", type(e).__name__)
    if not vids:
        print("monitor: no Shorts yet")
        return {"shorts": 0}
    stats = fetch([v["video_id"] for v in vids], key, client)
    now = datetime.now(UTC)
    rows, missing = [], []
    perf_path.parent.mkdir(parents=True, exist_ok=True)
    with open(perf_path, "a") as f:
        for v in vids:
            s = stats.get(v["video_id"])
            if not s:
                missing.append(v["video_id"])
                continue
            row = {**v, **s, "ts": now.isoformat(timespec="minutes")}
            rows.append(row)
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    subs, ch_views = channel_stats(rows[0]["channel_id"] if rows else CHANNEL_ID, key, client)
    if snap_path is not None:
        snapshot(ch_views, subs, snap_path, now)
    perf = summarise(rows, subs, now)
    perf["channel_views"] = ch_views
    perf["not_public_or_missing"] = missing
    from . import learning
    perf["lessons"] = learning.lessons(perf_path)
    write_insights(perf, insights_path)
    print(json.dumps({"shorts": len(rows), "missing": missing, "on_track": perf["on_track"], "behind": perf["behind"], "subs": subs}))
    return perf


if __name__ == "__main__":
    run()
    sys.exit(0)
