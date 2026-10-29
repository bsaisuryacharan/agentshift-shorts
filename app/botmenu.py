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
    ("target", "Progress towards the 1M-view target and monetisation"),
    ("list", "Recent Shorts"),
    ("use", "Switch to a Short: /use <id>"),
    ("approve", "Approve the Short: it is uploaded to YouTube publicly"),
    ("upload", "Retry the YouTube upload of the approved Short"),
    ("model", "Claude model: /model opus | sonnet | haiku"),
    ("effort", "Claude effort: /effort low | medium | high | xhigh | max"),
    ("changes", "Claude's proposed code changes"),
    ("merge", "Make Claude's newest change live"),
    ("discard", "Drop Claude's newest change"),
    ("settings", "Claude chat settings"),
    ("reset", "Clear the conversation with Claude"),
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
