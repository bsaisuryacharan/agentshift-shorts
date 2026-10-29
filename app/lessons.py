"""Self-learning from the judge: every scored attempt is written to data/judge_notes.jsonl, its fixes are sorted into recurring complaint
classes, and the classes that keep coming back become standing rules for the writer (applied from the first attempt, not after a rejection).
It also learns which formats score best, which the format rotation uses to break ties.

    record(spec, scores, fixes)        after every judged attempt (auto.finish)
    rules() -> [str]                   standing writer rules, most frequent complaint first
    format_boost() -> {format: score}  average judge score per format (only formats with >= 2 attempts)

Views and retention are learned separately (app.learning); this module is only about what the judge rejects, which is what blocks delivery.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NOTES = ROOT / "data" / "judge_notes.jsonl"
WINDOW = 30              # attempts looked at
MIN_COUNT = 2            # a complaint must recur before it becomes a rule

CLASSES = [
    ("ai_render", re.compile(r"generic|ai[- ]generated|\brender|artificial|stylized|toy model|sci-?fi|cgi|fake[- ]looking|unrealistic|not (?:an )?accurate (?:model|depiction)", re.I),
     "Never show a specific named real object (spacecraft, probe, instrument, rocket, landmark, animal species) as an AI image: give that beat a 'photo' or "
     "'footage' search term so a real picture is used. AI images only for abstract or scale illustrations."),
    ("number_mismatch", re.compile(r"discrepan|narration says|does(?:n't| not) match|mismatch|inconsistent|contradict", re.I),
     "Every number on screen must be exactly a number spoken in the narration (same value, same unit)."),
    ("text_render", re.compile(r"garbled|typo|merged|misspel|symbols|unreadable|illegible", re.I),
     "On-screen text: real words only, at most 4 words per element, no symbols or abbreviations."),
    ("safe_zone", re.compile(r"safe zone|bottom edge|too close to the|clipp|cut off|overlap|ui elements", re.I),
     "Keep every text element in the middle of the screen; nothing near the bottom or the edges, never two text elements at once."),
    ("outdated", re.compile(r"current data|as of \d|outdated|out of date|latest figure", re.I),
     "Give time-dependent figures with their year ('24 billion km in 2024')."),
    ("hook", re.compile(r"\bhook\b|opening|first frame|intrigue|too generic", re.I),
     "Open with the single most surprising concrete claim and a number in the first 2 seconds; never a title like 'facts about X'."),
    ("consistency", re.compile(r"consisten|visual language|disconnected|clash|different style", re.I),
     "One visual style across the Short: real photos and footage graded alike, no mix of cartoon and photo."),
]


def classify(fix: str) -> list[str]:
    return [name for name, rx, _ in CLASSES if rx.search(fix)]


def record(spec: dict, scores: dict, fixes: list[str], path: Path = NOTES) -> None:
    row = {"spec_id": spec.get("id"), "title": spec.get("title"), "format": spec.get("format"), "scores": scores,
           "avg": round(sum(scores.values()) / len(scores), 2) if scores else None,
           "classes": sorted({c for f in fixes for c in classify(str(f))}), "fixes": [str(f)[:240] for f in fixes][:8]}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        pass


def _rows(path: Path = NOTES) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines()[-WINDOW:]:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def rules(path: Path = NOTES, limit: int = 5) -> list[str]:
    counts: dict[str, int] = {}
    for r in _rows(path):
        for c in r.get("classes", []):
            counts[c] = counts.get(c, 0) + 1
    text = {name: rule for name, _, rule in CLASSES}
    top = sorted((c for c, n in counts.items() if n >= MIN_COUNT and c in text), key=lambda c: -counts[c])
    return [f"{text[c]} (judge complaint in {counts[c]} of the last {len(_rows(path))} attempts)" for c in top[:limit]]


def format_boost(path: Path = NOTES) -> dict[str, float]:
    by: dict[str, list[float]] = {}
    for r in _rows(path):
        if r.get("format") and r.get("avg") is not None:
            by.setdefault(r["format"], []).append(r["avg"])
    return {f: round(sum(v) / len(v), 2) for f, v in by.items() if len(v) >= 2}
