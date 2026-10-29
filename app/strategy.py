"""Growth strategist: turns the monthly goal (targets.MONTH_GOAL, 1,000,000 channel views in a month) into today's plan.

    python -m app.strategy          # build assets/strategy.json and send the daily growth report to Telegram (daily insights job)

Measures: channel views gained since the start (data/channel_views.jsonl, written hourly by app.monitor), the pace of the last 3 days, the
projection to the deadline, the gap. Decides (only levers the system really controls): how many Shorts a day, which topics and formats to
double down on and which to drop (from the channel's own views per hour and the judge history), the packaging rules that the winners share.
Everything downstream reads it: the topic picker, the script writer, the schedule guard, and Claude in Telegram.
Honest by design: views cannot be ordered; the plan raises the odds (more good Shorts, more of what already works) and says plainly how far off it is.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from . import targets

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "strategy.json"
SNAP = ROOT / "data" / "channel_views.jsonl"
MAX_PER_DAY = 2                     # free AI quota allows about two full Shorts a day
STOP = {"the", "a", "an", "of", "to", "in", "is", "your", "you", "why", "how", "what", "that", "this", "and", "for", "shorts", "these", "sound", "fake", "but", "they're", "true"}


def _snaps(path: Path = SNAP) -> list[tuple[datetime, int]]:
    out = []
    if path.exists():
        for line in path.read_text().splitlines():
            try:
                r = json.loads(line)
                out.append((datetime.fromisoformat(r["ts"]), int(r["views"])))
            except (ValueError, KeyError, TypeError):
                continue
    return sorted(out)


def progress(snaps: list[tuple[datetime, int]], goal: dict = targets.MONTH_GOAL, today: date | None = None) -> dict:
    today = today or datetime.now(UTC).date()
    start, deadline = date.fromisoformat(goal["start"]), date.fromisoformat(goal["deadline"])
    days_total = (deadline - start).days
    days_left = max((deadline - today).days, 0)
    since = [(t, v) for t, v in snaps if t.date() >= start] or snaps[-1:]
    if not since:
        return {"goal": goal["views"], "deadline": goal["deadline"], "days_left": days_left, "measured": False}
    base, last = since[0][1], since[-1][1]
    gained = last - base
    recent = [(t, v) for t, v in since if t >= since[-1][0] - timedelta(days=3)]
    span_days = max((recent[-1][0] - recent[0][0]).total_seconds() / 86400, 0.0) if recent else 0.0
    pace = (recent[-1][1] - recent[0][1]) / span_days if span_days >= 0.5 else None
    need = (goal["views"] - gained) / max(days_left, 1)
    projected = gained + (pace or 0) * days_left
    return {"goal": goal["views"], "start": goal["start"], "deadline": goal["deadline"], "days_total": days_total, "days_left": days_left, "measured": True,
            "baseline_views": base, "channel_views": last, "gained": gained, "pct": round(100 * gained / goal["views"], 2),
            "pace_per_day": None if pace is None else int(pace), "needed_per_day": int(need), "projected": int(projected),
            "on_track": pace is not None and projected >= goal["views"]}


def _words(title: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{4,}", title.lower()) if w not in STOP}


def winners_and_flops(shorts: list[dict]) -> tuple[list[dict], list[dict]]:
    """the channel's own Shorts ranked by views per hour of age (fair to new and old)"""
    rows = [dict(s, vph=s["views"] / max(s.get("age_h") or 1, 1)) for s in shorts if s.get("views") is not None]
    rows.sort(key=lambda s: -s["vph"])
    return rows[:3], rows[-3:][::-1] if len(rows) > 3 else []


def plan(prog: dict, shorts: list[dict], fmt_scores: dict[str, float] | None = None) -> dict:
    top, flop = winners_and_flops(shorts)
    behind = not prog.get("on_track")
    per_day = MAX_PER_DAY if behind else 1
    fmt = sorted((fmt_scores or {}).items(), key=lambda kv: -kv[1])
    focus_words = sorted({w for s in top for w in _words(s["title"])})[:10]
    avoid_words = sorted({w for s in flop for w in _words(s["title"])} - set(focus_words))[:10]
    actions = [
        f"Make {per_day} Short{'s' if per_day > 1 else ''} a day" + (" (behind the pace: more good Shorts = more chances of a breakout)" if behind else "") + ".",
        "Double down on what already wins on this channel: " + "; ".join(f"'{s['title'][:50]}' ({s['views']:,} views)" for s in top) + "." if top else "",
        "Drop what flopped: " + "; ".join(f"'{s['title'][:40]}' ({s['views']:,})" for s in flop) + "." if flop else "",
        ("Prefer the formats the judge scores best: " + ", ".join(f for f, _ in fmt[:2]) + ".") if fmt else "",
        "Every Short: 25-35 s; a concrete, surprising claim with a number in the first 2 s; real footage; one twist per beat; end on a one-word question.",
        "When a big science or tech story breaks this week, explain it while it is hot (news hooks get pushed to new viewers).",
    ]
    return {"shorts_per_day": per_day, "focus_words": focus_words, "avoid_words": avoid_words,
            "winners": [{"title": s["title"], "views": s["views"]} for s in top], "flops": [{"title": s["title"], "views": s["views"]} for s in flop],
            "best_formats": [f for f, _ in fmt[:3]], "actions": [a for a in actions if a]}


def build(write: bool = True) -> dict:
    from . import insights, lessons
    perf = insights.load().get("performance") or {}
    prog = progress(_snaps())
    st = {"updated": datetime.now(UTC).isoformat(timespec="minutes"), "progress": prog, **plan(prog, perf.get("shorts") or [], lessons.format_boost())}
    if write:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(st, indent=1, ensure_ascii=False))
    return st


def load() -> dict:
    try:
        return json.loads(OUT.read_text())
    except (OSError, ValueError):
        return {}


def shorts_per_day() -> int:
    return int(load().get("shorts_per_day") or 1)


def status_line(st: dict | None = None) -> str:
    st = st if st is not None else load()
    p = st.get("progress") or {}
    if not p.get("measured"):
        return f"Goal: {targets.MONTH_GOAL['views']:,} channel views by {targets.MONTH_GOAL['deadline']} (measuring starts with the first hourly check)."
    pace = f"{p['pace_per_day']:,}/day" if p.get("pace_per_day") is not None else "not measured yet"
    return (f"Goal: {p['goal']:,} channel views by {p['deadline']} ({p['days_left']} days left). Gained {p['gained']:,} ({p['pct']}%). "
            f"Needed: {p['needed_per_day']:,}/day; current pace: {pace}; projected: {p['projected']:,}. "
            + ("ON TRACK." if p.get("on_track") else "BEHIND."))


def hint(max_chars: int = 900) -> str:
    """the first thing the picker and the writer read"""
    st = load()
    if not st:
        return ""
    return ("NORTH STAR - " + status_line(st) + " Today's plan: " + " ".join(st.get("actions", [])[1:5]))[:max_chars]


def report(st: dict) -> str:
    """the daily growth report sent to Telegram"""
    return ("📈 Daily growth report\n" + status_line(st) + "\n\nToday's plan:\n" + "\n".join(f"• {a}" for a in st.get("actions", [])) +
            "\n\nReply to talk it through with Claude.")


if __name__ == "__main__":
    st = build()
    print(status_line(st))
    if os.environ.get("TELEGRAM_BOT_TOKEN") and "--quiet" not in sys.argv:
        from . import chat
        chat.send(report(st), chat=os.environ.get("TELEGRAM_CHAT_ID"))
    sys.exit(0)
