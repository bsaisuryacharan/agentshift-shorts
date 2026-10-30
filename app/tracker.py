"""Topic tracker: the system never makes a Short about a subject it has already covered.

    repeat_of(wiki, topic) -> the earlier row that covers the same subject, or None
    covered()              -> readable list of every subject so far (for the picker's prompt, /topics and Claude)

Built on the ledger data/topics.jsonl (every topic ever started and what became of it). A subject counts as covered when it was delivered/uploaded
(forever), made as a draft or started and lost (90 days), and a failed try is only retried after 3 days. Matching is by SUBJECT, not by exact title:
"Hubble Space Telescope" and "Hubble Deep Field" are the same subject because they share the distinctive word "hubble"; generic words (space,
telescope, earth, black, history ...) never make two topics the same on their own.
"""
from __future__ import annotations

import datetime as dt
import difflib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOPICS = ROOT / "data" / "topics.jsonl"
KEEP_DAYS = {"delivered": 3650, "uploaded": 3650, "draft": 90, "started": 90, "parked": 3}
GENERIC = {"space", "telescope", "earth", "black", "hole", "world", "ancient", "universe", "planet", "science", "history", "really", "truth", "about", "secret",
           "mystery", "facts", "extreme", "human", "humans", "what", "that", "this", "with", "from", "behind", "story", "nobody", "fully", "explain", "became",
           "versus", "event", "theory", "effect", "story", "first", "great", "deep", "light", "water", "energy", "years", "year", "ocean", "mission", "station",
           "star", "stars", "solar", "system", "life", "ever", "most", "than", "like", "does", "work", "works", "how", "the", "and", "your", "into", "mechanism"}


def _tokens(*texts: str) -> set[str]:
    words = set()
    for t in texts:
        t = re.sub(r"\(.*?\)", " ", t or "")
        words |= {w for w in re.findall(r"[a-z]{5,}", t.lower()) if w not in GENERIC}
    return words


def _norm(t: str) -> str:
    return re.sub(r"[^a-z0-9]", "", re.sub(r"\(.*?\)", "", (t or "").lower()))


def rows(path: Path = TOPICS) -> list[dict]:
    out = []
    if path.exists():
        for line in path.read_text().splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


def _live(rs: list[dict], today: dt.date) -> list[dict]:
    """rows still blocking a subject: one per subject, the strongest outcome wins; expired rows drop out"""
    best: dict[str, dict] = {}
    for r in rs:
        key = _norm(r.get("wiki") or r.get("topic"))
        try:
            age = (today - dt.date.fromisoformat(r["date"])).days
        except (KeyError, ValueError):
            continue
        keep = KEEP_DAYS.get(r.get("outcome"), 3)
        if not key or age > keep:
            continue
        if key not in best or keep >= KEEP_DAYS.get(best[key].get("outcome"), 3):
            best[key] = r
    return list(best.values())


def repeat_of(wiki: str, topic: str = "", path: Path = TOPICS, today: dt.date | None = None) -> dict | None:
    today = today or dt.date.today()
    mine_norm, mine_tok = _norm(wiki or topic), _tokens(wiki, topic if not wiki else "")
    for r in _live(rows(path), today):
        theirs_norm = _norm(r.get("wiki") or r.get("topic"))
        if mine_norm and (mine_norm == theirs_norm or difflib.SequenceMatcher(None, mine_norm, theirs_norm).ratio() >= 0.85):
            return r
        if mine_tok and mine_tok & _tokens(r.get("wiki", ""), ""):          # the same distinctive word in the subject's own title
            return r
    return None


def covered(path: Path = TOPICS, today: dt.date | None = None, limit: int = 80) -> list[str]:
    """one readable line per live subject, newest first: 'Mariana Trench (delivered 2026-10-29)'"""
    live = sorted(_live(rows(path), today or dt.date.today()), key=lambda r: r.get("date", ""), reverse=True)
    return [f"{r.get('wiki') or r.get('topic')} ({r.get('outcome')} {r.get('date')})" for r in live][:limit]
