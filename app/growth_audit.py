"""Evidence-based pre-publication growth audit. It measures readiness, not future views."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from .capabilities import inspect_capabilities
from .models import RunManifest
from .settings import Settings


def _competitor_scan(settings: Settings, topic: str) -> dict[str, object]:
    if not settings.youtube_api_key:
        return {"status": "unavailable: no YouTube API key", "items": []}
    # One search request per audit, deliberately bounded to preserve the daily API quota.
    response = httpx.get("https://www.googleapis.com/youtube/v3/search", params={
        "part": "snippet", "q": f"{topic} Shorts", "type": "video", "order": "relevance", "maxResults": 10,
        "publishedAfter": (datetime.now(UTC) - timedelta(days=90)).isoformat().replace("+00:00", "Z"),
        "safeSearch": "strict", "key": settings.youtube_api_key,
    }, timeout=25)
    response.raise_for_status()
    items = []
    for item in response.json().get("items", []):
        snippet = item["snippet"]
        items.append({"title": snippet["title"], "channel": snippet["channelTitle"], "published_at": snippet["publishedAt"],
                      "url": f"https://www.youtube.com/watch?v={item['id']['videoId']}"})
    return {"status": "ok", "items": items, "policy": "Use only for observable packaging patterns; never reuse media, scripts, or titles."}


def audit_run(settings: Settings, run_dir: Path) -> dict[str, object]:
    manifest = RunManifest.model_validate_json((run_dir / "manifest.json").read_text())
    if not manifest.script or not manifest.video:
        raise RuntimeError("Run has no completed script/video to audit.")
    creative = json.loads((run_dir / "creative_reviews.json").read_text())
    qa = json.loads((run_dir / "qa.json").read_text())
    ledger = json.loads((run_dir / "fact_ledger.json").read_text())
    reviews = {key: value for key, value in creative.items()}
    winner = reviews.get(manifest.selected_treatment or "", {})
    hook_words = len(manifest.script.hook.split())
    risks = []
    if hook_words > 11:
        risks.append("Hook is longer than 11 words; create a sharper first-frame version.")
    if len(manifest.script.body) < 3:
        risks.append("Fewer than three proof beats; the explanation may feel thin.")
    if winner.get("motion_readability", 0) < 8:
        risks.append("Motion readability is below release threshold.")
    if not risks:
        risks.append("No pre-release blocker detected. Actual audience response remains the deciding signal.")
    report = {
        "schema_version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "run_id": manifest.run_id,
        "scope": "pre-publication readiness; does not predict or promise views",
        "youtube_growth_dimensions": {
            "appeal": {"hook_words": hook_words, "title": manifest.script.title},
            "engagement": {"beats": len(manifest.script.body) + 2, "motion_readability": winner.get("motion_readability")},
            "satisfaction": {"accuracy": manifest.review.accuracy if manifest.review else None, "policy": manifest.review.policy if manifest.review else None},
            "originality": winner.get("originality"),
        },
        "source_integrity": {"source_count": len(ledger["sources"]), "claim_count": len(ledger["claims"]), "qa": qa},
        "creative_review": {"winner": manifest.selected_treatment, "winner_scores": winner, "all_candidates": reviews},
        "competition": _competitor_scan(settings, manifest.script.title),
        "risks_and_next_tests": risks,
        "capability_audit": inspect_capabilities(),
    }
    (run_dir / "growth_audit.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report
