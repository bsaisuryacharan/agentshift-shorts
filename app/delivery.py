from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from .models import Script
from .providers import ProviderError
from .settings import Settings

YOUTUBE_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]


def authorize_youtube(settings: Settings) -> None:
    if not settings.youtube_client_secrets_file.exists():
        raise ProviderError(f"Missing OAuth client: {settings.youtube_client_secrets_file}")
    flow = InstalledAppFlow.from_client_secrets_file(str(settings.youtube_client_secrets_file), YOUTUBE_SCOPES)
    credentials = flow.run_local_server(port=0)
    settings.youtube_token_file.write_text(credentials.to_json(), encoding="utf-8")


def telegram(settings: Settings, video: Path, script: Script, review_notes: str) -> None:
    if not (settings.telegram_bot_token and settings.telegram_chat_id):
        raise ProviderError("Telegram credentials missing.")
    caption = f"APPROVED SHORT\n\n{script.title}\n\n{script.description[:700]}\n\nReview: {review_notes[:250]}"
    response = httpx.post(f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendVideo",
                          data={"chat_id": settings.telegram_chat_id, "caption": caption},
                          files={"video": (video.name, video.open("rb"), "video/mp4")}, timeout=120)
    response.raise_for_status()
    if not response.json().get("ok"):
        raise ProviderError("Telegram rejected delivery.")


def discover_telegram_chat_id(settings: Settings) -> str:
    """Return the most recent private/group chat that contacted this bot; never print its token."""
    if not settings.telegram_bot_token:
        raise ProviderError("TELEGRAM_BOT_TOKEN is required to discover a chat ID.")
    response = httpx.get(
        f"https://api.telegram.org/bot{settings.telegram_bot_token}/getUpdates", timeout=30
    )
    response.raise_for_status()
    updates = response.json().get("result", [])
    for update in reversed(updates):
        chat = update.get("message", {}).get("chat") or update.get("channel_post", {}).get("chat")
        if chat and chat.get("id") is not None:
            return str(chat["id"])
    raise ProviderError("No chat found. Open the bot in Telegram, send /start, then run this command again.")


def publish_youtube(settings: Settings, video: Path, script: Script) -> str:
    if not settings.youtube_token_file.exists():
        raise ProviderError("YouTube OAuth token missing.")
    credentials = Credentials.from_authorized_user_file(str(settings.youtube_token_file), YOUTUBE_SCOPES)
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
        settings.youtube_token_file.write_text(credentials.to_json(), encoding="utf-8")
    youtube = build("youtube", "v3", credentials=credentials)
    publish_at = datetime.now(UTC) + timedelta(hours=24)
    body = {"snippet": {"title": script.title, "description": script.description, "categoryId": "27"},
            "status": {"privacyStatus": "private", "publishAt": publish_at.isoformat().replace("+00:00", "Z"),
                       "selfDeclaredMadeForKids": False, "containsSyntheticMedia": True}}
    request = youtube.videos().insert(part="snippet,status", body=body,
                                      media_body=MediaFileUpload(str(video), resumable=True))
    response = request.execute()
    return f"https://youtube.com/watch?v={response['id']}"
