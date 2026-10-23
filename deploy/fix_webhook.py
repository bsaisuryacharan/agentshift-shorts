"""Re-point the Telegram webhook at the Worker with a fresh secret (run on your Mac):  python3 deploy/fix_webhook.py [https://shorts-orchestrator.<you>.workers.dev]"""
import secrets, subprocess, sys, tempfile
from pathlib import Path

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
env = dotenv_values(ROOT / ".env")
url = sys.argv[1] if len(sys.argv) > 1 else "https://shorts-orchestrator.bsaisuryacharan.workers.dev"
if not url.startswith("http"):
    url = "https://" + url
sec = secrets.token_urlsafe(32)
wd = Path(tempfile.mkdtemp())
(wd / "worker.js").write_text((ROOT / "deploy" / "worker.js").read_text())
(wd / "wrangler.toml").write_text('name = "shorts-orchestrator"\nmain = "worker.js"\ncompatibility_date = "2025-01-01"\n')
subprocess.run(["npx", "--yes", "wrangler", "secret", "put", "TG_SECRET"], cwd=wd, input=sec, text=True, check=True)
r = httpx.post(f"https://api.telegram.org/bot{env['TELEGRAM_BOT_TOKEN']}/setWebhook", data={"url": url, "secret_token": sec}, timeout=30).json()
print("setWebhook:", r.get("ok"), r.get("description", ""))
print("check:", httpx.get(f"https://api.telegram.org/bot{env['TELEGRAM_BOT_TOKEN']}/getWebhookInfo", timeout=30).json()["result"].get("url"))
