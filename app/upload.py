"""Opt-in YouTube upload, triggered only by the owner's /upload command in Telegram (never automatically).

The approved Short's video is taken from the workflow artifact of the run that made it, uploaded as PRIVATE with a scheduled publish time
(next 19:00 IST at least 45 minutes ahead), with the title/description/tags from the upload pack and the synthetic-media disclosure set.
Needs the YOUTUBE_TOKEN_JSON secret (OAuth token that includes the youtube.upload scope). Unaudited API projects may force uploads to stay private:
the result message says what YouTube reports.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
IST = timedelta(hours=5, minutes=30)


class UploadError(Exception):
    pass


def next_slot(now: datetime | None = None, hour_ist: int = 19, lead_min: int = 45) -> datetime:
    """the next hour_ist:00 IST that is at least lead_min minutes away, as an aware UTC datetime"""
    now = now or datetime.now(UTC)
    ist_now = now + IST
    slot = ist_now.replace(hour=hour_ist, minute=0, second=0, microsecond=0)
    if slot - ist_now < timedelta(minutes=lead_min):
        slot += timedelta(days=1)
    return (slot - IST).replace(tzinfo=UTC) if slot.tzinfo is None else slot - IST


def credentials():
    raw = os.environ.get("YOUTUBE_TOKEN_JSON")
    if not raw:
        raise UploadError("The YOUTUBE_TOKEN_JSON secret is not set.")
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    info = json.loads(raw)
    creds = Credentials.from_authorized_user_info(info)
    if not creds.has_scopes([UPLOAD_SCOPE]):
        raise UploadError("The stored YouTube login does not include permission to upload. Re-authorize once on your Mac "
                          "(python3 -m app.main authorize-youtube, which asks for upload + analytics) and update the YOUTUBE_TOKEN_JSON secret.")
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return creds


def fetch_video(run_id: str, spec_id: str) -> Path:
    """download the approved Short from the workflow artifact of the run that produced it (kept 90 days)"""
    d = Path(tempfile.mkdtemp())
    p = subprocess.run(["gh", "run", "download", str(run_id), "-n", "run", "-D", str(d)], capture_output=True, text=True)
    if p.returncode != 0:
        raise UploadError(f"could not download the video artifact of run {run_id}: {p.stderr.strip()[:200]}")
    for cand in (d / spec_id / "telegram.mp4", *d.rglob("telegram.mp4")):
        if cand.exists():
            return cand
    raise UploadError("the run's artifact has no telegram.mp4")


def upload(video: Path, parts: dict, publish_at: datetime) -> dict:
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload
    youtube = build("youtube", "v3", credentials=credentials())
    body = {"snippet": {"title": parts["title"][:100], "description": parts["description"][:4900], "tags": parts["tags"], "categoryId": "28"},
            "status": {"privacyStatus": "private", "publishAt": publish_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                       "selfDeclaredMadeForKids": False, "containsSyntheticMedia": True}}
    try:
        res = youtube.videos().insert(part="snippet,status", body=body, media_body=MediaFileUpload(str(video), resumable=True, mimetype="video/mp4")).execute()
    except HttpError as e:
        reason = ""
        try:
            reason = json.loads(e.content).get("error", {}).get("errors", [{}])[0].get("reason", "")
        except (ValueError, AttributeError):
            pass
        raise UploadError(f"YouTube refused the upload ({e.resp.status} {reason or 'error'}). "
                          + ("The daily upload quota is used up; try tomorrow." if reason in ("quotaExceeded", "uploadLimitExceeded") else ""))
    st = res.get("status", {})
    return {"id": res["id"], "url": f"https://youtube.com/watch?v={res['id']}", "privacy": st.get("privacyStatus"), "publish_at": st.get("publishAt") or body["status"]["publishAt"]}
