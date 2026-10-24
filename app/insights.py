"""Compact, committed insights the cloud pipeline can read (the raw trend/analytics reports only exist on the owner's Mac).

    python -m app.insights          # rebuild assets/insights.json from data/latest_*.json, then run deploy/sync_repo.py

auto.pick_topic and auto.write_spec read it via load(); it is advisory text for the LLM, never a source of facts for a script.
"""
from __future__ import annotations

import collections
import json
import re
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "insights.json"


def _ascii_ratio(s: str) -> float:
    return sum(c.isascii() for c in s) / max(len(s), 1)


def build(data: Path = ROOT / "data") -> dict:
    out: dict = {"generated_at": datetime.now(UTC).isoformat(timespec="seconds"), "channel": {}, "trending": []}
    ca = data / "latest_channel_analytics.json"
    if ca.exists():
        c = json.loads(ca.read_text())
        cur = (c.get("current_period") or {}).get("summary") or {}
        if c.get("status") == "ok" and cur:
            out["channel"] = {"period": f"{c['current_period']['start']}..{c['current_period']['end']}", "shorts": c["current_period"].get("short_rows"),
                              "views": cur.get("views"), "avg_view_seconds": cur.get("averageViewDuration"), "avg_view_pct": cur.get("averageViewPercentage"),
                              "net_subscribers": cur.get("netSubscribers"), "likes": cur.get("likes"), "shares": cur.get("shares"),
                              "caveat": "tiny sample" if (c["current_period"].get("short_rows") or 0) < 5 else "ok"}
    # what the pipeline itself has learned: every delivered Short's judge scores live in the ledger the cloud commits daily
    hist = data / "history.jsonl"
    if hist.exists():
        rows = []
        for line in hist.read_text().splitlines()[-60:]:
            try:
                h = json.loads(line)
            except ValueError:
                continue
            sc = h.get("scores") or {}
            if sc:
                rows.append({"title": h.get("title", "")[:80], "avg": round(sum(sc.values()) / len(sc), 1), "weakest": min(sc, key=sc.get)})
        if rows:
            rows.sort(key=lambda r: -r["avg"])
            weak = collections.Counter(r["weakest"] for r in rows).most_common(3)
            out["learned"] = {"shorts_scored": len(rows), "best": rows[:3], "worst": rows[-3:][::-1] if len(rows) > 3 else [],
                              "weakest_dimensions": [w for w, _ in weak]}
    tr = data / "latest_trend_report.json"
    if tr.exists():
        t = json.loads(tr.read_text())
        rows = [s for s in t.get("signals", []) if s.get("title") and _ascii_ratio(s["title"]) > 0.9]
        rows.sort(key=lambda s: -(s.get("metric") or 0))
        out["region"] = t.get("region")
        news = [s for s in t.get("signals", []) if s.get("source") in ("news", "nasa") and s.get("title") and _ascii_ratio(s["title"]) > 0.9]
        out["news"] = [re.sub(r"\s+[-|]\s+[^-|]{3,60}$", "", s["title"]).strip()[:110] for s in news[:12]]      # drop the " - Publisher" tail
        out["trending"] = [re.sub(r"#\w+", "", s["title"]).strip(" |-!") for s in rows[:12]]
    return out


def load() -> dict:
    try:
        return json.loads(OUT.read_text())
    except (OSError, ValueError):
        return {}


def hint(max_chars: int = 900) -> str:
    """one advisory paragraph for the LLM prompts ('' when there is nothing)"""
    i = load()
    parts = []
    c = i.get("channel") or {}
    if c.get("avg_view_pct") is not None:
        parts.append(f"Channel so far ({c['period']}, {c['caveat']}): {c['views']:.0f} views on {c['shorts']} Short(s), average viewed {c['avg_view_pct']:.0f}% "
                     f"({c['avg_view_seconds']:.0f}s), {c['net_subscribers']:.0f} net subs. Keep hooks fast and Shorts tight.")
    l = i.get("learned") or {}
    if l.get("shorts_scored"):
        parts.append(f"Judge history over {l['shorts_scored']} Shorts: strongest were " + "; ".join(f"'{r['title']}' ({r['avg']})" for r in l["best"]) +
                     (". Weakest were " + "; ".join(f"'{r['title']}' ({r['avg']})" for r in l["worst"]) if l.get("worst") else "") +
                     f". Dimensions that fail most: {', '.join(l['weakest_dimensions'])} - choose topics and angles that avoid those weaknesses.")
    if i.get("trending"):
        parts.append("Popular on YouTube now (inspiration only, do not copy titles): " + "; ".join(i["trending"][:6]))
    return " ".join(parts)[:max_chars]


if __name__ == "__main__":
    d = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(d, indent=1, ensure_ascii=False))
    print("wrote", OUT, "-", hint()[:200])
