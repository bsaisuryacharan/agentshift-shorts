"""Curate motion references without copying other creators' assets or prompts."""
from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

GALLERY_URL = "https://prompt-motion.com"
GALLERY_SOURCE = "https://griffinwooldridge.com/blog/claude-motion-graphics-prompts"


def _techniques(label: str) -> list[str]:
    """Classify only from the public accessibility label; never retain prompt text."""
    words = label.lower()
    rules = {
        "kinetic_type": ("type", "text", "word", "letter", "title"),
        "ui_motion": ("ui", "app", "website", "interface", "dashboard", "cursor"),
        "data_story": ("data", "chart", "graph", "analytics", "stat"),
        "product_film": ("product", "launch", "brand", "showreel"),
        "editorial_collage": ("paper", "collage", "editorial", "poster"),
        "abstract_form": ("shape", "morph", "3d", "sphere", "abstract"),
    }
    found = [name for name, keywords in rules.items() if any(word in words for word in keywords)]
    return found or ["editorial_motion"]


def fetch_reference_library(destination: Path, limit: int = 200) -> list[dict[str, object]]:
    """Record 200 public gallery cards as attribution-preserving design references.

    The resulting library deliberately excludes thumbnails, videos, and full prompts. The
    system uses it to choose a technique, not to reproduce somebody else's work.
    """
    response = httpx.get(GALLERY_URL, headers={"User-Agent": "ShortsFactory/1.0"}, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    entries: list[dict[str, object]] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href = str(anchor["href"])
        if not re.fullmatch(r"/[a-z0-9-]+-[a-f0-9]{6}", href) or href in seen:
            continue
        seen.add(href)
        label = anchor.get("aria-label") or anchor.get_text(" ", strip=True)
        creator = re.search(r"@([\w_]+)", label)
        entries.append(
            {
                "id": href.removeprefix("/"),
                "reference_url": f"{GALLERY_URL}{href}",
                "creator": creator.group(1) if creator else "unknown",
                "label": label,
                "techniques": _techniques(label),
                "license_note": "Reference only. Do not reuse the creator's media, copy, or full prompt.",
            }
        )
        if len(entries) == limit:
            break
    if len(entries) < limit:
        raise RuntimeError(f"Gallery returned only {len(entries)} usable cards; expected {limit}.")
    payload = {
        "schema_version": 1,
        "collected_at": datetime.now(UTC).isoformat(),
        "source": GALLERY_SOURCE,
        "gallery": GALLERY_URL,
        "count": len(entries),
        "usage": "Technique reference and attribution only; no third-party media/prompt copying.",
        "entries": entries,
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return entries


def library_summary(path: Path) -> dict[str, int]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    result: dict[str, int] = {}
    for item in payload["entries"]:
        for technique in item["techniques"]:
            result[technique] = result.get(technique, 0) + 1
    return result
