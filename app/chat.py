"""Telegram chat layer: the owner talks to Claude (Claude Code, running in .github/workflows/chat.yml) in plain language.

Claude can explain the system, act as go-between with the judge and the orchestrator, start runs, and change the system itself (code, prompts,
flow, thresholds), always under the rules in docs/AGENT.md (tests before every commit, free tier, no secrets in replies).

    python -m app.chat control "<text>"     # /model, /effort, /reset, /settings: answered without calling Claude; exit 0 = handled, 1 = not a control
    python -m app.chat prompt "<text>"      # writes chat_prompt.txt (recent conversation + live system status + the new message) and chat_args.txt
    python -m app.chat finish result.json   # sends Claude's answer to Telegram and stores the turn in state/chat/<chat>.jsonl

Settings and memory live in the repo (state/chat/), so they survive between runs. Model and effort are the owner's choice per chat.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
DIR = ROOT / "state" / "chat"
MODELS = {"opus": "opus", "sonnet": "sonnet", "haiku": "haiku"}            # Claude Code aliases: always the latest model of each family
EFFORTS = ("low", "medium", "high", "xhigh", "max")
DEFAULT = {"model": "sonnet", "effort": "medium"}
KEEP_TURNS = 12


def _chat() -> str:
    return str(os.environ.get("CHAT") or os.environ.get("TELEGRAM_CHAT_ID") or "owner")


def settings(chat: str | None = None) -> dict:
    try:
        return {**DEFAULT, **json.loads((DIR / f"{chat or _chat()}.settings.json").read_text())}
    except (OSError, ValueError):
        return dict(DEFAULT)


def save_settings(s: dict, chat: str | None = None) -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    (DIR / f"{chat or _chat()}.settings.json").write_text(json.dumps(s, indent=1))


def history(chat: str | None = None, n: int = KEEP_TURNS) -> list[dict]:
    p = DIR / f"{chat or _chat()}.jsonl"
    if not p.exists():
        return []
    rows = []
    for line in p.read_text().splitlines()[-n:]:
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def remember(user: str, reply: str, meta: dict | None = None, chat: str | None = None) -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    with open(DIR / f"{chat or _chat()}.jsonl", "a") as f:
        f.write(json.dumps({"ts": datetime.now(UTC).isoformat(timespec="seconds"), "user": user[:4000], "reply": reply[:6000], **(meta or {})},
                           ensure_ascii=False) + "\n")


def send(text: str, chat: str | None = None) -> None:
    tok = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not tok:
        print("[chat] no TELEGRAM_BOT_TOKEN; reply:\n" + text)
        return
    for i in range(0, max(len(text), 1), 3900):                        # Telegram's limit is 4096 characters per message
        httpx.post(f"https://api.telegram.org/bot{tok}/sendMessage", data={"chat_id": chat or _chat(), "text": text[i:i + 3900] or "(empty)"}, timeout=60)


def control(text: str) -> str | None:
    """the owner's controls; returns the reply, or None when the text is not a control"""
    t = text.strip()
    cmd, _, arg = t.partition(" ")
    cmd, arg = cmd.lower().split("@")[0], arg.strip().lower()
    s = settings()
    if cmd == "/model":
        if arg not in MODELS:
            return f"Model now: {s['model']}. Choose one: /model opus (best, slowest), /model sonnet (balanced), /model haiku (fastest)."
        s["model"] = arg
        save_settings(s)
        return f"Model set to {arg}. Effort: {s['effort']}."
    if cmd == "/effort":
        if arg not in EFFORTS:
            return f"Effort now: {s['effort']}. Choose one: " + ", ".join(f"/effort {e}" for e in EFFORTS) + " (higher = more thorough and slower)."
        s["effort"] = arg
        save_settings(s)
        return f"Effort set to {arg}. Model: {s['model']}."
    if cmd in ("/settings", "/claude"):
        return (f"Claude chat: model {s['model']}, effort {s['effort']}, {len(history())} recent turns remembered. Change with /model, /effort; "
                "/reset forgets the conversation; /changes lists Claude's proposed code changes, /merge makes one live, /discard drops it.")
    if cmd in ("/merge", "/discard", "/changes"):
        return pr_control(cmd, arg)
    if cmd == "/reset":
        p = DIR / f"{_chat()}.jsonl"
        if p.exists():
            p.rename(p.with_suffix(f".{datetime.now(UTC):%Y%m%d%H%M%S}.old"))
        return "Conversation memory cleared (settings kept)."
    return None


