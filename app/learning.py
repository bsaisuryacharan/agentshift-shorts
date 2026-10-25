"""(module: app.learning; the older app.playbook is the writer-rules module used by providers.py) The self-correcting part: remember how each Short was built, compare with how it performed, and feed what separates the winners from the losers back into
the topic picker and the script writer.

    record_features(spec, run_dir, grades)   at production time -> data/features.jsonl (what we chose)
    lessons(performance_jsonl)               joins that with data/performance.jsonl (what happened) -> short human-readable lessons

It never invents a pattern: a lesson needs at least MIN_SHORTS Shorts older than MIN_AGE_H hours and a clear gap between groups (>= GAP x), and says how many
Shorts it is based on. Until then it returns [] and the pipeline falls back to the fixed best-practice rules in the writer prompt.
"""
from __future__ import annotations

import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FEATURES = ROOT / "data" / "features.jsonl"
MIN_SHORTS, MIN_AGE_H, GAP = 4, 48, 1.5


def features(spec: dict, run_dir: Path | None = None, grades: dict | None = None) -> dict:
    from . import motionbank
    say = " ".join(b.get("say", "") for b in spec["beats"])
    hf = [e["name"] for b in spec["beats"] for e in b.get("hud", []) if e.get("t") == "hf"]
    credits = 0
    if run_dir:
        for sub in ("img", "vid"):
            f = Path(run_dir) / sub / "credits.json"
            if f.exists():
                try:
                    credits += len(json.loads(f.read_text()))
                except ValueError:
                    pass
    imgs = len({b.get("img") for b in spec["beats"] if b.get("img")})
    hook_words = len(spec["beats"][0].get("say", "").split())
    return {"spec_id": spec.get("id"), "mood": motionbank.mood_of(spec.get("title", "") + " " + say)[0], "theme": spec.get("theme", "cool"),
            "hook_words": "<=7" if hook_words <= 7 else "8-11" if hook_words <= 11 else "12+", "beats": len(spec["beats"]),
            "words": len(say.split()), "hf": len(hf), "real_pictures": round(credits / imgs, 2) if imgs else 0.0,
            "grades": {k: v.get("grade") for k, v in (grades or {}).items()}}


def record_features(spec: dict, run_dir: Path | None = None, grades: dict | None = None, path: Path = FEATURES) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(features(spec, run_dir, grades), ensure_ascii=False) + "\n")


def _read(path: Path) -> list[dict]:
    try:
        return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]
    except (OSError, ValueError):
        return []


def lessons(perf_path: Path, features_path: Path = FEATURES) -> list[str]:
    feats = {r["spec_id"]: r for r in _read(features_path)}
    latest: dict[str, dict] = {}
    for r in _read(perf_path):
        latest[r["spec_id"]] = r                         # file is chronological: the last row is the newest
    joined = []
    for sid, r in latest.items():
        if sid in feats:
            from datetime import UTC, datetime
            age = (datetime.now(UTC) - datetime.fromisoformat(r["published_at"].replace("Z", "+00:00"))).total_seconds() / 3600
            if age >= MIN_AGE_H:
                joined.append((feats[sid], r["views"]))
    if len(joined) < MIN_SHORTS:
        return []
    out = []
    for key, label in (("mood", "topic type"), ("theme", "colour theme"), ("hook_words", "opening line length"), ("hf", "gallery graphics per Short")):
        groups: dict[str, list[int]] = {}
        for f, v in joined:
            groups.setdefault(str(f[key]), []).append(v)
        if len(groups) < 2:
            continue
        means = {g: statistics.mean(v) for g, v in groups.items()}
        best, worst = max(means, key=means.get), min(means, key=means.get)
        if means[worst] > 0 and means[best] / means[worst] >= GAP or (means[worst] == 0 and means[best] > 0):
            out.append(f"{label}: '{best}' averaged {means[best]:.0f} views vs '{worst}' {means[worst]:.0f} (n={len(joined)} Shorts): do more of '{best}'")
    return out[:4]
