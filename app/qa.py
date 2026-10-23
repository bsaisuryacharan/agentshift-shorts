from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .models import Script


@dataclass
class QaResult:
    passed: bool
    checks: dict[str, str]

    def text(self) -> str:
        return json.dumps({"passed": self.passed, "checks": self.checks}, indent=2)


def probe(video: Path) -> dict:
    output = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(video)],
                            capture_output=True, text=True, check=True).stdout
    return json.loads(output)


def hard_gate(video: Path, script: Script, prior_scripts: list[str]) -> QaResult:
    metadata = probe(video)
    streams = metadata["streams"]
    visual = next((s for s in streams if s["codec_type"] == "video"), {})
    audio = next((s for s in streams if s["codec_type"] == "audio"), {})
    duration = float(metadata["format"]["duration"])
    checks = {
        "duration": "pass" if 20 <= duration <= 60 else f"fail: {duration:.1f}s outside 20-60s",
        "resolution": "pass" if (visual.get("width"), visual.get("height")) == (1080, 1920) else "fail: not 1080x1920",
        "audio": "pass" if audio else "fail: no audio stream",
        "telegram_size": "pass" if video.stat().st_size < 49 * 1024 * 1024 else "fail: exceeds 49MB",
        "fact_ledger": "pass" if all(c.source_ids for c in script.claims) else "fail: uncited claim",
    }
    words = set(re.findall(r"[a-z]{4,}", script.narration.lower()))
    max_overlap = max((len(words & set(re.findall(r"[a-z]{4,}", old.lower()))) / max(len(words), 1) for old in prior_scripts), default=0)
    checks["originality_similarity"] = "pass" if max_overlap < .60 else f"fail: {max_overlap:.0%} overlap with recent script"
    # ffmpeg's black/freeze detectors provide deterministic evidence rather than subjective visual claims.
    freeze = subprocess.run(["ffmpeg", "-i", str(video), "-vf", "freezedetect=n=0.003:d=0.5", "-f", "null", "-"],
                            check=False, capture_output=True, text=True).stderr
    checks["no_frozen_stretch"] = "pass" if "freeze_start" not in freeze else "fail: frozen stretch >0.5s"
    return QaResult(passed=all(v == "pass" for v in checks.values()), checks=checks)
