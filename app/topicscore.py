"""Topic intelligence: what kind of topic is this, would a stranger stop for it, and how has that kind of topic done on THIS channel?

    topic_class(text)        -> one class name (awe_scale, inside_machine, myth_fact, what_if, earth_hazard, history_event, jargon_science, ai_tips, tech_explainer, general)
    format_of(title)         -> the Shorts format a published title was made in (best effort, from its framing words)
    curiosity(text)          -> float, a transparent rubric: familiar noun, number, tension framing up; jargon, abstract institutions down
    class_stats(shorts)      -> {class: {"n", "mean_log_views", "boost"}} from the channel's own Shorts (all of them, shrunk towards the channel mean)
    format_stats(shorts)     -> the same per format
    topic_boost(text, shorts)-> curiosity + learned class boost, the single number the picker adds to its score
    hint(shorts)             -> a short block for the picker prompt: what has won, what to avoid

Why this exists (audit 2026-11-10): the picker scored candidates by how much stock footage existed, not by whether anyone would click. On 30 Shorts the winners were awe or
"how does the thing you know work" topics with a familiar noun (Space Is Too Big For Your Brain 1.7k, Inside a Submarine 1.1k, Antarctic ozone hole myth 980, Jupiter what-if 873),
and the flops were jargon or abstract history (Cosmic Microwave Background 55, Solar Sails 39, Y2K 37) and AI-tips listicles (24-33). The sample is small, so every learned boost is
shrunk towards the channel mean and capped: it nudges the pick, it never overrides it.
"""
from __future__ import annotations

import math
import re
import statistics

CLASSES: list[tuple[str, re.Pattern]] = [
    ("ai_tips", re.compile(r"\b(?:prompts?|ai tricks?|free ai|chatgpt|interview|resume|side hustle|productivity|automate|no[- ]code|claude code|tutorial|tips?)\b", re.I)),
    ("what_if", re.compile(r"\bwhat if\b", re.I)),
    ("myth_fact", re.compile(r"\b(?:myth|truth about|true\b|sound fake|really\b|misconception|lie|lied|actually)\b", re.I)),
    ("inside_machine", re.compile(r"\b(?:inside|how (?:it|a|an|the)?\s*\w*\s*works?|how .{2,30} works?|anatomy|parts?|system|engine|machine|submarine|reactor|turbine|vault|mechanism)\b", re.I)),
    ("awe_scale", re.compile(r"\b(?:too big|how (?:big|long|far|fast|much|massive|widespread|old)|scale|light[- ]years?|universe|billion|trillion|speed of light|moving|km/h|km per)\b", re.I)),
    ("earth_hazard", re.compile(r"\b(?:volcano|volcanic|eruption|krakatoa|ozone|coral|climate|ocean|trench|earthquake|tsunami|glacier|ice sheet|hurricane|asteroid|meteor|solar storm|carrington|permafrost)\b", re.I)),
    ("history_event", re.compile(r"\b(?:history|year without|\bbug\b|y2k|timeline|ago|century|ancient|empire|war|library of|voynich|antikythera|date by date|\d{3,4}\s?(?:bce|ce|bc|ad)?\b)", re.I)),
    ("tech_explainer", re.compile(r"\b(?:turing|computer|chip|semiconductor|internet|starlink|satellite|google|iphone|phone|algorithm|software|robot|quantum|ai\b|artificial intelligence)\b", re.I)),
]
JARGON = re.compile(r"(?i:\b(?:cosmic microwave|microwave background|magnetar|boltzmann|lagrange|bottleneck|entanglement|eccentric|paradox|bleaching events?|"
                    r"catastrophe theory|stratigraphy|heliosphere|baryon|spectroscop\w*|photometr\w*|isotop\w*|polymer\w*|cosmological|extremophile)\b)|\b[A-Z]{3,}\b")
ABSTRACT = re.compile(r"\b(?:program(?:me)?|agency|administration|institute|center|centre|committee|initiative|framework|policy|history of|growth of|how .{2,25} grew)\b", re.I)
FAMILIAR = re.compile(r"\b(?:space|moon|sun|earth|mars|jupiter|saturn|planet|universe|brain|human body|heart|ocean|sea|volcano|submarine|plane|jet|rocket|robot|phone|iphone|google|"
                      r"computer|internet|ai\b|dinosaur|shark|octopus|cat|dog|fire|lightning|storm|ice|gold|money|sleep|dream|memory|time|light|speed|gravity|black hole|"
                      r"nuclear|bomb|mount everest|everest|titanic|pyramid|egypt|rome|moon landing|apollo|nasa|elon|tesla|bitcoin)\b", re.I)
