"""Variety supervisor: the owner's complaint "all videos seem to be almost the same", answered by bookkeeping, not another prompt hope.

The pipeline maps one look per format (looks.DEFAULT_BY_FORMAT), so unless code intervenes every myth_vs_fact Short inherits the same
swiss-grid visual language. This module keeps a small rolling ledger of what the recent APPROVED Shorts actually looked like and offers:

    adjust_look(choice, fmt)   rotates the look away from the uses the last Shorts made of it (candidates: looks.CANDIDATES per format)
    brief(fmt)                 a "STAND OUT" block injected into the writer prompt: recent looks/themes/techniques, a banned look and
                               one fresh motion technique the current renderer supports
    record(spec)               appends the ledger entry at approval time (written beside data/history.jsonl)

Variety is decided by code (record/adjust/brief), so it holds even when the writer ignores the prompt; the brief only steers composition
on top. No LLM, no network: the ledger stays data/style_ledger.json, newest last, trimmed to KEEP entries.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "data" / "style_ledger.json"
KEEP = 12                            # rolling window: only the most recent Shorts constrain variety

# motion techniques the current renderer supports (app.auto HUD_TYPES + app.gallery_hf ENABLED + graphic beats), as recipe tags.
# brief() offers the first tag no recent Short used, so every Short features at least one never-recently-seen motion idea.
TECH_MENU = {
    "bars": "lead one beat with a live bars element: two real values racing (bars never stand still, animate the stagger)",
    "line": "lead one beat with a line element: a trend line drawing itself as it is narrated",
    "ring": "lead one beat with a ring element: a percentage dial that fills in on the spoken word",
    "delta": "lead one beat with a delta element: a big +/- number or percentage slamming in",
    "kinetic": "lead one beat with the kinetic element: pure kinetic type, no picture at all",
    "tape": "lead one beat with a tape element as a ticker, updated twice within the beat",
    "toast": "one notification-style toast beat carrying a headline fact",
    "rows": "lead one beat with rows as an animated stat table, one row per spoken word",
    "chain": "lead one beat with chain: a step diagram wiring itself together as narrated",
    "list": "lead one beat with list: a numbered reveal that lands item by item",
    "cursor": "one cursor element pointing at the exact detail the narration mentions",
    "hf": "let a hf gallery component carry a beat (a component no recent Short used)",
    "pure_graphic": "one beat fully graphic:true: no picture, the look's designed ground + big type + one data element",
}


def entries() -> list[dict]:
    try:
        return json.loads(PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def _write(runs: list[dict]) -> None:
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(json.dumps(runs[-KEEP:], ensure_ascii=False), encoding="utf-8")


def _techniques(spec: dict) -> list[str]:
    out = []
    for b in spec.get("beats", []):
        for e in b.get("hud", []):
            if e.get("t") == "hf":
                out.append("hf")
            elif e.get("t") in TECH_MENU:
                out.append(e["t"])
        if b.get("graphic") and not any(k in b for k in ("photo", "footage", "prompt")):
            out.append("pure_graphic")
    return sorted(set(out))


def record(spec: dict) -> None:
    """append what the approved Short actually looked like; tolerant of failures (recording must never break delivery)"""
    try:
        runs = entries()
        runs.append({"date": datetime.now(UTC).date().isoformat(), "id": spec.get("id", ""), "title": (spec.get("title") or "")[:80],
                     "format": spec.get("format"), "look": spec.get("look"), "theme": spec.get("theme"),
                     "techniques": sorted(set(spec.get("techniques") or [])) or _techniques(spec)})
        _write(runs)
    except OSError:
        pass


def _last_used(tag: str) -> int:
    """how many entries back the tag's latest use is (-1 = never)"""
    for i, r in enumerate(reversed(entries())):
        if tag in (r.get("techniques") or []):
            return i
    return -1


def _rested() -> str:
    """a technique whose latest use is at least 3 Shorts back, or never used; fall back to the least recently used one"""
    tags = [t for t in TECH_MENU if not 0 <= _last_used(t) < 3]    # never used, or rested ≥3 Shorts
    if tags:
        return tags[0]
    return sorted(TECH_MENU, key=_last_used)[-1]


def adjust_look(choice: str | None, fmt: str | None = None) -> str:
    """pick a look the recent Shorts did not exhaust: candidates that fit the format, least recently used wins"""
    from . import looks
    cands = looks.CANDIDATES.get(fmt or "", []) or [looks.pick(choice, fmt)]
    used = [e.get("look") for e in entries()[-3:]]          # the last three Shorts must not all repeat one look
    fresh = [c for c in cands if c not in used]
    if fresh:
        return fresh[len(entries()) % len(fresh)]           # deterministic rotation rather than a wait for fancy random
    return cands[len(entries()) % len(cands)]               # every fitting look is burnt: cycle them anyway (rotation >= repetition)


def brief(fmt: str | None = None) -> str:
    """the STAND OUT block for the writer prompt; "" before any Short was approved"""
    runs = entries()
    if not runs:
        return ""
    recent = runs[-4:]
    banned = sorted({str(e.get("look") or "?") for e in runs[-2:]})          # the last two Shorts' looks, both now USED OUT
    from . import looks
    menu = looks.CANDIDATES.get(fmt or "", [])
    allowed = "; ".join(c for c in menu if c not in banned)[:260]
    themes_recent = [str(e.get("theme") or "?") for e in runs[-3:]]
    used_recently = sorted({t for e in recent for t in (e.get("techniques") or [])})
    lines = ["VARIETY (unbreakable): the last Shorts were: " + " | ".join(
        f"{e.get('date')} {e.get('format')} → {e.get('look')} (theme {e.get('theme')})" for e in recent) + ".",
        f"- Visual language: {' and '.join(banned)} {('is' if len(banned) == 1 else 'are')} now USED OUT. This Short must not read like it: "
        f"pick a different theme-coherent look. Fitting looks: {allowed}.",
        f"- Theme: recent themes were {', '.join(themes_recent)} — pick a DIFFERENT top-level theme this time if the subject allows.",
        f"- Motion ideas used too recently (do not lead a beat with these): {', '.join(used_recently) or 'none'}",
        f"- FEATURE one motion idea no recent Short led with: {TECH_MENU[_rested()]}",
        "Never two consecutive Shorts in the same rhythm: alternate wide/establishing first beats with macro-detail first beats, "
        "and vary where the hook type sits on the frame."]
    return "\nVARIETY BRIEF — STAND OUT FROM THE PREVIOUS SHORTS:\n" + "\n".join(lines)
