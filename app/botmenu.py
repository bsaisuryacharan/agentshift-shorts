"""Register the bot's slash-command menu with Telegram (setMyCommands), so typing "/" in the chat lists the commands.

    python -m app.botmenu        # idempotent; runs at the start of every cloud job, needs TELEGRAM_BOT_TOKEN
"""
from __future__ import annotations

import os
import sys

import httpx

COMMANDS = [
    ("new", "Make a Short about a topic: /new <topic>"),
    ("status", "Current Short and its scores"),
    ("list", "Recent Shorts"),
    ("use", "Switch to a Short: /use <id>"),
    ("approve", "Title + description + credits for the current Short"),
    ("help", "What the bot can do"),
]


def register(token: str | None = None) -> bool:
    token = token or os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        print("[botmenu] TELEGRAM_BOT_TOKEN not set; skipped")
        return False
    body = {"commands": [{"command": c, "description": d[:256]} for c, d in COMMANDS]}
    try:
        r = httpx.post(f"https://api.telegram.org/bot{token}/setMyCommands", json=body, timeout=30)
    except httpx.HTTPError as e:
        print(f"[botmenu] failed: {e!r}")
        return False
    ok = r.status_code == 200 and r.json().get("ok") is True
    print("[botmenu]", "registered" if ok else f"failed: HTTP {r.status_code}")
    return ok


if __name__ == "__main__":
    sys.exit(0 if register() else 1)