FORMAT_FRAMES: list[tuple[str, re.Pattern]] = [
    ("what_if", re.compile(r"\bwhat if\b", re.I)),
    ("myth_vs_fact", re.compile(r"\b(?:myth vs|truth about|sound fake|true\b|myth)\b", re.I)),
    ("unsolved", re.compile(r"\b(?:nobody can|mystery|unsolved|paradox|can't explain)\b", re.I)),
    ("anatomy", re.compile(r"\binside\b", re.I)),
    ("how_it_works", re.compile(r"\bhow\b.{0,40}\bworks?\b|\bhow it works\b", re.I)),
    ("ranked", re.compile(r"\b(?:top \d|\d+ extreme|extreme facts|ranked|\d+ (?:facts|ways|things))\b", re.I)),
    ("versus", re.compile(r"\b(?:versus|vs\.?)\b", re.I)),
    ("timeline", re.compile(r"\b(?:date by date|timeline|year\b.{0,20}\bvanished|journey|how .{2,30} happened)\b", re.I)),
    ("scale", re.compile(r"\bhow (?:big|long|far|fast|much|massive|widespread|old)\b|\btoo big\b|\bmoving\b", re.I)),
    ("story", re.compile(r"\bstory behind\b", re.I)),
]
MAX_BOOST = 1.5
SHRINK = 3.0                       # a class needs ~3 Shorts before its own mean counts as much as the channel mean


def topic_class(text: str) -> str:
    t = text or ""
    for name, rx in CLASSES:
        if rx.search(t):
            return name
    if JARGON.search(t):
        return "jargon_science"
    return "general"


def format_of(title: str) -> str:
    for name, rx in FORMAT_FRAMES:
        if rx.search(title or ""):
            return name
    return "other"


def curiosity(text: str) -> float:
    """transparent 0-ish rubric (about -3 .. +3): would a stranger stop scrolling for this subject?"""
    t = text or ""
    s = 0.0
    s += 1.0 if FAMILIAR.search(t) else 0.0
    s += 0.5 if re.search(r"\d", t) else 0.0
    s += 0.5 if re.search(r"\b(?:what if|truth|myth|really|too big|nobody|secret|hidden|impossible|actually)\b", t, re.I) else 0.0
    s -= 1.5 if JARGON.search(t) else 0.0
    s -= 1.0 if ABSTRACT.search(t) else 0.0
    s -= 1.0 if topic_class(t) == "ai_tips" else 0.0
    words = re.findall(r"[A-Za-z]{3,}", t)
    s -= 0.5 if len(words) > 14 else 0.0                       # a long, hedged title is rarely a clear promise
    return round(s, 2)


def _score(views: int, age_h: float | None) -> float:
    """log views; a Short younger than 3 days is lifted by what it is likely to reach (it still has most of its views to come)"""
    v = max(int(views), 0)
    if age_h is not None and age_h < 72:
        v = int(v / max(0.35, min(1.0, 0.35 + 0.65 * age_h / 72)))
    return math.log10(v + 10)


def _stats(rows: list[tuple[str, float]]) -> dict[str, dict]:
    if not rows:
        return {}
    mean_all = statistics.mean(v for _, v in rows)
    by: dict[str, list[float]] = {}
    for k, v in rows:
        by.setdefault(k, []).append(v)
    out = {}
    for k, vs in by.items():
        n = len(vs)
        m = statistics.mean(vs)
        shrunk = (m * n + mean_all * SHRINK) / (n + SHRINK)
        boost = max(-MAX_BOOST, min(MAX_BOOST, (shrunk - mean_all) * 2.0))
        out[k] = {"n": n, "mean_log_views": round(m, 2), "boost": round(boost, 2)}
    return out


def class_stats(shorts: list[dict]) -> dict[str, dict]:
    return _stats([(topic_class(s.get("title", "")), _score(s.get("views", 0), s.get("age_h"))) for s in shorts if s.get("views") is not None])


def format_stats(shorts: list[dict]) -> dict[str, dict]:
    return _stats([(format_of(s.get("title", "")), _score(s.get("views", 0), s.get("age_h"))) for s in shorts if s.get("views") is not None])


def topic_boost(text: str, shorts: list[dict] | None = None) -> float:
    cls = topic_class(text)
    b = class_stats(shorts or []).get(cls, {}).get("boost", 0.0)
    return round(curiosity(text) + b, 2)


def hint(shorts: list[dict], max_chars: int = 700) -> str:
    cs = class_stats(shorts)
    if not cs:
        return ""
    ranked = sorted(cs.items(), key=lambda kv: -kv[1]["boost"])
    win = [f"{k} (n={v['n']})" for k, v in ranked if v["boost"] > 0.2][:3]
    lose = [f"{k} (n={v['n']})" for k, v in ranked[::-1] if v["boost"] < -0.2][:3]
    return ("TOPIC CLASSES on this channel's own results: do more of " + (", ".join(win) or "none proven yet") + "; less of " + (", ".join(lose) or "none proven yet") +
            ". A topic earns a click from a familiar noun, a number and a tension (what if / myth / too big); jargon, institutions and listicles of AI tips do not.")[:max_chars]