def _gh(*args: str) -> str:
    import subprocess
    p = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=120)
    return (p.stdout or p.stderr).strip()


def pr_control(cmd: str, arg: str) -> str:
    """the owner's gate on Claude's code changes: /changes lists them, /merge makes the newest (or #n) live, /discard closes it. Plain code, no LLM."""
    try:
        prs = json.loads(_gh("pr", "list", "--state", "open", "--json", "number,title,headRefName,url") or "[]")
    except ValueError:
        return "Could not read the open changes from GitHub."
    prs = [p for p in prs if p["headRefName"].startswith("chat/")]
    if cmd == "/changes" or not prs:
        return "\n".join(f"#{p['number']} {p['title']} {p['url']}" for p in prs) or "No pending changes from Claude."
    pick = next((p for p in prs if arg.lstrip("#") == str(p["number"])), prs[0])
    if cmd == "/merge":
        out = _gh("pr", "merge", str(pick["number"]), "--squash", "--delete-branch")
        return f"Merged #{pick['number']} ({pick['title']}): it is live from the next run. {out[:200]}"
    out = _gh("pr", "close", str(pick["number"]), "--delete-branch")
    return f"Discarded #{pick['number']} ({pick['title']}). {out[:200]}"


def status_block() -> str:
    """a compact picture of the live system for Claude: current Short, recent runs, what the judge keeps saying, performance"""
    out = []
    try:
        st = json.loads((ROOT / "state" / f"{_chat()}.json").read_text())
        cur = st.get("current")
        p = (st.get("projects") or {}).get(cur) or {}
        out.append(f"Current Short: {cur} - '{p.get('title', '')}' status={p.get('status')} uploaded={bool(p.get('uploaded'))}")
    except (OSError, ValueError):
        out.append("Current Short: none")
    try:
        rows = (ROOT / "data" / "topics.jsonl").read_text().splitlines()[-6:]
        out.append("Recent topic ledger: " + " | ".join(f"{r.get('date')} {r.get('outcome')} {r.get('wiki')}" for r in map(json.loads, rows)))
    except (OSError, ValueError):
        pass
    try:
        from . import lessons
        rules = lessons.rules()
        if rules:
            out.append("Recurring judge complaints: " + " | ".join(r[:110] for r in rules[:4]))
    except Exception:
        pass
    try:
        perf = json.loads((ROOT / "assets" / "insights.json").read_text()).get("performance") or {}
        if perf.get("shorts"):
            out.append(f"Performance: {len(perf['shorts'])} uploaded Shorts, best {perf.get('best')}")
    except (OSError, ValueError):
        pass
    return "\n".join(out)


def build_prompt(text: str) -> str:
    convo = "\n".join(f"OWNER: {h['user']}\nYOU: {h['reply'][:1500]}" for h in history())
    return (f"LIVE SYSTEM STATUS (read from the repo just now):\n{status_block()}\n\n"
            f"RECENT CONVERSATION WITH THE OWNER (oldest first):\n{convo or '(none yet)'}\n\n"
            f"NEW MESSAGE FROM THE OWNER (Telegram):\n{text}\n\n"
            "Answer the owner. Your final message is sent to Telegram as-is: plain text, short, no markdown tables.")


def finish(result_path: Path, text: str) -> int:
    try:
        r = json.loads(result_path.read_text())
        reply = (r.get("result") or "").strip() or "(Claude returned no answer.)"
        meta = {"model": settings()["model"], "effort": settings()["effort"], "turns": r.get("num_turns"), "cost_usd": r.get("total_cost_usd"),
                "error": r.get("is_error")}
    except (OSError, ValueError):
        reply, meta = "Claude did not finish (no result). Try again, or a lower effort for a quick answer.", {"error": True}
    send(reply)
    remember(text, reply, meta)
    return 0


if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0] == "control":
        msg = control(a[1] if len(a) > 1 else "")
        if msg is None:
            raise SystemExit(1)
        send(msg)
        raise SystemExit(0)
    if a and a[0] == "prompt":
        s = settings()
        (ROOT / "chat_prompt.txt").write_text(build_prompt(a[1] if len(a) > 1 else ""))
        (ROOT / "chat_args.txt").write_text(f"{MODELS[s['model']]} {s['effort']}")
        send(f"Thinking ({s['model']}, effort {s['effort']})...")
        raise SystemExit(0)
    if a and a[0] == "finish":
        raise SystemExit(finish(Path(a[1]), a[2] if len(a) > 2 else ""))
    raise SystemExit(__doc__)
