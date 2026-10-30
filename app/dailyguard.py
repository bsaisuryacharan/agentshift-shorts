"""Stops duplicate Short runs: two taps on a button, a late scheduled slot next to a manual run, or the Cloudflare cron next to GitHub's own schedule.

    python -m app.dailyguard         # exit 0 = skip this run (another free-daily run started in the last 25 minutes, or today's Shorts are done)

Reads the recent runs of this workflow through the GitHub API (GH_TOKEN, GITHUB_REPOSITORY, GITHUB_RUN_ID, GITHUB_EVENT_NAME). A manual run with an
explicit topic is never skipped for being a duplicate of a scheduled one, only for being a repeat of the same request.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime

WINDOW_S = 25 * 60
ACTIVE = ("queued", "in_progress", "waiting", "pending", "requested")


def duplicate(runs: list[dict], my_id: int, now: datetime | None = None, window: int = WINDOW_S, manual: bool = False) -> dict | None:
    """an earlier run of this workflow that is active, or (not for a manual run: the owner may ask again) finished successfully, within the window"""
    now = now or datetime.now(UTC)
    for r in sorted(runs, key=lambda r: r["id"]):
        if r["id"] >= my_id:
            continue
        age = (now - datetime.fromisoformat(r["created_at"].replace("Z", "+00:00"))).total_seconds()
        if age > window:
            continue
        if r["status"] in ACTIVE or (not manual and r.get("conclusion") == "success"):
            return r
    return None


def main() -> int:
    from . import auto
    event, topic = os.environ.get("GITHUB_EVENT_NAME", ""), os.environ.get("TOPIC", "").strip()
    if event in ("schedule", "repository_dispatch") and auto.delivered_today():
        print("today's Shorts are already delivered")
        return 0
    repo, my_id = os.environ.get("GITHUB_REPOSITORY"), int(os.environ.get("GITHUB_RUN_ID", "0") or 0)
    if not repo or not my_id:
        return 1
    try:
        out = subprocess.run(["gh", "api", f"repos/{repo}/actions/workflows/free-daily.yml/runs?per_page=10"], capture_output=True, text=True, timeout=60, check=True).stdout
        dup = duplicate(json.loads(out).get("workflow_runs", []), my_id, manual=event == "workflow_dispatch")
    except (subprocess.SubprocessError, ValueError, OSError) as e:
        print("guard could not read the runs; continuing:", type(e).__name__)
        return 1
    if dup and not (topic and dup.get("event") != "workflow_dispatch"):
        print(f"another run (#{dup['id']}, {dup['event']}, {dup['status']}) started {dup['created_at']}: skipping this one")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
