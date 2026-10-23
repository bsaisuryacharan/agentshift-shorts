"""Safe capability awareness: detect gaps, never install or execute internet advice autonomously."""
from __future__ import annotations

import importlib.util
import shutil
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Capability:
    id: str
    purpose: str
    required_for: str
    detection: str
    available: bool
    suggested_install: str | None
    policy: str = "recommend_only"


def inspect_capabilities() -> list[dict[str, object]]:
    checks = [
        ("ffmpeg", "Encode, inspect, and quality-check video", "all production renders", shutil.which("ffmpeg") is not None, None),
        ("ffprobe", "Verify duration, resolution, and streams", "hard QA", shutil.which("ffprobe") is not None, None),
        ("chrome", "Deterministic HTML motion-card screenshots", "richer motion graphics", any(shutil.which(x) for x in ("google-chrome", "chromium", "chromium-browser")), "Install Google Chrome or Chromium"),
        ("whisperx", "Word-level timestamp alignment", "karaoke captions and retention pacing", importlib.util.find_spec("whisperx") is not None, "pip install whisperx"),
        ("scenedetect", "Detect accidental cuts and weak static stretches", "visual continuity QA", importlib.util.find_spec("scenedetect") is not None, "pip install scenedetect[opencv]"),
        ("playwright", "Render and inspect deterministic web motion frames", "HTML/Canvas motion candidate tests", importlib.util.find_spec("playwright") is not None, "pip install playwright && playwright install chromium"),
        ("youtube_analytics", "Measure shown-in-feed, chose-to-view, retention", "post-publication learning", False, "Authorize YouTube Analytics read-only scope or import Studio CSV"),
    ]
    return [asdict(Capability(id, purpose, required, id, available, install))
            for id, purpose, required, available, install in checks]
