"""Autonomous production loop.

PLAN -> BUILD -> AUDIO -> CAPTIONS -> ASSEMBLE -> LINT -> RENDER -> GATE -> OBSERVE
     -> DIAGNOSE -> CORRECT (bounded) -> LEARN, or ESCALATE with evidence.

Design rules
------------
* Fail closed: no invented sources, no silent fallback to a blank video.
* The LLM only writes *content* (spec). HTML/motion comes from app/frames.py so a
  weak model cannot break the frame contract.
* Corrections are deterministic and bounded. When they run out, the loop writes
  ESCALATION.md instead of guessing.
* Every run writes loop_state.json + qa.json + observer_report.json + report.md,
  which is also the learning record.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import time
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from .frames import write_project
from .llm import LLM
from .models import Claim, Source, VideoSpec
from .providers import ProviderError
from .qa import hard_gate, probe
from .settings import Settings

REPO = Path(__file__).resolve().parent.parent
VIDEOS = REPO / "videos"
TEMPLATE = REPO / "templates" / "project"
WORK = REPO / "work"
LOGS = REPO / "logs"
DATA = REPO / "data"
HF_VERSION = os.getenv("HYPERFRAMES_VERSION", "0.8.186")
MIN_VISUAL_SCORE = 6


class StageError(RuntimeError):
    pass


# ---------------------------------------------------------------- utilities
def _now() -> str:
    return datetime.now(UTC).isoformat()


def _scripts_dir() -> Path:
    override = os.getenv("SHORTS_SKILL_SCRIPTS")
    if override:
        return Path(override).expanduser()
    vendored = REPO / "vendor" / "faceless-explainer" / "scripts"
    if vendored.is_dir():
        return vendored
    return Path("~/.config/opencode/skills/faceless-explainer/scripts").expanduser()


def _hf(*args: str) -> list[str]:
    return ["npx", "--yes", f"hyperframes@{HF_VERSION}", *args]


def _run(cmd: list[str], cwd: Path, timeout: int = 900) -> str:
    started = time.time()
    result = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, timeout=timeout, check=False)
    elapsed = round(time.time() - started, 1)
    LOGS.mkdir(parents=True, exist_ok=True)
    with (LOGS / "loop_commands.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"at": _now(), "cwd": str(cwd), "cmd": cmd[:4],
                                 "code": result.returncode, "seconds": elapsed}) + "\n")
    if result.returncode:
        raise StageError(f"{' '.join(cmd[:3])} failed ({result.returncode}): {result.stderr[-1200:]}")
    return result.stdout + result.stderr


def _load(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


# ------------------------------------------------------------------- state
class State:
    def __init__(self, video: Path):
        self.video = video
        self.path = video / "loop_state.json"
        self.data: dict[str, Any] = _load(self.path, {
            "video_id": video.name, "stage": "init", "attempt": 0, "history": [],
            "created_at": _now(),
        })

    def set(self, stage: str, **extra: Any) -> None:
        self.data.update({"stage": stage, "updated_at": _now(), **extra})
        self.data.setdefault("history", []).append({"at": _now(), "stage": stage, **extra})
        _dump(self.path, self.data)

    def save(self) -> None:
        self.data["updated_at"] = _now()
        _dump(self.path, self.data)


# --------------------------------------------------------------------- plan
BEAT_SCHEMA = {
    "type": "object",
    "required": ["id", "kind", "say", "headline"],
    "properties": {
        "id": {"type": "string"},
        "kind": {"enum": ["hook", "stat", "compare", "timeline", "diagram", "statement", "close"]},
        "say": {"type": "string"},
        "kicker": {"type": "string"},
        "headline": {"type": "string"},
        "sub": {"type": "string"},
        "value": {"type": "string"},
        "unit": {"type": "string"},
        "left": {"type": "string"},
        "right": {"type": "string"},
        "left_pct": {"type": "integer"},
        "right_pct": {"type": "integer"},
        "ticks": {"type": "array", "items": {"type": "string"}},
        "meta": {"type": "array", "items": {"type": "string"}},
        "accent": {"enum": ["hot", "electric", "acid"]},
        "claims": {"type": "array", "items": {"type": "string"}},
    },
}

SPEC_SCHEMA = {
    "type": "object",
    "required": ["title", "thesis", "promise", "beats"],
    "properties": {
        "title": {"type": "string"},
        "thesis": {"type": "string"},
        "promise": {"type": "string"},
        "description": {"type": "string"},
        "beats": {"type": "array", "items": BEAT_SCHEMA, "minItems": 4, "maxItems": 7},
    },
}


def plan_from_research(topic: str, research_path: Path, llm: LLM | None = None) -> VideoSpec:
    """The only place an LLM invents structure. Sources and claims must already exist."""
    research = _load(research_path, None)
    if not research or not research.get("sources") or not research.get("claims"):
        raise StageError(
            f"{research_path} must contain verified sources and claims. "
            "The loop refuses to plan from model memory alone."
        )
    sources = [Source.model_validate(item) for item in research["sources"]]
    claims = [Claim.model_validate(item) for item in research["claims"]]
    claim_text = "\n".join(f"- [{i}] {c.text}" for i, c in enumerate(claims))
    instruction = (
        f"Topic: {topic}\n\nVerified claims (the ONLY facts you may use):\n{claim_text}\n\n"
        "Write a 6-beat vertical short (38-50 spoken words total, 22-30 seconds at Kokoro pace). Beat 1 is the hook "
        "(kind=hook, <=12 words, a specific promise). "
        "Use stat for a number, compare for a before/after, timeline for a progression, diagram for a "
        "mechanism, statement for the turn, close for the loop-out. Narration is spoken prose; headline is "
        "2-5 uppercase words; sub is one short supporting line. Every factual beat lists claim indexes in "
        "`claims` as strings. Do not add facts that are not in the claims."
    )
    llm = llm or LLM(role="director")
    payload = llm.json(instruction, SPEC_SCHEMA, temperature=0.5)
    beats = payload.get("beats") or []
    if len(beats) < 4:
        raise StageError("Planner returned fewer than 4 beats")
    spec = VideoSpec(
        id=re.sub(r"[^a-z0-9]+", "-", payload["title"].lower()).strip("-")[:48],
        title=payload["title"],
        thesis=payload["thesis"],
        promise=payload["promise"],
        description=payload.get("description", payload["thesis"]),
        beats=beats,
        sources=sources,
        claims=claims,
    )
    return spec


# ------------------------------------------------------------------ metrics
def _ffmpeg_metrics(video: Path) -> dict[str, Any]:
    freeze = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(video), "-vf", "freezedetect=n=0.003:d=0.5",
         "-f", "null", "-"], capture_output=True, text=True, check=False
    ).stderr
    freeze_starts = len(re.findall(r"freeze_start", freeze))
    freeze_seconds = sum(float(x) for x in re.findall(r"freeze_duration: ([0-9.]+)", freeze))

    scenes = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(video), "-vf", "select='gt(scene,0.15)',showinfo",
         "-f", "null", "-"], capture_output=True, text=True, check=False
    ).stderr
    scene_changes = len(re.findall(r"pts_time:", scenes))

    loud = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(video), "-af", "ebur128=peak=true", "-f", "null", "-"],
        capture_output=True, text=True, check=False
    ).stderr
    match = re.findall(r"I:\s+(-?[0-9.]+) LUFS", loud)
    lufs = float(match[-1]) if match else None

    silence = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(video), "-af", "silencedetect=n=-45dB:d=1.0", "-f", "null", "-"],
        capture_output=True, text=True, check=False
    ).stderr
    silence_events = [float(x) for x in re.findall(r"silence_duration: ([0-9.]+)", silence)]
    return {"freeze_events": freeze_starts, "freeze_seconds": round(freeze_seconds, 2),
            "scene_changes": scene_changes, "lufs": lufs,
            "silence_max": round(max(silence_events, default=0), 2),
            "silence_seconds": round(sum(silence_events), 2)}


def _contact_sheet(video: Path, destination: Path, duration: float) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    times = [duration * f for f in (0.04, 0.2, 0.36, 0.52, 0.68, 0.84)]
    tmp = destination.parent
    frames = []
    for index, at in enumerate(times):
        frame = tmp / f"shot_{index}.jpg"
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", f"{at:.2f}", "-i", str(video),
                        "-frames:v", "1", "-vf", "scale=360:640", "-y", str(frame)], check=False)
        if frame.exists():
            frames.append(frame)
    if not frames:
        raise StageError("Could not extract observer frames")
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", f"{tmp}/shot_%d.jpg",
                    "-vf", "tile=3x2", "-frames:v", "1", "-y", str(destination)], check=False)
    return destination


VISION_SCHEMA = {
    "type": "object",
    "required": ["visual_richness", "hierarchy", "legibility", "hook", "verdict"],
    "properties": {
        "visual_richness": {"type": "integer"},
        "hierarchy": {"type": "integer"},
        "legibility": {"type": "integer"},
        "hook": {"type": "integer"},
        "verdict": {"enum": ["approve", "revise"]},
        "notes": {"type": "array", "items": {"type": "string"}},
    },
}


def _vision_review(sheet: Path) -> dict[str, Any]:
    digest = sha256(sheet.read_bytes()).hexdigest()[:16]
    cache = DATA / "vision_cache" / f"{digest}.json"
    if cache.exists():
        cached = _load(cache, {})
        if "skipped" not in cached:
            return cached
    llm = LLM(role="visual-critic")
    if not llm.available():
        return {"skipped": "no LLM credentials"}
    instruction = (
        "These are six frames from one 1080x1920 vertical short, in order. Score 1-10: "
        "visual_richness (how much is shown beyond typography - objects, data, scenes), "
        "hierarchy (one clear focal point), legibility (text readable at phone size), "
        "hook (does frame 1 stop a scroll). Verdict 'revise' if visual_richness < 6. "
        "Notes must name the specific frame and the concrete fix."
    )
    try:
        review = llm.json(instruction, VISION_SCHEMA, images=[sheet], temperature=0.2)
        score = review.get("visual_richness")
        if isinstance(score, int) and score < MIN_VISUAL_SCORE:
            # A single VL sample swings by ~2 points. Only re-ask to confirm a failure, and
            # take the lower score: retries must never be a path to passing.
            second = llm.json(instruction, VISION_SCHEMA, images=[sheet], temperature=0.2)
            if isinstance(second.get("visual_richness"), int) and (
                second["visual_richness"] < score
            ):
                review["confirmed_once"] = True
                review["visual_richness"] = second["visual_richness"]
                review["verdict"] = second.get("verdict", review.get("verdict"))
                review["notes"] = list(review.get("notes", [])) + [
                    f"[sample 2] {n}" for n in second.get("notes", [])
                ]
    except ProviderError as error:
        # Never cache a failure: a quota that resets in an hour must not poison the visual gate.
        return {"skipped": str(error)[:300]}
    _dump(cache, review)
    return review


def observe(video: Path, script: Any, prior: list[str]) -> dict[str, Any]:
    metadata = probe(video)
    duration = float(metadata["format"]["duration"])
    gate = hard_gate(video, script, prior)
    sheet = _contact_sheet(video, WORK / video.stem / "contact.jpg", duration)
    metrics = _ffmpeg_metrics(video)
    visual = _vision_review(sheet)
    report = {
        "at": _now(), "video": str(video), "duration": duration,
        "size_mb": round(video.stat().st_size / 1024 / 1024, 2),
        "gate": {"passed": gate.passed, "checks": gate.checks},
        "metrics": metrics, "visual_review": visual, "contact_sheet": str(sheet),
    }
    _dump(video.parent / "observer_report.json", report)
    return report


def diagnose(report: dict[str, Any]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for name, result in report["gate"]["checks"].items():
        if result != "pass":
            findings.append({"code": f"GATE_{name.upper()}", "detail": result})
    metrics = report["metrics"]
    if metrics["freeze_seconds"] >= 0.5:
        findings.append({"code": "FREEZE", "detail": f"{metrics['freeze_seconds']}s frozen"})
    if metrics["lufs"] is not None and not (-16.5 <= metrics["lufs"] <= -11.5):
        findings.append({"code": "LOUDNESS", "detail": f"{metrics['lufs']} LUFS"})
    if metrics["silence_max"] >= 1.2:
        findings.append({"code": "SILENCE", "detail": f"{metrics['silence_max']}s continuous silence"})
    visual = report.get("visual_review") or {}
    if isinstance(visual.get("visual_richness"), int) and visual["visual_richness"] < MIN_VISUAL_SCORE:
        findings.append({"code": "MORE_VISUAL", "detail": f"richness {visual['visual_richness']}/10"})
    # A model almost always says "revise"; only a sub-threshold score may block the gate.
    # Notes are still recorded in the report as guidance for the next design pass.
    if visual.get("verdict") == "revise" and (
        not isinstance(visual.get("visual_richness"), int)
        or visual["visual_richness"] < MIN_VISUAL_SCORE
    ):
        findings.append({"code": "VISION_REVISE", "detail": "; ".join(visual.get("notes", []))[:400]})
    return findings


# ------------------------------------------------------------------ correct
def _add_scene_drift(video: Path, duration_hint: float = 0.0) -> int:
    """Deterministic anti-freeze + depth fix: slow scene drift, no new dependencies."""
    changed = 0
    for frame in sorted((video / "compositions" / "frames").glob("*.html")):
        text = frame.read_text(encoding="utf-8")
        if "SCENE-DRIFT" in text:
            continue
        if "tl.seek(0);" not in text:
            continue
        text = text.replace(
            "tl.seek(0);",
            'tl.to("#scene", { y: -18, scale: 1.02, duration: D, ease: "none" }, 0); // SCENE-DRIFT\n      tl.seek(0);',
        )
        frame.write_text(text, encoding="utf-8")
        changed += 1
    return changed


def _loudnorm(video: Path) -> Path:
    fixed = video.with_name(video.stem + "-loud.mp4")
    _run(["ffmpeg", "-hide_banner", "-y", "-i", str(video), "-c:v", "copy",
          "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-c:a", "aac", "-b:a", "192k",
          "-movflags", "+faststart", str(fixed)], cwd=video.parent, timeout=600)
    fixed.replace(video)
    return video


# -------------------------------------------------------------------- learn
def learn(state: State, spec: VideoSpec, report: dict[str, Any], findings: list[dict[str, str]],
          attempt: int) -> None:
    record = {
        "at": _now(), "video_id": spec.id, "attempt": attempt,
        "duration": report["duration"], "size_mb": report["size_mb"],
        "metrics": report["metrics"], "visual_review": report.get("visual_review", {}),
        "findings": findings, "gate_passed": report["gate"]["passed"],
        "beats": [{"kind": b.kind, "accent": b.accent, "chars": len(b.headline)} for b in spec.beats],
    }
    path = DATA / "creative_learning.json"
    learning = _load(path, {"schema_version": 1, "weights": {}, "runs": []})
    learning.setdefault("loop_runs", []).append(record)
    learning["loop_runs"] = learning["loop_runs"][-200:]
    _dump(path, learning)

    lessons = REPO / "docs" / "LESSONS.md"
    lessons.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"## {spec.id} · attempt {attempt} · {'PASS' if report['gate']['passed'] else 'FAIL'}",
        f"- {record['duration']:.1f}s, {record['size_mb']}MB, freezes={record['metrics']['freeze_seconds']}s, "
        f"scene_changes={record['metrics']['scene_changes']}, LUFS={record['metrics']['lufs']}",
        f"- vision: {json.dumps(record['visual_review'])[:400]}",
        f"- findings: {', '.join(f['code'] for f in findings) or 'none'}",
        "",
    ]
    with lessons.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def escalate(video: Path, report: dict[str, Any], findings: list[dict[str, str]],
             stage: str, error: str | None = None) -> Path:
    path = video / "ESCALATION.md"
    body = [
        f"# Escalation — {video.name}",
        "",
        f"Stage: `{stage}`",
        f"When: {_now()}",
        "",
        "Deterministic corrections were exhausted. A human (or a coding agent) must decide.",
        "",
        "## Findings",
        *[f"- **{f['code']}** — {f['detail']}" for f in findings],
        "",
        "## Metrics",
        "```json",
        json.dumps({"metrics": report.get("metrics", {}), "gate": report.get("gate", {}),
                    "visual": report.get("visual_review", {})}, indent=2),
        "```",
        "",
        "## Evidence",
        f"- contact sheet: `{report.get('contact_sheet', 'n/a')}`",
        f"- observer report: `{video / 'observer_report.json'}`",
        f"- rendered file: `{report.get('video', 'n/a')}`",
        "",
        "## Questions to resolve",
        "1. Which specific frame fails, and what should it show instead?",
        "2. Is the failure editorial (beat choice), motion (too static), or technical (lint/render)?",
        "3. Should the next attempt change the spec, the frame template, or both?",
    ]
    if error:
        body += ["", "## Error", "```", error[-3000:], "```"]
    path.write_text("\n".join(body) + "\n", encoding="utf-8")
    return path


# --------------------------------------------------------------------- run
def _prior_scripts(exclude: Path) -> list[str]:
    texts = []
    for script in VIDEOS.glob("*/SCRIPT.md"):
        if script.parent == exclude:
            continue
        texts.append(script.read_text(encoding="utf-8"))
    return texts


def build(video: Path, spec: VideoSpec, state: State, durations: dict[str, float] | None = None) -> None:
    scripts = _scripts_dir()
    state.set("build")
    write_project(video, spec, durations, template_dir=TEMPLATE)

    state.set("audio")
    if not (video / "audio_meta.json").exists():
        _run(["node", str(scripts / "audio.mjs"), "--script", "SCRIPT.md", "--storyboard", "STORYBOARD.md",
              "--hyperframes", ".", "--out", "audio_meta.json"], cwd=video, timeout=1200)
    _run(["node", str(scripts / "audio.mjs"), "sync-durations", "--audio-meta", "audio_meta.json",
          "--storyboard", "STORYBOARD.md"], cwd=video, timeout=180)

    meta = _load(video / "audio_meta.json", {})
    voices = meta.get("voices", [])
    real = {beat.id: float(voices[i]["duration_s"]) for i, beat in enumerate(spec.beats)
            if i < len(voices) and voices[i].get("duration_s")}
    if len(real) != len(spec.beats):
        raise StageError("audio_meta is missing one voice per beat")
    padded = {beat.id: round(max(3.2, real[beat.id] + 0.35), 3) for beat in spec.beats}
    total = sum(padded.values())
    if total < 20.3:
        raise StageError(
            f"script is {total:.1f}s of speech; the gate needs 20-60s. "
            "Add beats or words to the spec and retry (do not pad with silence)."
        )
    write_project(video, spec, padded, template_dir=TEMPLATE)

    state.set("captions")
    _run(["node", str(scripts / "captions.mjs"), "build", "--storyboard", "STORYBOARD.md",
          "--audio-meta", "audio_meta.json", "--hyperframes", ".", "--out", "caption_groups.json"],
         cwd=video, timeout=300)

    state.set("assemble")
    _run(["node", str(scripts / "assemble-index.mjs"), "--storyboard", "STORYBOARD.md",
          "--hyperframes", ".", "--audio-meta", "audio_meta.json"], cwd=video, timeout=300)
    if "transition" in " ".join(b.say for b in spec.beats).lower():
        pass  # transitions are injected only when the storyboard requests them
    _run(["node", str(scripts / "transitions.mjs"), "verify", "--storyboard", "STORYBOARD.md",
          "--index", "index.html"], cwd=video, timeout=180)

    state.set("lint")
    _run(_hf("lint"), cwd=video, timeout=600)
    _run(_hf("check"), cwd=video, timeout=600)


def render(video: Path, state: State) -> Path:
    state.set("render")
    started = time.time()
    _run(_hf("render", "--crf", "21"), cwd=video, timeout=2400)
    candidates = [p for p in (video / "renders").glob("*.mp4") if p.stat().st_mtime >= started - 5]
    if not candidates:
        candidates = sorted((video / "renders").glob("*.mp4"), key=lambda p: p.stat().st_mtime)
    if not candidates:
        raise StageError("render produced no mp4")
    return max(candidates, key=lambda p: p.stat().st_mtime)


def run(video: Path, spec: VideoSpec, max_attempts: int = 3) -> int:
    state = State(video)
    video.mkdir(parents=True, exist_ok=True)
    script = spec.to_script()
    prior = _prior_scripts(video)

    try:
        build(video, spec, state)
    except StageError as error:
        escalate(video, {}, [], "build", str(error))
        state.set("escalated", error=str(error)[:2000])
        print(f"BUILD FAILED: {error}")
        return 2

    for attempt in range(1, max_attempts + 1):
        state.set("attempt", attempt=attempt)
        out = render(video, state)
        _loudnorm(out)
        report = observe(out, script, prior)
        findings = diagnose(report)
        learn(state, spec, report, findings, attempt)

        blocking = [f for f in findings if f["code"] != "VISION_REVISE"]
        passed = report["gate"]["passed"] and not blocking
        if passed:
            state.set("passed", video=str(out), findings=findings)
            (video / "report.md").write_text(
                f"# {spec.title}\n\n{spec.thesis}\n\n- video: `{out}`\n"
                f"- duration: {report['duration']:.1f}s\n- size: {report['size_mb']}MB\n"
                f"- metrics: `{json.dumps(report['metrics'])}`\n"
                f"- vision: `{json.dumps(report.get('visual_review', {}))}`\n",
                encoding="utf-8",
            )
            print(json.dumps({"status": "passed", "video": str(out), "attempt": attempt}, indent=2))
            return 0

        corrected = []
        codes = {f["code"] for f in findings}
        if codes & {"FREEZE", "GATE_NO_FROZEN_STRETCH", "MORE_VISUAL", "VISION_REVISE"}:
            changed = _add_scene_drift(video)
            if changed:
                corrected.append(f"scene-drift x{changed}")
        state.set("correct", attempt=attempt, actions=corrected, findings=findings)
        if not corrected:
            break

    escalate(video, report, findings, "gate")
    state.set("escalated", findings=findings)
    print(json.dumps({"status": "escalated", "findings": findings}, indent=2))
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.loop")
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="build, render, gate and learn")
    run_p.add_argument("--video-id", required=True)
    run_p.add_argument("--spec", type=Path)
    run_p.add_argument("--max-attempts", type=int, default=3)

    plan_p = sub.add_parser("plan", help="write spec.json from verified research")
    plan_p.add_argument("--video-id", required=True)
    plan_p.add_argument("--topic", required=True)
    plan_p.add_argument("--research", type=Path, required=True)

    prod_p = sub.add_parser("produce", help="one-command cinematic Short (app.produce): voice, HUD, render, QA gate")
    prod_p.add_argument("--spec", type=Path, required=True)
    prod_p.add_argument("--out", type=Path, default=Path("runs"))

    obs_p = sub.add_parser("observe", help="re-score an existing render")
    obs_p.add_argument("--video-id", required=True)

    args = parser.parse_args(argv)
    if args.command == "produce":
        from .produce import run as produce_run

        m = produce_run(args.spec, args.out)
        bad = [k for k, v in m["checks"].items() if v != "pass" and k != "vision"]
        print(json.dumps({"failed": bad, "vision": m["checks"].get("vision"), "run": str(args.out)}, indent=2))
        return 1 if bad else 0  # vision is added afterwards via `python -m app.produce qa`
    video = VIDEOS / args.video_id

    if args.command == "plan":
        spec = plan_from_research(args.topic, args.research)
        video.mkdir(parents=True, exist_ok=True)
        (video / "spec.json").write_text(spec.model_dump_json(indent=2), encoding="utf-8")
        print(json.dumps({"spec": str(video / "spec.json"), "id": spec.id, "beats": len(spec.beats)}, indent=2))
        return 0

    spec_path = getattr(args, "spec", None) or (video / "spec.json")
    if not spec_path.exists():
        raise SystemExit(f"missing spec: {spec_path} (run `plan --research` first)")

    if args.command == "observe":
        spec = VideoSpec.model_validate_json(spec_path.read_text(encoding="utf-8"))
        renders = sorted((video / "renders").glob("*.mp4"), key=lambda p: p.stat().st_mtime)
        if not renders:
            raise SystemExit("no render to observe")
        report = observe(renders[-1], spec.to_script(), _prior_scripts(video))
        print(json.dumps({"gate": report["gate"], "metrics": report["metrics"],
                          "visual": report["visual_review"]}, indent=2))
        return 0 if report["gate"]["passed"] else 1

    spec = VideoSpec.model_validate_json(spec_path.read_text(encoding="utf-8"))
    return run(video, spec, args.max_attempts)


if __name__ == "__main__":
    raise SystemExit(main())
