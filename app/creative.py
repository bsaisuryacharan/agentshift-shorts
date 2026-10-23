"""Bounded creative direction, candidate rendering, and learning for Shorts Factory.

This module never changes application code, installs tools, or pulls unreviewed assets. It may
only update a small preference file from measured candidate reviews and later performance data.
"""
from __future__ import annotations

import json
import logging
import math
import re
import shutil
import subprocess
import textwrap
import unicodedata
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFont

from .models import CreativeTreatment, VisualReview
from .playbook import PLAYBOOK

logger = logging.getLogger(__name__)

# Six authored poses per second keep production rendering practical on a small runner; ffmpeg
# delivers a 30 fps H.264 stream and the movement itself is designed as deliberate beat steps.
FPS = 6
CANVAS = (1080, 1920)
SAFE_BOTTOM = 1510
THUMB = (216, 384)


def default_treatments() -> list[CreativeTreatment]:
    """Three deliberately different treatments derived from the reference-library patterns."""
    return [
        CreativeTreatment(
            id="kinetic-evidence", name="Kinetic evidence", concept="A claim becomes evidence, then a takeaway.",
            visual_language="high-contrast editorial typography, one moving signal line, source cards",
            object_chain=["signal dot", "source card", "claim underline", "evidence marker", "takeaway frame"],
            banned=["crossfades", "particles", "lens flares", "3D card spins", "bouncy easing"],
            palette=["#09111F", "#F5F0E6", "#D6FF4B", "#FF5A36"],
            reference_techniques=["kinetic_type", "data_story", "product_film"],
        ),
        CreativeTreatment(
            id="editorial-collage", name="Editorial collage", concept="Source imagery is framed like a living magazine spread.",
            visual_language="paper panels, hard crops, moving annotation tape, one coral accent",
            object_chain=["picture crop", "paper panel", "annotation tape", "fact pin", "closing poster"],
            banned=["stock icons", "crossfades", "soft fades", "gradient UI chrome", "camera shake", "generic neon"],
            palette=["#EEE6D8", "#141414", "#ED5B42", "#1C5677"],
            reference_techniques=["editorial_collage", "product_film", "editorial_motion"],
        ),
        CreativeTreatment(
            id="data-pulse", name="Data pulse", concept="Each fact is a visual measurement that resolves into one clear conclusion.",
            visual_language="dark field, luminous measured bars, number-led type, disciplined grid",
            object_chain=["baseline", "rising bar", "comparison marker", "source tick", "conclusion lockup"],
            banned=["crossfades", "rainbow charts", "floating UI", "spinning objects", "random effects", "tiny labels"],
            palette=["#070B14", "#DDE8FF", "#55D6BE", "#8471FF"],
            reference_techniques=["data_story", "kinetic_type", "ui_motion"],
        ),
    ]


