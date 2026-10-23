"""HyperFrames motion gallery: index, search, and install registry motion blocks.

The HyperFrames registry ships ~450 installable motion blocks and components. This module
turns that catalog into a local, queryable motion library so every faceless Short can be
assembled from proven motion graphics instead of hand-rebuilding named looks.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any, Iterable

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
INDEX_PATH = DATA_DIR / "hf_registry_index.json"
KIT_PATH = DATA_DIR / "hf_motion_kit.json"

CATALOG_CMD = ["npx", "--yes", "hyperframes", "catalog", "--json"]

# Motion kit: the recurring grammar of a faceless Short. Each beat type maps to the
# registry items that give it texture, energy, and legibility.
DEFAULT_KIT: dict[str, list[dict[str, str]]] = {
    "hook": [
        {"name": "headline-slam", "type": "component", "role": "weighted hook type"},
        {"name": "rgb-glitch-text", "type": "component", "role": "controlled glitch on the question"},
        {"name": "yt-camera-move", "type": "component", "role": "punch-in camera"},
    ],
    "reveal": [
        {"name": "particle-text-dissolve", "type": "component", "role": "assemble a claim from particles"},
        {"name": "scan-band", "type": "component", "role": "single sweep accent"},
        {"name": "shimmer-sweep", "type": "component", "role": "light passing over a headline"},
    ],
    "data": [
        {"name": "count-up", "type": "component", "role": "stat counter"},
        {"name": "number-wheel", "type": "component", "role": "rolling digits"},
        {"name": "mk-progress-stat", "type": "block", "role": "big-numeral statistic card"},
        {"name": "beat-pulse-background", "type": "component", "role": "energy pulsing behind a number"},
    ],
    "diagram": [
        {"name": "locked-nucleus-orbit", "type": "component", "role": "orbits around a fixed center"},
        {"name": "svg-line-draw-loader", "type": "component", "role": "drawn path reveal"},
        {"name": "falling-lines", "type": "block", "role": "directional motion streaks"},
    ],
    "transition": [
        {"name": "chromatic-aberration-wipe", "type": "component", "role": "hard cut with RGB split"},
        {"name": "cinematic-zoom", "type": "block", "role": "zoom-blur transition"},
        {"name": "glitch", "type": "block", "role": "digital glitch transition"},
    ],
    "texture": [
        {"name": "grain-overlay", "type": "component", "role": "film grain"},
        {"name": "vignette", "type": "component", "role": "edge falloff"},
        {"name": "vfx-anamorphic-flare", "type": "block", "role": "anamorphic light points"},
    ],
}


def _run(cmd: list[str], cwd: Path | None = None, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)


def refresh_index(destination: Path = INDEX_PATH) -> dict[str, Any]:
    """Pull the full HyperFrames catalog into a local JSON index."""
    proc = _run(CATALOG_CMD, timeout=180)
    if proc.returncode != 0:
        raise RuntimeError(f"hyperframes catalog failed: {proc.stderr.strip()[:400]}")
    payload = json.loads(proc.stdout)
    items = payload if isinstance(payload, list) else payload.get("results", payload.get("items", []))
    index = {
        "schema_version": 1,
        "source": "hyperframes registry",
        "count": len(items),
        "items": [
            {
                "name": i.get("name"),
                "type": i.get("type"),
                "title": i.get("title"),
                "description": i.get("description", ""),
                "tags": i.get("tags", []),
                "dimensions": i.get("dimensions"),
                "duration": i.get("duration"),
            }
            for i in items
        ],
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(index, indent=2), encoding="utf-8")
    return index


def load_index(path: Path = INDEX_PATH) -> dict[str, Any]:
    if not path.exists():
        return refresh_index(path)
    return json.loads(path.read_text(encoding="utf-8"))


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def search(query: str, kind: str | None = None, limit: int = 6, path: Path = INDEX_PATH) -> list[dict[str, Any]]:
    """Rank local index items against a plain-English motion query.

    Falls back to the CLI (which may know fresher items) when the local index is empty
    or the query returns nothing.
    """
    index = load_index(path)
    terms = _words(query)
    scored: list[tuple[float, dict[str, Any]]] = []
    for item in index["items"]:
        if kind and item.get("type") != kind:
            continue
        haystack = " ".join(
            [str(item.get("name", "")), str(item.get("title", "")), str(item.get("description", "")), " ".join(item.get("tags", []))]
        )
        words = _words(haystack)
        if not terms:
            continue
        overlap = len(terms & words)
        if not overlap:
            continue
        scored.append((overlap / len(terms), item))
    scored.sort(key=lambda pair: (-pair[0], str(pair[1].get("name"))))
    results = [item for _, item in scored[:limit]]
    if results:
        return results

    proc = _run(["npx", "--yes", "hyperframes", "catalog", "--query", query, "--json"], timeout=120)
    if proc.returncode != 0:
        return []
    payload = json.loads(proc.stdout)
    needle = (kind or "").strip()
    return [i for i in payload.get("results", []) if not needle or i.get("type") == needle][:limit]


def kit(roles: Iterable[str] | None = None, path: Path = KIT_PATH) -> dict[str, list[dict[str, str]]]:
    """Return the curated motion kit, or only the requested beat roles."""
    if path.exists():
        stored = json.loads(path.read_text(encoding="utf-8"))
        data = stored.get("roles", stored)
    else:
        data = DEFAULT_KIT
    if roles is None:
        return data
    return {role: data[role] for role in roles if role in data}


def save_kit(data: dict[str, list[dict[str, str]]] | None = None, path: Path = KIT_PATH) -> Path:
    data = data or DEFAULT_KIT
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "note": "Curated HyperFrames registry motion kit for faceless Shorts. Each role is a beat intent.",
                "roles": data,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def install(project: Path, names: Iterable[str]) -> dict[str, str]:
    """Install registry items into a project. Returns name -> status."""
    results: dict[str, str] = {}
    for name in dict.fromkeys(names):
        proc = _run(["npx", "--yes", "hyperframes", "add", name, "--no-clipboard"], cwd=project, timeout=180)
        results[name] = "installed" if proc.returncode == 0 else f"failed: {proc.stderr.strip()[:200]}"
    return results


def installed(project: Path) -> list[str]:
    manifest = project / "hyperframes.json"
    if not manifest.exists():
        return []
    data = json.loads(manifest.read_text(encoding="utf-8"))
    return [item.get("name", "") for item in data.get("registryItems", [])]
