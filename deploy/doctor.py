"""python deploy/doctor.py  - shows which keys exist in .env (yes/no only, values never printed) and smoke-tests the free image + LLM providers."""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import dotenv_values, load_dotenv  # noqa: E402

KEYS = ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "GEMINI_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY", "CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN"]
have = {k for k, v in dotenv_values(ROOT / ".env").items() if v}
for k in KEYS:
    print(f"{'yes' if k in have else 'NO '}  {k}")
load_dotenv(ROOT / ".env")
from app import auto, stills  # noqa: E402

print("\nLLM providers with keys:", auto._providers() or "none")
for p in auto._providers():
    try:
        out = auto._call(p, "Reply with JSON only.", 'Return {"ok": true}')
        print(f"  {p}: works ->", out.strip()[:40])
    except Exception as e:
        print(f"  {p}: FAILED {type(e).__name__}")
try:
    f, prov = stills.generate("photoreal city at night, cinematic, no text", Path(tempfile.mkdtemp()) / "t")
    print(f"image provider: {prov} -> {f}")
except Exception as e:
    print("image: FAILED", e)