def creative_brief(lines: list[str], treatment: CreativeTreatment) -> dict[str, object]:
    """Human-auditable plan generated before any frames; no hidden visual improvisation."""
    return {
        "concept": treatment.concept,
        "object_chain": treatment.object_chain,
        "banned": sorted(set(PLAYBOOK["banned"] + treatment.banned)),
        "beat_map": [
            {"beat": index + 1, "copy": _screen_copy(line), "purpose": purpose}
            for index, (line, purpose) in enumerate(zip(lines, ["promise", "proof", "mechanism", "implication", "payoff", "takeaway", "close"] * ((len(lines) + 6) // 7)))
        ],
        "asset_policy": "Use first-party source imagery where available; otherwise use original, claim-specific visuals. Never reuse competitor media.",
        "review": "Inspect contact sheet and decoded candidate frames before delivery.",
    }


def refine_treatment(treatment: CreativeTreatment, prior_reviews: dict[str, VisualReview]) -> CreativeTreatment:
    """Convert visual-review findings into a fixed, safe set of rendering directives.

    Reviewer prose is untrusted feedback, never executable instruction. Only known visual defects
    map to directives, and these directives can influence renderer parameters—not source code,
    provider configuration, credentials, or network access.
    """
    notes = " ".join(note.lower() for review in prior_reviews.values() for note in review.repair_notes)
    directives: list[str] = []
    if "static" in notes or "repetitive" in notes:
        directives.append("increase_per_beat_variation")
    if "transition" in notes or "abrupt" in notes:
        directives.append("strengthen_object_continuity")
    if "label" in notes or "artifact" in notes:
        directives.append("remove_production_labels")
    if "text" in notes or "legible" in notes or "clutter" in notes:
        directives.append("protect_text_clearspace")
    return treatment.model_copy(update={"iteration_directives": directives})


def prioritize_treatments(treatments: list[CreativeTreatment], learning_path: Path) -> list[CreativeTreatment]:
    """Use previous measured scores only to choose candidate order, never to auto-approve."""
    if not learning_path.exists():
        return treatments
    state = json.loads(learning_path.read_text(encoding="utf-8"))
    weights = state.get("weights", {})
    return sorted(treatments, key=lambda treatment: float(weights.get(treatment.id, 0.5)), reverse=True)


def recent_feedback(path: Path) -> dict[str, VisualReview]:
    """Load only structured, allowlisted feedback from the previous observed run."""
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8")).get("last_reviews", {})
    feedback: dict[str, VisualReview] = {}
    for treatment_id, review in raw.items():
        try:
            feedback[treatment_id] = VisualReview.model_validate(review)
        except Exception:  # noqa: BLE001 - stale learning data must not block a new run
            logger.warning("Ignoring malformed persisted feedback for treatment %s", treatment_id)
    return feedback


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    names = (
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    )
    for name in names:
        if Path(name).exists():
            return ImageFont.truetype(name, size)
    raise RuntimeError("A production font is required for motion rendering.")


def _hex(value: str) -> tuple[int, int, int]:
    value = value.removeprefix("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def _cover(image: Image.Image, zoom: float, pan_x: float, pan_y: float) -> Image.Image:
    width, height = CANVAS
    scale = max(width / image.width, height / image.height) * zoom
    resized = image.resize((round(image.width * scale), round(image.height * scale)), Image.Resampling.LANCZOS)
    x = int((resized.width - width) * pan_x)
    y = int((resized.height - height) * pan_y)
    return resized.crop((x, y, x + width, y + height))


def _multiline(draw: ImageDraw.ImageDraw, text: str, xy: tuple[int, int], width: int, font: ImageFont.FreeTypeFont,
               fill: tuple[int, int, int], anchor: str = "la", spacing: int = 8) -> tuple[int, int, int, int]:
    wrapped = "\n".join(textwrap.wrap(text, width=width, break_long_words=False))
    draw.multiline_text(xy, wrapped, font=font, fill=fill, anchor=anchor, spacing=spacing)
    return draw.multiline_textbbox(xy, wrapped, font=font, anchor=anchor, spacing=spacing)


def _ease(progress: float) -> float:
    progress = min(1.0, max(0.0, progress))
    return 1 - (1 - progress) ** 3


def _base_frame(image: Path, progress: float, palette: list[str], scene_index: int,
                directives: set[str] | None = None) -> Image.Image:
    source = Image.open(image).convert("RGB")
    # A source asset can appear in several honest crops, but each beat must have a visibly
    # different compositional state.  The pan continues throughout the whole beat rather than
    # easing to a stop halfway through it; frozen-frame QA caught the former end-of-beat pose.
    # The deterministic path avoids random/template drift while giving source imagery an honest
    # documentary Ken-Burns movement.
    directives = directives or set()
    varied = "increase_per_beat_variation" in directives
    base_x = (0.08, 0.70, 0.42, 0.90, 0.25)[scene_index % 5]
    base_y = (0.12, 0.50, 0.85, 0.30, 0.68)[scene_index % 5]
    direction_x = (-1, 1, -1, 1, -1)[scene_index % 5]
    direction_y = (1, -1, 1, -1, 1)[scene_index % 5]
    # Reviewer learning only widens the compositional spread; it never invents new media.
    span_x, span_y = (0.34, 0.26) if varied else (0.28, 0.20)
    pan_x = min(0.96, max(0.04, base_x + direction_x * (progress - 0.5) * span_x))
    pan_y = min(0.96, max(0.04, base_y + direction_y * (progress - 0.5) * span_y))
    zoom_step = 0.16 if varied else 0.10
    frame = _cover(source, 1.12 + (scene_index % 3) * zoom_step + progress * (0.26 if varied else 0.18), pan_x, pan_y)
    # A constant heavy grade washes distinct photographs into same-looking frames. Tie the grade
    # strength to the scene so consecutive beats remain recognizably different photos.
    blend = (0.16 + 0.05 * (scene_index % 4)) if varied else (0.30 + 0.04 * (scene_index % 3))
    grade = Image.new("RGB", CANVAS, _hex(palette[scene_index % len(palette)] if varied else palette[0]))
    frame = Image.blend(frame, grade, blend)
    return ImageEnhance.Contrast(frame).enhance(1.12)


def _card_frame(palette: list[str], local: float, scene_index: int) -> Image.Image:
    """Surplus beats repeat no photograph: a designed typographic card stands in for re-shown media.

    Motion must be obvious frame to frame (the frozen-frame QA probe rejects sub-noise drift), so
    the gradient brightens strongly across the scene and a wide accent band sweeps visibly through
    the whole beat instead of crossing the canvas in a handful of frames.
    """
    base, base_end = _hex(palette[0]), _hex(palette[-1])
    ramp = Image.new("RGB", (1, CANVAS[1]))
    mix = 0.18 + 0.34 * local
    for y in range(CANVAS[1]):
        t = (y / (CANVAS[1] - 1)) * mix
        ramp.putpixel((0, y), tuple(int(a + (b - a) * t) for a, b in zip(base, base_end)))
    frame = ramp.resize(CANVAS)
    draw = ImageDraw.Draw(frame, "RGBA")
    accent = _hex(palette[2 % len(palette)])
    # Alternate the sweep between downward and upward so two consecutive recap cards do not
    # read as the same composition on the contact sheet.
    descending = scene_index % 2 == 0
    edge = int(-560 + (CANVAS[1] + 1120) * local) if descending else int(CANVAS[1] + 560 - (CANVAS[1] + 1120) * local)
    draw.polygon([(0, edge), (CANVAS[0], edge - 300), (CANVAS[0], edge - 560), (0, edge - 260)], fill=(*accent, 46))
    draw.line((0, edge, CANVAS[0], edge - 300), fill=(*accent, 220), width=10)
    draw.rectangle((84, 230, 118, 240 + 520 + (scene_index % 3) * 40), fill=(*accent, 235))
    # The right third would otherwise read as empty on the contact sheet. A soft glow that
    # travels with the sweep balances the typographic block without inventing imagery.
    glow_y = int(CANVAS[1] * (0.25 + 0.5 * local) if descending else CANVAS[1] * (0.75 - 0.5 * local))
    draw.ellipse((CANVAS[0] - 640, glow_y - 320, CANVAS[0] + 40, glow_y + 320), fill=(*accent, 24))
    draw.ellipse((CANVAS[0] - 430, glow_y - 190, CANVAS[0] + 40, glow_y + 190), fill=(*accent, 22))
    for step in range(5):
        x = CANVAS[0] - 150 + step * 30
        draw.line((x, glow_y - 330, x - 160, glow_y + 330), fill=(*base_end, 28 - step * 4), width=4)
    return frame


def _screen_copy(text: str, words: int = 5) -> str:
    """On-screen copy is a visual cue, never a duplicate transcript."""
    # Narration may retain scientific notation, but its display cue must be renderable by the
    # bundled production fonts. Prevent a missing-glyph square from reaching a final frame.
    # Unicode dashes vanish in the ASCII fold below and would weld neighbouring words together
    # ("El Niño-driven" → "NINODRIVEN"). They are spaced out before the fold; the plain ASCII
    # hyphen (as in "RS-25") is kept literal.
    cleaned = re.sub(r"[\u2010-\u2015\u2212]", " ", text.replace("γ", "gamma").replace("₹", ""))
    cleaned = unicodedata.normalize("NFKD", cleaned).encode("ascii", "ignore").decode("ascii")
    cleaned = " ".join(cleaned.split())
    # Prefer a self-contained first clause to a teaser cut midway through its payoff.
    cleaned = re.split(r"[,;:]", cleaned, maxsplit=1)[0]
    selected = cleaned.split()[:words]
    # Never leave the viewer on a grammatical fragment such as "ENGINE FOR" or "SMOKE OVER".
    # A smaller, complete cue is more readable than a six-word transcription that promises a
    # missing payoff.
    while len(selected) > 2 and selected[-1].lower().strip(".,;:!?'") in {
        "a", "an", "and", "at", "by", "for", "from", "how", "in", "into", "near", "of",
        "on", "over", "than", "the", "to", "with",
    }:
        selected.pop()
    return " ".join(selected).upper()


def _measured_numeric(text: str) -> str | None:
    """A number-plus-unit actually spoken in the narration, or None — never a generic caption."""
    cleaned = _screen_copy(text, words=12)
    match = re.search(r"\b\d+(?:\.\d+)?\s*(?:SECONDS?|MINUTES?|PERCENT|%|HOURS?|DAYS?|MILLION|BILLION)\b", cleaned)
    return match.group(0) if match else None


def _measured_copy(text: str) -> str:
    """Extract only a number actually spoken in the narration; never invent a chart or comparison."""
    return _measured_numeric(text) or _screen_copy(text, words=4)


def _accent(palette: list[str], local_or_index: int, varied: bool) -> tuple[int, int, int]:
    """Alternate the accent between the declared palette colors when variety is requested."""
    choice = 2 if not varied else (2 + (local_or_index + 1) % max(1, len(palette) - 2))
    return _hex(palette[min(choice, len(palette) - 1)])


def _scene_captions(lines: list[str]) -> list[str]:
    """Per-beat display cues that never repeat verbatim in consecutive beats.

    Narration often opens several beats with the same subject ("Air quality worsened…" twice);
    when a repeat would occur, the later beat shows its trailing clause instead, which carries
    that beat's own claim.
    """
    captions = [_screen_copy(line, words=7) for line in lines]
    for index in range(1, len(captions)):
        if captions[index] != captions[index - 1]:
            continue
        parts = re.split(r"[,;:]", lines[index], maxsplit=1)
        if len(parts) == 2 and parts[1].strip():
            alternate = _screen_copy(parts[1], words=7)
            if alternate and alternate != captions[index]:
                captions[index] = alternate
    return captions


def _kinetic(frame: Image.Image, treatment: CreativeTreatment, text: str, local: float, index: int,
             directives: set[str] | None = None, caption: str | None = None) -> Image.Image:
    directives = directives or set()
    varied = "increase_per_beat_variation" in directives
    clear = "protect_text_clearspace" in directives
    draw = ImageDraw.Draw(frame, "RGBA")
    accent = _accent(treatment.palette, index % 4, varied)
    light = _hex(treatment.palette[1])
    phase = index % 4
    x = int(88 + 900 * _ease(local))
    line_y = (265, 1450, 360, 1190)[phase]
    draw.line((88, line_y, x, line_y), fill=(*accent, 255), width=14)
    draw.ellipse((x - 18, line_y - 18, x + 18, line_y + 18), fill=(*accent, 255))
    if phase == 0:
        draw.rounded_rectangle((68, 360, 1010, 720), radius=28, fill=(*_hex(treatment.palette[0]), 225),
                               outline=(*_hex(treatment.palette[2 % len(treatment.palette)]), 140), width=3)
        headline_y, copy_width = 455, 18
    elif phase == 1:
        draw.rounded_rectangle((70, 980, 1010, 1370), radius=28, fill=(*_hex(treatment.palette[0]), 232),
                               outline=(*_hex(treatment.palette[2 % len(treatment.palette)]), 140), width=3)
        headline_y, copy_width = 1060, 19
    elif phase == 2:
        draw.polygon([(68, 540), (1012, 460), (1012, 890), (68, 970)], fill=(*_hex(treatment.palette[0]), 228),
                     outline=(*_hex(treatment.palette[2 % len(treatment.palette)]), 140), width=3)
        headline_y, copy_width = 625, 17
    else:
        draw.rounded_rectangle((68, 730, 1012, 1120), radius=190, fill=(*_hex(treatment.palette[0]), 226),
                               outline=(*_hex(treatment.palette[2 % len(treatment.palette)]), 140), width=3)
        headline_y, copy_width = 815, 18
    if clear:
        # More air around display copy; one fewer word per line keeps the cue subordinate.
        copy_width = max(12, copy_width - 3)
        headline_y += 24
    scale = 0.94 + 0.06 * _ease(local * 1.8)
    headline = caption or _screen_copy(text, words=6 if clear else 7)
    font = _font(round(84 if clear else 90 * scale), True)
    _multiline(draw, headline, (84, headline_y), copy_width, font, light, spacing=4)
    return frame


def _collage(frame: Image.Image, treatment: CreativeTreatment, text: str, local: float, index: int,
             directives: set[str] | None = None, caption: str | None = None) -> Image.Image:
    directives = directives or set()
    varied = "increase_per_beat_variation" in directives
    paper, ink = map(_hex, treatment.palette[:2])
    accent = _accent(treatment.palette, index % 3, varied)
    draw = ImageDraw.Draw(frame, "RGBA")
    # The panel slides toward its rest position while a settling tilt straightens to level.
    offset = int((88 if varied else 55) * (1 - _ease(local)))
    tilt = math.radians(3.5 * (1 - _ease(local)))
    panel = [(55 - offset, 330), (980 - offset, 285), (1008 - offset, 930), (80 - offset, 990)]
    if tilt:
        pivot = (531.5 - offset, 660.0)
        panel = [(px - pivot[0], py - pivot[1]) for px, py in panel]
        panel = [((px * math.cos(tilt) - py * math.sin(tilt)) + pivot[0],
                  (px * math.sin(tilt) + py * math.cos(tilt)) + pivot[1]) for px, py in panel]
        panel = [(round(px), round(py)) for px, py in panel]
    # The panel carries story copy, not editing labels such as "field note" or "keep watching".
    # It is deliberately smaller so the sourced photograph remains the principal visual.
    draw.polygon(panel, fill=(*paper, 238))
    draw.rectangle((74, 300, 290, 324), fill=(*accent, 255))
    drift = round((1 - _ease(local)) * 14)
    _multiline(draw, caption or _screen_copy(text, words=7), (90 + drift, 455 - drift), 18,
               _font(76, True), ink, spacing=1)
    tape_y = int(900 - (96 if varied else 70) * _ease(local))
    draw.rounded_rectangle((80, tape_y, 420, tape_y + 18), radius=5, fill=(*accent, 245))
    return frame


def _data(frame: Image.Image, treatment: CreativeTreatment, text: str, local: float, index: int,
          directives: set[str] | None = None, caption: str | None = None) -> Image.Image:
    directives = directives or set()
    varied = "increase_per_beat_variation" in directives
    draw = ImageDraw.Draw(frame, "RGBA")
    light, accent = _hex(treatment.palette[1]), _accent(treatment.palette, index % 3, varied)
    # Random bars falsely suggest a measured comparison. Use one real spoken measurement as the
    # hero and a moving baseline only as a compositional device. A numbers-free beat keeps a single
    # headline — echoing the caption twice reads as cluttered on the contact sheet.
    marker_x = int(84 + 900 * _ease(local))
    for y in (315, 1480):
        draw.line((84, y, 996, y), fill=(*light, 55), width=3)
        draw.line((84, y, marker_x, y), fill=(*accent, 240), width=10)
        draw.ellipse((marker_x - 12, y - 12, marker_x + 12, y + 12), fill=(*accent, 255))
    metric = _measured_numeric(text)
    if metric:
        metric_font = _font(122 if len(metric) <= 12 else 86, True)
        _multiline(draw, metric, (84, 500), 13, metric_font, accent, spacing=2)
        remainder = _screen_copy(re.sub(re.escape(metric), "", text, flags=re.IGNORECASE), words=6).strip()
        if remainder:
            _multiline(draw, remainder, (84, 1090), 19, _font(64, True), light, spacing=1)
    else:
        _multiline(draw, caption or _screen_copy(text, words=6), (84, 1090), 19, _font(64, True), light, spacing=1)
    return frame


def _recap_scenes(images: list[Path]) -> set[int]:
    """Scenes whose photo had already appeared earlier in the same candidate."""
    recap: set[int] = set()
    seen: set[Path] = set()
    for scene, asset in enumerate(images):
        if asset in seen:
            recap.add(scene)
        seen.add(asset)
    return recap


def render_candidate(images: list[Path], lines: list[str], audio: Path, treatment: CreativeTreatment, destination: Path) -> tuple[Path, Path]:
    """Create deterministic, animated candidate frames and encode an MP4 plus contact sheet."""
    if len(images) != len(lines):
        raise RuntimeError("Every narration beat requires one source image.")
    duration = float(subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(audio)
    ], text=True).strip())
    work = destination.parent / f"frames-{treatment.id}"
    shutil.rmtree(work, ignore_errors=True); work.mkdir(parents=True)
    total = max(math.ceil(duration * FPS), len(lines) * FPS)
    scene_duration = duration / len(lines)
    frame_paths: list[Path] = []
    renderers = {"kinetic-evidence": _kinetic, "editorial-collage": _collage, "data-pulse": _data}
    renderer = renderers[treatment.id]
    directives = set(treatment.iteration_directives)
    # Sample a quarter into each scene: rounding a scene's exact start can land on the previous
    # beat's final frame, and reviewers then see the prior caption twice in the storyboard.
    scene_starts = [min(round((scene + 0.25) * scene_duration * FPS), max(total - 1, 0)) for scene in range(len(lines))]
    # With fewer verified photos than beats, surplus beats re-show an already used photo. Reviewers
    # read that as "the same shot everywhere", so those beats become typographic cards instead.
    recap_scenes = _recap_scenes(images)
    captions = _scene_captions(lines)
    for frame_no in range(total):
        time = min(frame_no / FPS, duration - 0.001)
        index = min(int(time / scene_duration), len(lines) - 1)
        local = (time - index * scene_duration) / scene_duration
        if index in recap_scenes:
            image = _card_frame(treatment.palette, local, index)
        else:
            image = _base_frame(images[index], local, treatment.palette, index, directives)
        image = renderer(image, treatment, lines[index], local, index, directives, captions[index])
        output = work / f"frame-{frame_no:05}.jpg"
        image.convert("RGB").save(output, quality=88, optimize=True)
        frame_paths.append(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run([
        "ffmpeg", "-y", "-framerate", str(FPS), "-i", str(work / "frame-%05d.jpg"), "-i", str(audio),
        "-t", f"{duration:.3f}", "-map", "0:v", "-map", "1:a", "-r", "30", "-c:v", "libx264", "-crf", "19",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(destination),
    ], capture_output=True, text=True, check=False)
    if result.returncode:
        raise RuntimeError(f"Candidate encode failed: {result.stderr[-800:]}")
    contact = _contact_sheet(frame_paths, destination.parent / f"{treatment.id}-contact-sheet.jpg", scene_starts)
    return destination, contact


def _contact_sheet(frames: list[Path], destination: Path, scene_starts: list[int] | None = None,
                   filler_beats: set[int] | None = None) -> Path:
    """Strictly one tile per narrated beat: a storyboard, never duplicated frames.

    Mid-beat sampling repeatedly re-showed one photograph or one caption and independent review
    read the grid as "the same frame everywhere". A beat-count sheet is also the review surface
    the treatments were built for: every distinct composition is judged exactly once.
    """
    total = len(frames)
    starts = sorted(set(scene_starts or []))
    chosen: list[int] = starts[:9] if starts else [round(f * (total - 1) / 8) for f in range(9)]
    chosen = sorted(dict.fromkeys(chosen))
    # Two columns keeps the sheet near a 1:2.5 portrait: reviewers read it as a vertical filmstrip
    # of the short instead of mistaking the grid for the short's actual collage layout.
    cols = 2
    rows = max(3, math.ceil(len(chosen) / cols))
    sheet = Image.new("RGB", (THUMB[0] * cols, THUMB[1] * rows), "#111111")
    for i, frame_index in enumerate(chosen):
        image = Image.open(frames[frame_index]).convert("RGB").resize(THUMB, Image.Resampling.LANCZOS)
        sheet.paste(image, ((i % cols) * THUMB[0], (i // cols) * THUMB[1]))
    sheet.save(destination, quality=90)
    return destination


def learn_from_reviews(path: Path, reviews: dict[str, VisualReview], winner: str | None) -> None:
    """Bounded learning: only update selection weights; never modify code/tools/prompts unsupervised."""
    state = json.loads(path.read_text()) if path.exists() else {"schema_version": 1, "weights": {}, "runs": []}
    weights = state.setdefault("weights", {})
    for treatment_id, review in reviews.items():
        previous = float(weights.get(treatment_id, 0.5))
        observed = review.average / 10
        weights[treatment_id] = round(previous * 0.75 + observed * 0.25 + (0.02 if treatment_id == winner else 0), 3)
    state["last_reviews"] = {key: value.model_dump() for key, value in reviews.items()}
    state["runs"].append({"winner": winner, "scores": {key: value.average for key, value in reviews.items()}})
    state["runs"] = state["runs"][-100:]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")
