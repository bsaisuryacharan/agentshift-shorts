"""Production QA v2 — measures what viewers actually see.

The v1 gate (app/qa.py) only proves a file is valid (duration, resolution, loudness-ish, a 0.5 s freeze test). That let a
48-second Short through that was ONE static illustration with a 3-line caption box and a missing-glyph (tofu) rupee sign,
and the text-only LLM review scored it 8/10. v2 adds measured checks for the failure modes that actually lose viewers:

  cadence        a visible change (cut, camera move, graphic) at least every MAX_STATIC_S seconds
  distinct_shots enough different pictures for the runtime (1 per ~5 s)
  motion         the picture is never effectively still
  black/freeze/silence/loudness  technical hygiene
  glyphs         every on-screen character exists in the caption font (no tofu boxes)
  safe_zone      HUD/graphics stay out of YouTube's UI zones (overlay PNGs)
  vision         a *frame-based* review is mandatory; a text-only review can never approve

    python -m app.qa_v2 final.mp4 [--overlay work/ovl] [--text onscreen.txt] [--font path.ttf] [--sheet out.jpg]
exit 0 = pass, 2 = fail.  Thresholds are constants below; tune them only from measured evidence in docs/LESSONS.md.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

MIN_S, MAX_S = 20.0, 60.0
MAX_STATIC_S = 4.0        # no stretch longer than this without a visible change
SHOT_EVERY_S = 6.0        # at least duration/6 distinct pictures
MIN_MOTION = 1.2          # median frame-to-frame mean abs diff (0-255) at 10 fps
LUFS_RANGE = (-16.5, -11.5)
MAX_SILENCE_S = 1.2
UI_BOTTOM_PX, UI_RIGHT_PX = 500, 140     # YouTube Shorts UI: channel/title (bottom), buttons (right)
TAIL_OK_S = 3.5                         # silence inside the last N seconds (end card) is allowed
CAPTION_BAND = (1180, 1420)              # where pinned captions may sit (abs y)


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def probe(video: Path) -> dict:
    return json.loads(_run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(video)]).stdout)


def sample_gray(video: Path, fps: int = 10, size=(90, 160)) -> np.ndarray:
    """decode to small grayscale frames; cheap and deterministic."""
    w, h = size
    p = subprocess.run(["ffmpeg", "-v", "error", "-i", str(video), "-vf", f"fps={fps},scale={w}:{h},format=gray",
                        "-f", "rawvideo", "-"], capture_output=True, check=True)
    a = np.frombuffer(p.stdout, np.uint8)
    return a[: len(a) // (w * h) * w * h].reshape(-1, h, w).astype(np.float32)


def visual_metrics(video: Path) -> dict:
    g = sample_gray(video)
    fps = 10
    step = np.abs(np.diff(g, axis=0)).mean(axis=(1, 2))                 # frame-to-frame motion
    lag = 2 * fps                                                       # compare with the picture 2 s earlier
    nov = np.abs(g[lag:] - g[:-lag]).mean(axis=(1, 2)) if len(g) > lag else np.array([0.0])
    # distinct shots: histogram correlation against the shot's first frame drops
    shots, ref = 1, None
    for f in g:
        h = cv2.calcHist([f.astype(np.uint8)], [0], None, [32], [0, 256]).flatten()
        h /= h.sum() + 1e-9
        if ref is None:
            ref = h
        elif cv2.compareHist(ref.astype(np.float32), h.astype(np.float32), cv2.HISTCMP_CORREL) < 0.80:
            shots, ref = shots + 1, h
    # longest stretch where the picture stayed "the same" as 2 s earlier AND barely moved
    quiet = (nov[: len(step) - lag + 1 if len(step) >= lag else 0] if len(step) else nov) < 3.0
    longest, run = 0, 0
    for q in (nov < 3.0):
        run = run + 1 if q else 0
        longest = max(longest, run)
    return {"median_motion": float(np.median(step)), "distinct_shots": shots,
            "longest_static_s": round((longest + lag) / fps if longest else 0.0, 1),
            "frames": len(g), "p95_motion": float(np.percentile(step, 95))}


def audio_metrics(video: Path) -> dict:
    """one audio-only pass: loudness (EBU R128) + silence."""
    e = _run(["ffmpeg", "-nostats", "-vn", "-i", str(video), "-af", f"silencedetect=n=-45dB:d={MAX_SILENCE_S},ebur128", "-f", "null", "-"]).stderr
    m = re.findall(r"I:\s+(-?\d+\.?\d*) LUFS", e)
    dur = float(probe(video)["format"]["duration"])
    gaps = [(float(a), float(b)) for a, b in re.findall(r"silence_start: ([\d.]+)[\s\S]*?silence_duration: ([\d.]+)", e)]
    gaps = [b for a, b in gaps if a + b < dur - 0.2 and a < dur - TAIL_OK_S]   # a quiet end-card tail is fine
    return {"lufs": float(m[-1]) if m else None, "silences": [str(g) for g in gaps]}


def hygiene(video: Path) -> dict:
    """freeze + black detection on a 10 fps 270x480 proxy (same verdicts, ~10x cheaper than full-res)."""
    e = _run(["ffmpeg", "-nostats", "-i", str(video), "-an", "-vf", "fps=10,scale=270:480,freezedetect=n=0.003:d=0.5,blackdetect=d=0.6:pix_th=0.06",
              "-f", "null", "-"]).stderr
    return {"freeze": "freeze_start" in e, "black": re.findall(r"black_start:([\d.]+).*?black_duration:([\d.]+)", e)}


def glyph_audit(text: str, font_path: str | Path) -> list[str]:
    """characters that the caption font cannot draw (they render as □ tofu)."""
    from fontTools.ttLib import TTFont
    font = TTFont(str(font_path), fontNumber=0)
    cmap = set()
    for t in font["cmap"].tables:
        cmap |= set(t.cmap.keys())
    return sorted({c for c in text if not c.isspace() and ord(c) not in cmap})


def safe_zone_overlay(ovl_dir: Path, every: int = 15, h: int = 1920, w: int = 1080) -> dict:
    """overlay PNGs: anything visible in YouTube's UI zones (outside the caption band) is a violation."""
    bad = []
    files = sorted(Path(ovl_dir).glob("*.png"))[::every]
    for f in files:
        a = cv2.imread(str(f), cv2.IMREAD_UNCHANGED)
        if a is None or a.shape[2] < 4:
            continue
        # content = visible AND bright/saturated; dark scrims/gradients behind text are allowed in UI zones
        al = (a[..., 3] > 100) & (a[..., :3].max(axis=2) > 110)
        below = al[h - UI_BOTTOM_PX:1895].copy()
        lo, hi = CAPTION_BAND
        below[max(0, lo - (h - UI_BOTTOM_PX)):max(0, hi - (h - UI_BOTTOM_PX))] = False   # captions allowed here
        right = al[200:1895, w - UI_RIGHT_PX:]
        if below.sum() > 150 or right.sum() > 150:
            bad.append({"frame": f.name, "bottom_px": int(below.sum()), "right_px": int(right.sum())})
    return {"checked": len(files), "violations": bad[:10], "n_violations": len(bad)}


