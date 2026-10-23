"""Read-only YouTube Shorts performance monitor.

The monitor compares equal completed-day windows and writes a compact evidence packet consumed by
trend discovery. It never publishes, edits a video, or treats unavailable data as zero.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from .settings import Settings

METRICS = [
    "views", "engagedViews", "estimatedMinutesWatched", "averageViewDuration",
    "averageViewPercentage", "likes", "comments", "shares", "subscribersGained", "subscribersLost",
]


def _empty(status: str, note: str, destination: Path) -> dict[str, Any]:
    report = {"generated_at": datetime.now(UTC).isoformat(), "status": status, "note": note}
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def _credentials(settings: Settings) -> Credentials | None:
    if not settings.youtube_token_file.exists():
        return None
    # Load the grants actually held by the stored token first. Supplying new scopes here can
    # provoke an invalid_scope refresh request instead of giving the owner a clear reauth action.
    credentials = Credentials.from_authorized_user_file(str(settings.youtube_token_file))
    if not credentials.has_scopes(["https://www.googleapis.com/auth/yt-analytics.readonly"]):
        return None
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
        settings.youtube_token_file.write_text(credentials.to_json(), encoding="utf-8")
    return credentials


def _headers(result: dict[str, Any]) -> list[str]:
    return [header["name"] for header in result.get("columnHeaders", [])]


def _rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    names = _headers(result)
    return [dict(zip(names, row, strict=True)) for row in result.get("rows", [])]


def _summary(rows: list[dict[str, Any]]) -> dict[str, float | int | None]:
    totals = {metric: 0.0 for metric in METRICS if metric not in {"averageViewDuration", "averageViewPercentage"}}
    for row in rows:
        for metric in totals:
            totals[metric] += float(row.get(metric) or 0)
    denominator = totals.get("engagedViews") or totals.get("views") or 0
    for metric in ("averageViewDuration", "averageViewPercentage"):
        if denominator:
            totals[metric] = sum(float(row.get(metric) or 0) * float(row.get("engagedViews") or row.get("views") or 0) for row in rows) / denominator
        else:
            totals[metric] = None
    totals["netSubscribers"] = totals["subscribersGained"] - totals["subscribersLost"]
    return {key: round(value, 3) if isinstance(value, float) else value for key, value in totals.items()}


def _periods(days: int) -> tuple[tuple[str, str], tuple[str, str]]:
    # Analytics days are Pacific calendar days. Exclude the current day to avoid partial data.
    end = datetime.now(UTC).date() - timedelta(days=1)
    current_start = end - timedelta(days=days - 1)
    previous_end = current_start - timedelta(days=1)
    previous_start = previous_end - timedelta(days=days - 1)
    return (current_start.isoformat(), end.isoformat()), (previous_start.isoformat(), previous_end.isoformat())


def _query(service: Any, start: str, end: str) -> list[dict[str, Any]]:
    # `creatorContentType` is a supported *dimension* in channel reports, not a filter. Combining
    # it with `video` is not an available report shape, so this gives a channel-level Shorts
    # baseline without inventing unavailable per-video retention data.
    result = service.reports().query(
        ids="channel==MINE", startDate=start, endDate=end, metrics=",".join(METRICS),
        dimensions="creatorContentType",
    ).execute()
    return [row for row in _rows(result) if str(row.get("creatorContentType", "")).lower() == "shorts"]


def _topic_guidance(current: dict[str, Any], previous: dict[str, Any], top: list[dict[str, Any]]) -> list[str]:
    guidance = ["Use the channel's own strongest Short patterns as a hypothesis, not a rule."]
    if current.get("averageViewPercentage") is not None and previous.get("averageViewPercentage") is not None:
        direction = "improved" if current["averageViewPercentage"] >= previous["averageViewPercentage"] else "declined"
        guidance.append(f"Average viewed percentage {direction}; test hook clarity and payoff structure before changing niche.")
    if top:
        guidance.append("Study the top current Short's promise, pacing, and audience response; do not copy its topic, script, or footage.")
    else:
        guidance.append("No per-video Shorts row is available from this report shape; use the channel-level retention baseline with broad verified trends.")
    return guidance


def channel_analytics(settings: Settings) -> dict[str, Any]:
    """Write and return a 30-day Shorts monitor report, or a precise authorization state."""
    destination = settings.data_dir / "latest_channel_analytics.json"
    credentials = _credentials(settings)
    if credentials is None or not credentials.has_scopes(["https://www.googleapis.com/auth/yt-analytics.readonly"]):
        return _empty("needs_analytics_authorization", "Run authorize-youtube again to grant read-only YouTube Analytics access.", destination)
    current_period, previous_period = _periods(settings.analytics_days)
    try:
        analytics = build("youtubeAnalytics", "v2", credentials=credentials)
        current_rows = _query(analytics, *current_period)
        previous_rows = _query(analytics, *previous_period)
    except Exception as error:  # noqa: BLE001 - availability failures must persist without inventing values.
        return _empty("unavailable", f"Analytics query failed: {type(error).__name__}", destination)
    current, previous = _summary(current_rows), _summary(previous_rows)
    # The supported creator-content-type query is channel-level. Do not label a fabricated
    # per-video sample as an analytics result.
    top: list[dict[str, Any]] = []
    report = {
        "generated_at": datetime.now(UTC).isoformat(), "status": "ok",
        "date_basis": "YouTube Analytics reports use Pacific calendar days; current day excluded.",
        "current_period": {"start": current_period[0], "end": current_period[1], "short_rows": len(current_rows), "summary": current},
        "previous_period": {"start": previous_period[0], "end": previous_period[1], "short_rows": len(previous_rows), "summary": previous},
        "top_shorts_sample": top,
        "limitations": [
            "This supported query provides a channel-level Shorts aggregate; it does not expose per-video retention rows.",
            "Shown-in-feed and chose-to-view are Studio-specific diagnostics and are not asserted when absent from the API response.",
            "Do not infer causation or a viral forecast from a small channel's historical sample.",
        ],
        "topic_guidance": _topic_guidance(current, previous, top),
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report
