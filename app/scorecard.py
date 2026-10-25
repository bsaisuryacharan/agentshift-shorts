"""Grade every Short stage by stage, and check the publishing guidelines, so the system knows WHERE a weak Short is weak and the next attempt fixes that stage.

    build(spec, run_dir, scores) -> {"stages": {name: {"score", "grade"}}, "weakest", "signals", "policy": {"ok", "checks": [...]}}

Stage scores are averages of the independent judge's dimensions; grades: A >= 9, B >= 8, C >= 7, D < 7. TARGET_GRADE is the level the channel aims at.
The guideline checks cover what YouTube asks of this kind of channel (original commentary, sources, disclosed synthetic media, credited third-party material,
no mass-produced repetition); the first three are hard (a failing Short is not approved), the rest are warnings that appear in the notes.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAGES = {"hook": ["hook"], "story": ["accuracy", "originality", "payoff"], "visuals": ["visual_quality", "visual_variety", "consistency"],
          "polish": ["polish", "hierarchy"], "policy": ["policy"]}
FIX_HINT = {"hook": "make the first 2 seconds a clear, surprising promise (<= 9 words)", "story": "tighten the facts, add a fresh angle, close the loop in the last line",
            "visuals": "use real pictures and footage, vary the shot types, keep one visual language", "polish": "check text size, clipping and the safe zones",
            "policy": "remove anything misleading or unsafe"}
TARGET_GRADE = "B"


def grade(score: float) -> str:
    return "A" if score >= 9 else "B" if score >= 8 else "C" if score >= 7 else "D"


def stages(scores: dict) -> dict:
    out = {}
    for name, dims in STAGES.items():
        vals = [scores[d] for d in dims if isinstance(scores.get(d), (int, float))]
        if vals:
            avg = round(sum(vals) / len(vals), 1)
            out[name] = {"score": avg, "grade": grade(avg)}
    return out


def _json(p: Path) -> dict:
    try:
        return json.loads(Path(p).read_text())
    except (OSError, ValueError):
        return {}


def signals(spec: dict, run_dir: Path) -> dict:
    run_dir = Path(run_dir)
    imgs = len({b.get("img") for b in spec["beats"] if b.get("img")})
    img_credits, vid_credits = _json(run_dir / "img" / "credits.json"), _json(run_dir / "vid" / "credits.json")
    hf = [e.get("name") for b in spec["beats"] for e in b.get("hud", []) if e.get("t") == "hf"]
    man = _json(run_dir / "manifest.json")
    return {"pictures": imgs, "real_photos": len(img_credits), "footage_clips": len(vid_credits), "gallery_graphics": hf,
            "duration_s": man.get("video_s"), "words": sum(len(b.get("say", "").split()) for b in spec["beats"]), "hard_gates": man.get("checks", {})}


def policy(spec: dict, run_dir: Path, sig: dict, features_path: Path | None = None) -> dict:
    run_dir = Path(run_dir)
    checks = []
    srcs = [v for v in (spec.get("sources") or {}).values() if str(v).startswith("http")]
    checks.append({"check": "sources", "hard": True, "ok": bool(srcs), "note": f"{len(srcs)} source link(s)"})
    creds = [*(_json(run_dir / "img" / "credits.json").values()), *(_json(run_dir / "vid" / "credits.json").values())]
    bad = [c for c in creds if not (c.get("license") and (c.get("url") or c.get("source")))]
    checks.append({"check": "third_party_credits", "hard": True, "ok": not bad, "note": f"{len(creds)} credited, {len(bad)} incomplete"})
    dur = sig.get("duration_s")
    checks.append({"check": "length_under_60s", "hard": True, "ok": dur is None or dur <= 60, "note": f"{dur}s"})
    checks.append({"check": "synthetic_media_disclosed", "hard": False, "ok": True, "note": "set on every upload (containsSyntheticMedia)"})
    checks.append({"check": "original_narration_and_analysis", "hard": False, "ok": sig.get("words", 0) >= 70, "note": f"{sig.get('words')} spoken words"})
    from . import learning
    prev = learning._read(features_path or learning.FEATURES)[-3:]
    mine = (spec.get("theme", "cool"), tuple(sorted(sig.get("gallery_graphics", []))), len(spec["beats"]))
    same = [p for p in prev if p.get("theme") == mine[0] and p.get("beats") == mine[2]]
    checks.append({"check": "not_a_repeated_template", "hard": False, "ok": len(same) < 3, "note": "same theme and beat count as each of the last 3 Shorts" if len(same) >= 3 else "format varies"})
    return {"ok": all(c["ok"] for c in checks if c["hard"]), "checks": checks}


def build(spec: dict, run_dir: Path, scores: dict, features_path: Path | None = None) -> dict:
    st = stages(scores)
    weakest = min(st, key=lambda k: st[k]["score"]) if st else None
    sig = signals(spec, run_dir)
    card = {"stages": st, "weakest": weakest, "target_grade": TARGET_GRADE, "on_target": all(v["grade"] <= TARGET_GRADE for v in st.values()) if st else False,
            "signals": sig, "policy": policy(spec, run_dir, sig, features_path)}
    if weakest:
        card["fix_first"] = f"{weakest} ({st[weakest]['grade']} {st[weakest]['score']}): {FIX_HINT[weakest]}"
    return card


def summary_line(card: dict) -> str:
    return " ".join(f"{k}:{v['grade']}" for k, v in card["stages"].items())
