"""vidIQ market intelligence the cloud pipeline can read: a committed snapshot, assets/vidiq.json.

The vidIQ connector only exists inside the owner's Claude session (it is not reachable from the GitHub runner), so the snapshot is refreshed
there (about 40 credits per refresh: breakout Shorts per niche, matching keywords, trending Shorts by views per hour) and committed.
Source order: this committed snapshot is the primary source (always available in the cloud); live vidIQ queries are secondary and only used to refresh it.
It also carries the owner's own channel analytics (per-Short views, what pattern works, direction, visual level).
The pipeline reads it through hint(); like insights it is advisory text for the LLM, never a source of facts for a script.
"""
from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "assets" / "vidiq.json"
STALE_DAYS = 21


def load(path: Path = PATH) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def age_days(d: dict, today: date | None = None) -> int | None:
    try:
        return ((today or datetime.now(UTC).date()) - date.fromisoformat(d["fetched"])).days
    except (KeyError, ValueError):
        return None


def hint(max_chars: int = 1800, path: Path = PATH) -> str:
    """advisory paragraph: proven title shapes, low-competition search terms, what is breaking out now ('' without a snapshot or when stale)"""
    d = load(path)
    age = age_days(d)
    if not d or age is None or age > STALE_DAYS:
        return ""
    parts = []
    ch = d.get("channel") or {}
    if ch.get("findings"):
        parts.append("This channel's own results: " + " ".join(ch["findings"][:3]) + f" Direction: {ch.get('direction', '')} Visuals: {ch.get('visual_level', '')}")
    if d.get("patterns"):
        parts.append("vidIQ market data: " + " ".join(d["patterns"][:4]))
    kws = [k for k in d.get("keywords", []) if (k.get("competition") or 100) <= 50]
    kws.sort(key=lambda k: -((k.get("monthly") or 0) * (1 + max(k.get("growth_pct") or 0, 0) / 200)))
    if kws:
        parts.append("Search terms people actually use (low competition): " + ", ".join(f"'{k['term']}'" for k in kws[:5]) + ".")
    outl = sorted(d.get("outliers", []), key=lambda o: -o.get("breakout", 0))
    if outl:
        parts.append("Recent breakout Shorts from small channels (study the hook, never copy): " +
                     "; ".join(f"'{o['title'][:55]}' ({o['views']:,} views, {o['subs']:,} subs)" for o in outl[:4]))
    return " ".join(parts)[:max_chars]


def topic_ideas(path: Path = PATH, limit: int = 6) -> list[str]:
    """proven titles (snapshot, not stale) to show the topic picker as examples of angles that break out"""
    d = load(path)
    age = age_days(d)
    if not d or age is None or age > STALE_DAYS:
        return []
    rows = sorted(d.get("outliers", []) + d.get("trending_space_shorts", []), key=lambda o: -(o.get("breakout") or 0))
    return [r["title"] for r in rows[:limit]]
