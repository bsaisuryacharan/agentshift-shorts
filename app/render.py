from __future__ import annotations

import base64
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import httpx
from PIL import Image, ImageDraw, ImageFont

from .models import Script
from .providers import ProviderError
from .settings import Settings


def _run(args: list[str]) -> None:
    result = subprocess.run(args, check=False, text=True, capture_output=True)
    if result.returncode:
        raise ProviderError(f"Render command failed: {' '.join(args[:2])}: {result.stderr[-800:]}")


def narrate(settings: Settings, script: Script, destination: Path) -> Path:
    try:
        _run([sys.executable, "-m", "edge_tts", "--voice", "en-US-AvaMultilingualNeural", "--rate", "+2%",
              "--text", script.narration, "--write-media", str(destination)])
        return destination
    except ProviderError:
        if not (settings.cloudflare_account_id and settings.cloudflare_api_token):
            raise
    endpoint = (f"https://api.cloudflare.com/client/v4/accounts/{settings.cloudflare_account_id}/"
                "ai/run/@cf/myshell-ai/melotts")
    response = httpx.post(endpoint, headers={"Authorization": f"Bearer {settings.cloudflare_api_token}"},
                          json={"prompt": script.narration, "lang": "en"}, timeout=90)
    response.raise_for_status()
    if response.headers.get("content-type", "").startswith("audio/"):
        destination.write_bytes(response.content)
        return destination
    audio = response.json().get("result", {}).get("audio")
    if not audio:
        raise ProviderError("Cloudflare MeloTTS did not return audio data.")
    destination.write_bytes(base64.b64decode(audio))
    return destination


def make_srt(lines: list[str], destination: Path, seconds: float) -> Path:
    # Even allocation is conservative; future forced alignment can replace it without weakening QA.
    per_line = seconds / len(lines)
    def stamp(t: float) -> str:
        ms = round(t * 1000); h, ms = divmod(ms, 3_600_000); m, ms = divmod(ms, 60_000); s, ms = divmod(ms, 1000)
        return f"{h:02}:{m:02}:{s:02},{ms:03}"
    blocks = []
    for index, line in enumerate(lines, 1):
        blocks.append(f"{index}\n{stamp((index-1)*per_line)} --> {stamp(index*per_line)}\n{line}\n")
    destination.write_text("\n".join(blocks), encoding="utf-8")
    return destination


def audio_duration(audio: Path) -> float:
    result = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                             "-of", "default=noprint_wrappers=1:nokey=1", str(audio)], text=True,
                            capture_output=True, check=True)
    return float(result.stdout.strip())


def render_vertical(images: list[Path], audio: Path, subtitles: Path, destination: Path) -> Path:
    if not images:
        raise ProviderError("No images were generated; refusing to render a blank video.")
    duration = audio_duration(audio)
    images = _caption_images(images, _captions_from_srt(subtitles), destination.parent / "captioned")
    each = max(duration / len(images), 1.0)
    scene_frames = max(round(each * 30), 30)
    inputs = []
    for image in images:
        inputs.extend(["-loop", "1", "-t", str(each), "-i", str(image)])
    filters = [
        f"[{i}:v]scale=1080:1920:force_original_aspect_ratio=increase,"
        f"crop=1080:1920,zoompan=z='1+0.08*on/{scene_frames}':d={scene_frames}:s=1080x1920:fps=30,setsar=1[v{i}]"
        for i in range(len(images))
    ]
    joins = "".join(f"[v{i}]" for i in range(len(images)))
    # Captions deliberately stay high enough above the Shorts UI safe zone.
    filters.append(f"{joins}concat=n={len(images)}:v=1:a=0[video]")
    _run(["ffmpeg", "-y", *inputs, "-i", str(audio), "-filter_complex", ";".join(filters),
          "-map", "[video]", "-map", f"{len(images)}:a", "-t", str(duration), "-c:v", "libx264",
          "-pix_fmt", "yuv420p", "-r", "30", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(destination)])
    return destination


def _caption_images(images: list[Path], captions: list[tuple[str, float, float]], destination: Path) -> list[Path]:
    if len(images) != len(captions):
        raise ProviderError("Scene count does not match caption count; caption timing is unsafe.")
    destination.mkdir(parents=True, exist_ok=True)
    font = _caption_font()
    rendered = []
    for index, (image_path, (caption, _, _)) in enumerate(zip(images, captions)):
        image = Image.open(image_path).convert("RGB")
        scale = max(1080 / image.width, 1920 / image.height)
        image = image.resize((round(image.width * scale), round(image.height * scale)), Image.Resampling.LANCZOS)
        left, top = (image.width - 1080) // 2, (image.height - 1920) // 2
        image = image.crop((left, top, left + 1080, top + 1920))
        draw = ImageDraw.Draw(image)
        wrapped = "\n".join(textwrap.wrap(caption, width=30))
        box = draw.multiline_textbbox((0, 0), wrapped, font=font, align="center", spacing=10, stroke_width=3)
        x, y = (1080 - (box[2] - box[0])) // 2, 1260
        draw.rounded_rectangle((x - 30, y - 20, x + box[2] - box[0] + 30, y + box[3] - box[1] + 20), radius=20, fill=(0, 0, 0, 170))
        draw.multiline_text((x, y), wrapped, font=font, fill="white", align="center", spacing=10, stroke_width=2, stroke_fill="black")
        output = destination / f"scene_{index:02}.jpg"
        image.save(output, quality=94)
        rendered.append(output)
    return rendered


def _caption_font() -> ImageFont.FreeTypeFont:
    for candidate in ("/System/Library/Fonts/Supplemental/Arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, 54)
    raise ProviderError("No production caption font is available on this runner.")


def _captions_from_srt(path: Path) -> list[tuple[str, float, float]]:
    blocks = path.read_text(encoding="utf-8").strip().split("\n\n")
    captions = []
    for block in blocks:
        lines = block.splitlines()
        if len(lines) < 3:
            continue
        match = re.match(r"(\d\d):(\d\d):(\d\d),(\d\d\d) --> (\d\d):(\d\d):(\d\d),(\d\d\d)", lines[1])
        if not match:
            continue
        values = [int(value) for value in match.groups()]
        start = values[0] * 3600 + values[1] * 60 + values[2] + values[3] / 1000
        end = values[4] * 3600 + values[5] * 60 + values[6] + values[7] / 1000
        captions.append((" ".join(lines[2:]), start, end))
    if not captions:
        raise ProviderError("No timed captions could be read from the SRT file.")
    return captions
