"""Topic -> visual style mapper: which look and colour theme suit THIS Short, learned from what the channel has actually published.

    choose(spec, fmt, shorts=None, rng=None) -> {"look", "theme", "class", "why", "lemo_style"}

The old rule was format -> look (looks.DEFAULT_BY_FORMAT) with a rotation away from the last three. That keeps formats from repeating a look but knows nothing about the TOPIC
(a coral-bleaching Short and a Y2K Short got the same treatment if they shared a format) and nothing about results. This mapper:

 1. classes the topic (app.topicscore: awe_scale, inside_machine, myth_fact, what_if, earth_hazard, history_event, jargon_science, ai_tips, tech_explainer, general);
 2. takes the looks that fit that class, ordered by fit, restricted to the ones the format allows when they overlap;
 3. never repeats one of the last two looks and spreads colour themes (59 of the last 66 Shorts were "cool");
 4. exploits what worked: once a look has >= MIN_N published Shorts with results, the best-scoring fresh look wins; EXPLORE of the time it tries a fresh one instead;
 5. names the closest Lemo-Opuscar film style for the class ("lemo_style") so a future render engine (see docs/FACELESS_TOOLKIT.md) can take over a look without changing the mapper.

It is pure code: no LLM, no network, deterministic for a given rng.
"""
from __future__ import annotations

import json
import random
import statistics
from pathlib import Path

from . import looks, topicscore, variety

ROOT = Path(__file__).resolve().parents[1]
EXPLORE = 0.25
MIN_N = 2

# class -> (looks in order of fit, themes that suit it, closest Lemo-Opuscar film styles)
PLAN: dict[str, dict] = {
    "awe_scale": {"looks": ["midnight-grid", "poster-pop", "editorial-paper", "ink-line"], "themes": ["cool", "mono"], "lemo": ["Data Storytelling", "Satellite Briefing", "Time-lapse Symphony"]},
    "inside_machine": {"looks": ["blueprint", "explainer-diagram", "graphite-ui"], "themes": ["cool", "mono"], "lemo": ["Exploded Teardown", "Blueprint", "Engineering Briefing Board"]},
    "myth_fact": {"looks": ["swiss-kinetic", "swiss-grid", "poster-pop", "explainer-diagram"], "themes": ["mono", "warm", "cool"], "lemo": ["Caption News", "Swiss Motion Graphics", "Visual Investigation"]},
    "what_if": {"looks": ["midnight-grid", "graphite-ui", "paper-cut", "poster-pop"], "themes": ["cool", "warm", "earth"], "lemo": ["Sci-fi Hologram HUD", "Isometric Infographic", "Sports Telestrator"]},
    "earth_hazard": {"looks": ["paper-cut", "risograph", "editorial-paper", "poster-pop"], "themes": ["earth", "warm"], "lemo": ["Satellite Briefing", "Risograph Print", "Chinese Ink Wash"]},
    "history_event": {"looks": ["time-travel", "editorial-paper", "risograph", "paper-cut"], "themes": ["warm", "mono"], "lemo": ["1920s Newsreel", "Archive Light Table", "Transit Map"]},
    "jargon_science": {"looks": ["explainer-diagram", "ink-line", "blueprint", "editorial-paper"], "themes": ["cool", "mono"], "lemo": ["Whiteboard Explainer", "Chalkboard", "Microscope Story"]},
    "ai_tips": {"looks": ["graphite-ui", "swiss-kinetic", "swiss-grid"], "themes": ["cool", "mono"], "lemo": ["Living Screencast", "Dark Tech Keynote", "Swiss Motion Graphics"]},
    "tech_explainer": {"looks": ["graphite-ui", "midnight-grid", "blueprint", "explainer-diagram"], "themes": ["cool", "mono"], "lemo": ["Dark Tech Keynote", "Circuit Board", "Pictogram Motion"]},
    "general": {"looks": [], "themes": ["cool", "warm", "earth", "mono"], "lemo": ["Data Storytelling", "Swiss Motion Graphics"]},
}
ALL_THEMES = ["cool", "warm", "mono", "earth"]


def _features(path: Path = ROOT / "data" / "features.jsonl") -> dict[str, dict]:
    try:
        return {r["spec_id"]: r for r in (json.loads(x) for x in path.read_text().splitlines() if x.strip())}
    except (OSError, ValueError, KeyError):
        return {}


def look_results(shorts: list[dict], feats: dict[str, dict] | None = None) -> dict[str, dict]:
    """{look: {"n", "mean_log_views"}} for Shorts whose spec recorded a look (features.jsonl 'look', written since 2026-11-10)"""
    feats = feats if feats is not None else _features()
    by: dict[str, list[float]] = {}
    for s in shorts:
        look = (feats.get(s.get("spec_id")) or {}).get("look")
        if look and s.get("views") is not None:
            by.setdefault(look, []).append(topicscore._score(s["views"], s.get("age_h")))
    return {k: {"n": len(v), "mean_log_views": round(statistics.mean(v), 2)} for k, v in by.items()}


def _fit(cls: str, fmt: str | None) -> list[str]:
    plan = [x for x in PLAN.get(cls, PLAN["general"])["looks"] if x in looks.LOOKS]
    fmt_ok = looks.CANDIDATES.get(fmt or "", [])
    both = [x for x in plan if x in fmt_ok]
    if cls == "general" or not plan:
        return fmt_ok or [looks.pick(None, fmt)]
    return both + [x for x in plan if x not in both]          # topic fit first, format fit breaks ties inside it


def choose(spec: dict, fmt: str | None = None, shorts: list[dict] | None = None, rng: random.Random | None = None,
           recent: list[dict] | None = None, feats: dict[str, dict] | None = None) -> dict:
    rng = rng or random.Random()
    text = " ".join([spec.get("title", "")] + [b.get("say", "") for b in spec.get("beats", [])[:3]])
    cls = topicscore.topic_class(text)
    plan = PLAN.get(cls, PLAN["general"])
    cands = _fit(cls, fmt)
    recent = variety.entries() if recent is None else recent
    last_looks = [e.get("look") for e in recent[-2:]]
    fresh = [c for c in cands if c not in last_looks] or cands
    results = look_results(shorts or [], feats)
    proven = [c for c in fresh if results.get(c, {}).get("n", 0) >= MIN_N]
    why = "topic fit"
    if proven and rng.random() > EXPLORE:
        look = max(proven, key=lambda c: results[c]["mean_log_views"])
        why = f"best result so far for this kind of Short ({results[look]['n']} Shorts)"
    elif len(fresh) > 1 and rng.random() < EXPLORE:
        look = rng.choice(fresh[1:])
        why = "exploring a fresh fit"
    else:
        look = fresh[0]
    used_themes = [e.get("theme") for e in recent[-3:]]
    themes = [t for t in plan["themes"] if used_themes.count(t) < 2] or [t for t in ALL_THEMES if used_themes.count(t) < 2] or plan["themes"]
    theme = themes[0] if themes[0] != (used_themes[-1] if used_themes else None) or len(themes) == 1 else themes[1]
    return {"look": look, "theme": theme, "class": cls, "why": why, "lemo_style": plan["lemo"]}
