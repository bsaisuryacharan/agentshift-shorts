"""Bounded local supervisor for a sequence of independently produced Shorts.

It records what each pipeline stage decided, applies only the system's allowlisted learning rules,
and treats unavailable reviews as a wait condition rather than an approval or blind retry.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .analytics import channel_analytics
from .settings import Settings
from .trends import analyze


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": 1, "delivered_runs": [], "attempts": []}
    return json.loads(path.read_text(encoding="utf-8"))


def _save(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _reviewer_unavailable(errors: list[str]) -> bool:
    return any("visual review unavailable" in error.lower() for error in errors)


def supervise(settings: Settings, target: int = 3, max_attempts: int = 9) -> dict[str, Any]:
    """Create up to `target` delivered review Shorts through stage-by-stage local supervision.

    This is intentionally bounded: the supervisor cannot install tools, change credentials, publish
    publicly, ignore a quality gate, or spin on a quota outage.
    """
    state_path = settings.data_dir / "teacher_loop_state.json"
    # Import here to keep the normal CLI entry point and the supervisor module acyclic.
    from .main import run

    state = _load(state_path)
    state["target"] = target
    state["updated_at"] = datetime.now(UTC).isoformat()
    delivered = set(state.get("delivered_runs", []))
    attempts_this_invocation = 0

    while len(delivered) < target and attempts_this_invocation < max_attempts:
        analytics = channel_analytics(settings)
        trends = analyze(settings)
        preflight = {
            "analytics_status": analytics.get("status"),
            "trend_sources": trends.source_status,
            "signal_count": len(trends.signals),
        }
        if analytics.get("status") != "ok":
            state["waiting_reason"] = "analytics_unavailable"
            state["attempts"].append({"at": datetime.now(UTC).isoformat(), "preflight": preflight, "status": "waiting"})
            break

        manifest = run()
        attempts_this_invocation += 1
        run_dir = settings.output_dir / manifest.run_id
        notes_path = run_dir / "teacher_notes.json"
        notes = json.loads(notes_path.read_text(encoding="utf-8")) if notes_path.exists() else {}
        state["attempts"].append({
            "at": datetime.now(UTC).isoformat(), "run_id": manifest.run_id, "preflight": preflight,
            "status": manifest.status, "teacher_notes": notes,
        })
        if manifest.status == "released":
            delivered.add(manifest.run_id)
            state.pop("waiting_reason", None)
            continue
        if _reviewer_unavailable(manifest.errors):
            state["waiting_reason"] = "visual_reviewer_unavailable"
            break
        state["waiting_reason"] = "quality_correction_required"

    state["delivered_runs"] = sorted(delivered)
    state["completed"] = len(delivered) >= target
    state["updated_at"] = datetime.now(UTC).isoformat()
    # Keep the persistent learning ledger inspectable but bounded.
    state["attempts"] = state["attempts"][-100:]
    _save(state_path, state)
    return state
