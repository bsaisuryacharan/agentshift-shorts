"""Attributed, bounded editorial rules distilled from current research.

These are production constraints, not claims that any tactic guarantees views.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

PLAYBOOK = {
    "schema_version": 1,
    "principles": [
        {"id": "appeal", "rule": "Frame one states a specific, visible promise in nine words or fewer.", "source": "YouTube performance guidance", "strength": "official"},
        {"id": "engagement", "rule": "Use a new proof, visual state, or question every 2-5 seconds; no filler setup.", "source": "YouTube engagement guidance + motion reference study", "strength": "mixed"},
        {"id": "satisfaction", "rule": "Resolve the hook with a sourced explanation; do not withhold the answer merely for duration.", "source": "YouTube performance guidance", "strength": "official"},
        {"id": "originality", "rule": "Use first-party facts and original narration/visual composition; never reproduce a competitor's edit, media, title, or prompt.", "source": "YouTube original-content update", "strength": "official"},
        {"id": "motion", "rule": "Write a beat map, one object chain, and a banned-effects list before rendering.", "source": "Prompt Motion reference analysis", "strength": "secondary"},
        {"id": "copy", "rule": "Keep on-screen copy to a short visual cue; narration carries explanation.", "source": "Prompt Motion reference analysis", "strength": "secondary"},
    ],
    "banned": ["generic scene slideshow", "copied competitor media", "unsourced numbers", "crossfades as default", "particles", "lens flares", "bouncy easing", "camera shake", "long first-frame setup"],
    "measurement_plan": ["shown in feed", "chose to view vs swiped away", "average view duration", "average percentage viewed", "likes/comments/shares", "audience retention key moments"],
    "sources": [
        {"title": "YouTube: Understand content performance", "url": "https://support.google.com/youtube/answer/16559650?hl=en", "kind": "official"},
        {"title": "YouTube: Shorts search and discovery", "url": "https://support.google.com/youtube/answer/11914225?co=YOUTUBE._YTVideoType%3Dshorts&hl=en-GB", "kind": "official"},
        {"title": "YouTube: Shorts analytics", "url": "https://support.google.com/youtube/answer/12942217?co=YOUTUBE._YTVideoType%3Dshorts&hl=en", "kind": "official"},
        {"title": "Prompt Motion analysis", "url": "https://griffinwooldridge.com/blog/claude-motion-graphics-prompts", "kind": "secondary"},
    ],
}


def writer_rules() -> str:
    return "\n".join(f"- {item['rule']}" for item in PLAYBOOK["principles"])


def write_playbook(destination: Path) -> Path:
    payload = {**PLAYBOOK, "refreshed_at": datetime.now(UTC).isoformat()}
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return destination