def contact_sheet(video: Path, out: Path, n: int = 12) -> Path:
    """REAL decoded frames for the vision reviewer (never review a script as if it were the picture)."""
    d = float(probe(video)["format"]["duration"])
    cols = 6
    _run(["ffmpeg", "-y", "-v", "error", "-i", str(video), "-vf",
          f"fps={n}/{d:.2f},scale=270:480,tile={cols}x{(n + cols - 1) // cols}", "-frames:v", "1", str(out)])
    return out


VISION_RUBRIC = """You are a strict YouTube Shorts creative director. You see a contact sheet of REAL frames in time order.
Score 1-10 each: hook_frame (is frame 1 arresting without sound?), visual_variety (different picture/camera every ~3-5 s?),
polish (lighting, resolution, no AI artefacts, no tofu boxes, no clipped text), hierarchy (one focal point, legible type),
safe_zone (text not under bottom 500px / right 140px), consistency (one visual language), payoff (does the last frame close the loop).
Return JSON {"scores":{...},"verdict":"approve|revise|reject","fixes":["frame N: concrete change"]}.
Approve only if every score >= 7 and visual_variety >= 8. Be harsh: generic stock/template looks are 4-5."""


def evaluate(video: Path, overlay: Path | None = None, onscreen_text: str = "", font: str | None = None,
             vision: dict | None = None) -> dict:
    meta = probe(video)
    v = next((s for s in meta["streams"] if s["codec_type"] == "video"), {})
    has_a = any(s["codec_type"] == "audio" for s in meta["streams"])
    dur = float(meta["format"]["duration"])
    vm, am, hy = visual_metrics(video), audio_metrics(video), hygiene(video)
    checks: dict[str, str] = {
        "duration": "pass" if MIN_S <= dur <= MAX_S else f"fail: {dur:.1f}s",
        "resolution": "pass" if (v.get("width"), v.get("height")) == (1080, 1920) else "fail: not 1080x1920",
        "audio": "pass" if has_a else "fail: no audio",
        "cadence": "pass" if vm["longest_static_s"] <= MAX_STATIC_S else f"fail: {vm['longest_static_s']}s with no visible change",
        "distinct_shots": "pass" if vm["distinct_shots"] >= max(3, dur / SHOT_EVERY_S) else f"fail: {vm['distinct_shots']} shots in {dur:.0f}s",
        "motion": "pass" if vm["median_motion"] >= MIN_MOTION else f"fail: median motion {vm['median_motion']:.2f}",
        "freeze": "fail: frozen stretch" if hy["freeze"] else "pass",
        "black": "fail: black frames mid-video" if any(float(s) > 0.5 and float(s) + float(d) < dur - 0.3 for s, d in hy["black"]) else "pass",
        "loudness": "pass" if am["lufs"] is not None and LUFS_RANGE[0] <= am["lufs"] <= LUFS_RANGE[1] else f"fail: {am['lufs']} LUFS",
        "silence": "pass" if not am["silences"] else f"fail: {am['silences']}s silence",
    }
    if font and onscreen_text:
        miss = glyph_audit(onscreen_text, font)
        checks["glyphs"] = "pass" if not miss else f"fail: font lacks {''.join(miss)}"
    if overlay:
        sz = safe_zone_overlay(overlay)
        checks["safe_zone"] = "pass" if not sz["n_violations"] else f"fail: {sz['n_violations']} frames, e.g. {sz['violations'][:2]}"
    if vision is None:
        checks["vision"] = "fail: no frame-based review (run contact_sheet + VISION_RUBRIC)"
    else:
        s = vision.get("scores", {})
        ok = vision.get("verdict") == "approve" and s and min(s.values()) >= 7 and s.get("visual_variety", 0) >= 8
        checks["vision"] = "pass" if ok else f"fail: {vision.get('verdict')} {vision.get('fixes', [])[:3]}"
    return {"passed": all(c == "pass" for c in checks.values()), "checks": checks,
            "metrics": {"duration": dur, **vm, **am}}


if __name__ == "__main__":
    a = sys.argv[1:]
    arg = lambda k: a[a.index(k) + 1] if k in a else None
    video = Path(a[0])
    if arg("--sheet"):
        contact_sheet(video, Path(arg("--sheet")))
    text = Path(arg("--text")).read_text() if arg("--text") else ""
    vis = json.loads(Path(arg("--vision")).read_text()) if arg("--vision") else None
    res = evaluate(video, Path(arg("--overlay")) if arg("--overlay") else None, text, arg("--font"), vis)
    print(json.dumps(res, indent=2, ensure_ascii=False))
    raise SystemExit(0 if res["passed"] else 2)
