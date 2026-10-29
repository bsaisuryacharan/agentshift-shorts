"""One-shot provisioning of the always-on orchestrator (run on YOUR Mac):  python deploy/provision.py [--dry-run] [--repo NAME]

What it does (keys are read from your .env / typed at a hidden prompt, passed to tools through stdin, and never printed):
  1. Builds a CLEAN staging copy of the code from an allow-list (no .env, token.json, oauth_client.json, output/, videos/, data/, logs/).
  2. Creates a PUBLIC GitHub repo (unlimited free Actions minutes) with `gh` and pushes the staging copy.
  3. Sets the repo's Actions secrets from your .env.
  4. Deploys the Cloudflare Worker with `wrangler` and sets its secrets.
  5. Points your existing Telegram bot's webhook at the Worker (stop `app.orchestrator listen` first - they can't run together).
Prereqs: `gh auth login`, `npx wrangler login`, a fine-grained GitHub token (this repo only, Contents: Read and write) for the Worker.
"""
from __future__ import annotations

import getpass
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOW = ["app", "tests", "examples", "docs", "skills", "templates", "assets", "deploy", "pyproject.toml", "README.md", "INTEGRATION.md"]
SECRET_FILES = {".env", "token.json", "oauth_client.json"}
ACTION_SECRETS = ["PEXELS_API_KEY", "PIXABAY_API_KEY", "GEMINI_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY", "CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN",
                  "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"]
DRY = "--dry-run" in sys.argv


def sh(cmd: list[str], cwd: Path | None = None, stdin: str | None = None, check: bool = True) -> subprocess.CompletedProcess:
    shown = " ".join(cmd)
    print("  $", shown if not stdin else shown + "   (value via stdin)")
    if DRY:
        return subprocess.CompletedProcess(cmd, 0, "", "")
    return subprocess.run(cmd, cwd=cwd, input=stdin, text=True, capture_output=True, check=check)


def stage(dest: Path) -> list[str]:
    """copy allow-listed paths; returns what was copied. Refuses if any secret-looking file slipped in."""
    copied = []
    for name in ALLOW:
        src = ROOT / name
        if not src.exists():
            continue
        if src.is_dir():
            skip = ["__pycache__", "*.pyc", ".env*", "token.json", "oauth_client.json", "runs", "output"] + ([] if name == "assets" else ["*.mp4"])   # assets/motion/*.mp4 is the shipped motion bank
            shutil.copytree(src, dest / name, ignore=shutil.ignore_patterns(*skip))
        else:
            shutil.copy2(src, dest / name)
        copied.append(name)
    (dest / ".gitignore").write_text(".env\n.env.*\ntoken.json\noauth_client.json\nruns/\noutput/\nvideos/\nlogs/\n__pycache__/\n*.mp4\n!assets/motion/*.mp4\n*.egg-info/\n")
    (dest / ".github" / "workflows").mkdir(parents=True, exist_ok=True)
    for wf in ("orchestrator.yml", "free-daily.yml", "weekly-insights.yml", "picker-eval.yml", "hud-test.yml", "stock-test.yml", "monitor.yml", "upload-test.yml"):
        for cand in (ROOT / "deploy" / wf, ROOT / "scripts" / wf):
            if cand.exists():
                shutil.copy2(cand, dest / ".github" / "workflows" / wf)
                break
    leaked = [str(p.relative_to(dest)) for p in dest.rglob("*") if p.is_file() and (p.name in SECRET_FILES or p.name.startswith(".env"))]
    if leaked:
        raise SystemExit(f"refusing: secret files in staging copy: {leaked}")
    return copied


def load_env() -> dict[str, str]:
    from dotenv import dotenv_values
    return {k: v for k, v in dotenv_values(ROOT / ".env").items() if v}


def main() -> int:
    repo_name = sys.argv[sys.argv.index("--repo") + 1] if "--repo" in sys.argv else "agentshift-shorts"
    env = load_env()
    missing = [k for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID") if k not in env]
    if missing:
        raise SystemExit(f"missing in .env: {missing}")
    if not any(k in env for k in ("GEMINI_API_KEY", "GROQ_API_KEY")):
        print("WARNING: no GEMINI_API_KEY or GROQ_API_KEY in .env - the writer/judge needs one (free from aistudio.google.com or console.groq.com).")
    if "CLOUDFLARE_API_TOKEN" not in env:
        print("NOTE: no CLOUDFLARE_* keys - stills will use the lower-quality keyless Pollinations fallback.")

    work = Path(tempfile.mkdtemp(prefix="shorts_stage_"))
    print("1/5 staging clean copy ->", work)
    print("   copied:", stage(work))
    print("2/5 GitHub repo (PUBLIC; the code is public, secrets are not)")
    if input(f"   create public repo '{repo_name}' under your account? [y/N] ").strip().lower() != "y":
        raise SystemExit("aborted")
    sh(["git", "init", "-q", "-b", "main"], cwd=work)
    sh(["git", "add", "-A"], cwd=work)
    sh(["git", "-c", "user.name=shorts-bot", "-c", "user.email=shorts-bot@users.noreply.github.com", "commit", "-qm", "initial: shorts factory"], cwd=work)
    sh(["gh", "repo", "create", repo_name, "--public", "--source", str(work), "--push"], cwd=work)
    who = "" if DRY else sh(["gh", "api", "user", "--jq", ".login"]).stdout.strip()
    full = f"{who}/{repo_name}"
    print("3/5 Actions secrets ->", full)
    for k in ACTION_SECRETS:
        if k in env:
            sh(["gh", "secret", "set", k, "--repo", full], stdin=env[k])
    print("4/5 Cloudflare Worker")
    wd = work / "worker"
    wd.mkdir()
    shutil.copy2(ROOT / "deploy" / "worker.js", wd / "worker.js")
    (wd / "wrangler.toml").write_text('name = "shorts-orchestrator"\nmain = "worker.js"\ncompatibility_date = "2025-01-01"\n')
    tg_secret = secrets.token_urlsafe(32)
    if DRY:
        gh_token = "DRY"
    elif "--pat" in sys.argv:
        gh_token = getpass.getpass("   paste a fine-grained GitHub token for the Worker (hidden; Contents: Read and write, this repo only): ")
    else:   # zero-paste default: reuse the token `gh auth login` already stored (broader than a fine-grained PAT; rotate later with --pat)
        gh_token = sh(["gh", "auth", "token"]).stdout.strip()
    sh(["npx", "--yes", "wrangler", "deploy"], cwd=wd)
    for k, v in {"TG_SECRET": tg_secret, "TG_TOKEN": env["TELEGRAM_BOT_TOKEN"], "ALLOWED_CHAT": env["TELEGRAM_CHAT_ID"], "GH_TOKEN": gh_token, "GH_REPO": full}.items():
        sh(["npx", "--yes", "wrangler", "secret", "put", k], cwd=wd, stdin=v)
    url = input("   Worker URL printed above (https://....workers.dev): ").strip() if not DRY else "https://example.workers.dev"
    if not DRY and not url.startswith("http"):
        url = "https://" + url.lstrip("/")
    print("5/5 Telegram webhook (stop `app.orchestrator listen` first)")
    import httpx
    if DRY:
        print("   would call setWebhook")
    else:
        r = httpx.post(f"https://api.telegram.org/bot{env['TELEGRAM_BOT_TOKEN']}/setWebhook", data={"url": url, "secret_token": tg_secret}, timeout=30)
        print("   setWebhook:", r.json().get("ok"), r.json().get("description", ""))
    print("\nDone. Message your bot /help. Actions runs: https://github.com/" + full + "/actions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
