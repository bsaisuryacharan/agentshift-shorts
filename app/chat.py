"""Telegram chat layer: the owner talks to Claude (Claude Code, running in .github/workflows/chat.yml) in plain language.

Claude can explain the system, act as go-between with the judge and the orchestrator, start runs, and change the system itself (code, prompts,
flow, thresholds), always under the rules in docs/AGENT.md (tests before every commit, free tier, no secrets in replies).

    python -m app.chat control "<text>"     # /model, /effort, /reset, /settings: answered without calling Claude; exit 0 = handled, 1 = not a control
    python -m app.chat prompt "<text>"      # writes chat_prompt.txt (recent conversation + live system status + the new message) and chat_args.txt
    python -m app.chat stream "<text>"      # runs Claude with live progress (one Telegram message edited step by step), then the answer
    python -m app.chat finish result.json   # sends Claude's answer to Telegram and stores the turn in state/chat/<chat>.jsonl

Settings and memory live in the repo (state/chat/), so they survive between runs. Model and effort are the owner's choice per chat.
"""
from __future__ import annotations

import json
import re
import os
import sys
import time
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


def _tg(method: str, **data) -> dict:
    tok = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not tok:
        print(f"[chat] {method}:", str(data.get("text", ""))[:300])
        return {}
    try:
        r = httpx.post(f"https://api.telegram.org/bot{tok}/{method}", json=data, timeout=60)
        out = r.json()
    except (httpx.HTTPError, ValueError) as e:
        print(f"[chat] {method} failed: {e!r}", flush=True)
        return {}
    if not out.get("ok"):
        print(f"[chat] {method} refused: {str(out.get('description'))[:200]}", flush=True)
    return out


def keyboard(rows: list[list[tuple[str, str]]] | None) -> dict | None:
    """[[(label, callback_data), ...], ...] -> Telegram inline keyboard (callback_data is cut to Telegram's 64 bytes)"""
    if not rows:
        return None
    return {"inline_keyboard": [[{"text": lab[:40], "callback_data": data.encode()[:64].decode(errors="ignore")} for lab, data in row] for row in rows]}


def send(text: str, chat: str | None = None, buttons: list | None = None, edit: str | None = None) -> int | None:
    """send (or, with edit=message id, replace) a message; long text is split; buttons go on the last part. Returns the message id."""
    chat = chat or _chat()
    parts = [text[i:i + 3900] for i in range(0, max(len(text), 1), 3900)] or ["(empty)"]
    mid = None
    for n, part in enumerate(parts):
        extra = {"reply_markup": keyboard(buttons)} if buttons and n == len(parts) - 1 else {}
        if edit and n == 0:
            out = _tg("editMessageText", chat_id=chat, message_id=int(edit), text=part or "(empty)", **extra)
            if out.get("ok"):
                mid = int(edit)
                continue
        out = _tg("sendMessage", chat_id=chat, text=part or "(empty)", **extra)
        mid = (out.get("result") or {}).get("message_id", mid)
    return mid


def control_buttons(text: str) -> list | None:
    """the tap-to-choose keyboards for the owner's controls (current choice marked ✓)"""
    cmd = text.strip().split(" ")[0].lower().split("@")[0]
    s = settings()
    mark = lambda cur, v: ("✓ " if cur == v else "") + v
    models = [[(mark(s["model"], m), f"cmd:/model {m}") for m in MODELS]]
    efforts = [[(mark(s["effort"], e), f"cmd:/effort {e}") for e in EFFORTS[:3]], [(mark(s["effort"], e), f"cmd:/effort {e}") for e in EFFORTS[3:]]]
    if cmd == "/model":
        return models
    if cmd == "/effort":
        return efforts
    if cmd in ("/settings", "/claude"):
        return models + efforts + [[("Show memory", "cmd:/memory"), ("Recent actions", "cmd:/actions")], [("Forget the conversation", "cmd:/reset")]]
    if cmd == "/memory":
        return [[("Recent actions", "cmd:/actions"), ("Settings", "cmd:/settings")]]
    if cmd == "/changes":
        try:
            prs = [p for p in json.loads(_gh("pr", "list", "--state", "open", "--json", "number,title,headRefName") or "[]") if p["headRefName"].startswith("chat/")]
        except ValueError:
            return None
        return [[(f"Merge #{p['number']}", f"cmd:/merge {p['number']}"), (f"Discard #{p['number']}", f"cmd:/discard {p['number']}")] for p in prs[:6]] or None
    return None


BUTTON_LINE = re.compile(r"^\s*BUTTONS:\s*(.+)$", re.M)


def split_buttons(reply: str) -> tuple[str, list | None]:
    """Claude may end a reply with  BUTTONS: Yes, post it | Not now  -> the owner taps one instead of typing (the tap comes back as their message)"""
    m = BUTTON_LINE.search(reply)
    if not m:
        return reply, None
    opts = [o.strip() for o in m.group(1).split("|") if o.strip()][:4]
    return BUTTON_LINE.sub("", reply).strip(), [[(o, f"say:{o}") for o in opts]] if opts else None


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
    if cmd == "/memory":
        return "What I remember long-term:\n\n" + (memory() or "(nothing yet)") + "\n\nTell me \"forget …\" or \"remember …\" to change it."
    if cmd == "/actions":
        return "Recent actions (automatic log):\n" + ("\n".join(f"{a['ts'][5:16]} {a['what']}" for a in actions(20)) or "(none yet)")
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
        log_action(f"Owner merged #{pick['number']}", pick["title"])
        return f"Merged #{pick['number']} ({pick['title']}): it is live from the next run. {out[:200]}"
    out = _gh("pr", "close", str(pick["number"]), "--delete-branch")
    log_action(f"Owner discarded #{pick['number']}", pick["title"])
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
        from . import insights
        perf = insights.load().get("performance") or {}
        if perf.get("shorts"):
            out.append(f"Performance: {len(perf['shorts'])} uploaded Shorts, best {perf.get('best')}")
    except (OSError, ValueError):
        pass
    return "\n".join(out)


MEMORY = "memory.md"              # long-term memory: decisions, owner's rules, changes made, open items (Claude keeps it current)
ACTIONS = "actions.jsonl"         # what was actually done (written by code, not by Claude): commands run, runs started, PRs opened/merged
SYSTEM_ACTIONS = ("app.orchestrator handle", "gh workflow run", "dispatches", "gh pr create", "git push -u origin chat/")
MEMORY_MAX = 8000


def memory() -> str:
    try:
        t = (DIR / MEMORY).read_text()
    except OSError:
        return ""
    return t if len(t) <= MEMORY_MAX else "…(older part trimmed; keep the file short)\n" + t[-MEMORY_MAX:]


def log_action(what: str, detail: str = "") -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    with open(DIR / ACTIONS, "a") as f:
        f.write(json.dumps({"ts": datetime.now(UTC).isoformat(timespec="seconds"), "what": what, "detail": detail[:300]}, ensure_ascii=False) + "\n")


def actions(n: int = 15) -> list[dict]:
    p = DIR / ACTIONS
    if not p.exists():
        return []
    out = []
    for line in p.read_text().splitlines()[-n:]:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def build_prompt(text: str) -> str:
    convo = "\n".join(f"OWNER: {h['user']}\nYOU: {h['reply'][:1500]}" for h in history())
    acts = "\n".join(f"{a['ts'][:16]} {a['what']}" + (f" - {a['detail']}" if a.get("detail") else "") for a in actions())
    return (f"YOUR LONG-TERM MEMORY (state/chat/{MEMORY}; update it as docs/AGENT.md says):\n{memory() or '(empty)'}\n\n"
            f"WHAT WAS ACTUALLY DONE RECENTLY (automatic log, newest last):\n{acts or '(nothing yet)'}\n\n"
            f"LIVE SYSTEM STATUS (read from the repo just now):\n{status_block()}\n\n"
            f"RECENT CONVERSATION WITH THE OWNER (oldest first):\n{convo or '(none yet)'}\n\n"
            f"NEW MESSAGE FROM THE OWNER (Telegram):\n{text}\n\n"
            "Answer the owner. Your final message is sent to Telegram as-is: plain text, short, no markdown tables.")


def finish(result_path: Path, text: str) -> int:
    try:
        r = json.loads(result_path.read_text())
        reply = (r.get("result") or "").strip() or "(Claude returned no answer.)"
        if auth_refused(reply):
            reply = ("Claude could not log in (the stored token was refused). Create a new one with `claude setup-token` on the Mac, copy it as ONE line, "
                     "and save it with: pbpaste | gh secret set CLAUDE_CODE_OAUTH_TOKEN -R bsaisuryacharan/agentshift-shorts")
        meta = {"model": settings()["model"], "effort": settings()["effort"], "turns": r.get("num_turns"), "cost_usd": r.get("total_cost_usd"),
                "error": r.get("is_error")}
    except (OSError, ValueError):
        reply, meta = "Claude did not finish (no result). Try again, or a lower effort for a quick answer.", {"error": True}
    body, buttons = split_buttons(reply)
    send(body, buttons=buttons)
    remember(text, body, meta)
    return 0


ALLOWED = ["Read", "Grep", "Glob", "Edit", "Write",
           "Bash(python -m pytest:*)", "Bash(git status:*)", "Bash(git diff:*)", "Bash(git log:*)", "Bash(git switch -c chat/:*)",
           "Bash(git add:*)", "Bash(git commit:*)", "Bash(git push -u origin chat/:*)", "Bash(gh pr create:*)",
           "Bash(gh run list:*)", "Bash(gh run view:*)", "Bash(grep:*)", "Bash(ls:*)",
           "Bash(python -m app.orchestrator handle:*)",                                   # /status /list /target /use /approve /upload, answered in Telegram
           "Bash(gh workflow run free-daily.yml:*)", "Bash(gh workflow run stage-check.yml:*)", "Bash(gh workflow run weekly-insights.yml:*)",
           "Bash(gh api repos/bsaisuryacharan/agentshift-shorts/dispatches:*)"]          # /new <topic> or a revision -> the orchestrator job (render)
DISALLOWED = ["Bash(git push origin main:*)", "Bash(git push --force:*)", "WebFetch"]


def describe(tool: str, inp: dict) -> str:
    """one plain-language progress line for a tool call ('Reading app/auto.py', 'Running the tests')"""
    f = lambda k: str(inp.get(k, "")).replace(str(ROOT) + "/", "")
    if tool == "Read":
        return f"Reading {f('file_path')}"
    if tool in ("Edit", "MultiEdit"):
        return f"Editing {f('file_path')}"
    if tool == "Write":
        return f"Writing {f('file_path')}"
    if tool == "Grep":
        return f"Searching the code for '{f('pattern')[:40]}'"
    if tool == "Glob":
        return f"Listing files {f('pattern')[:40]}"
    if tool == "Bash":
        c = f("command")
        if "app.orchestrator handle" in c:
            import re as _re
            m = _re.search(r'--text\s+["\']?(/?\w+)', c)
            return f"Asking the orchestrator: {m.group(1) if m else 'command'}"
        for key, text in (("pytest", "Running the tests"), ("gh workflow run free-daily", "Starting a new Short (full pipeline)"),
                          ("gh workflow run stage-check", "Starting a step test"), ("dispatches", "Handing the job to the orchestrator"), ("gh run view", "Reading a run's log"), ("gh run list", "Checking recent runs"),
                          ("git switch", "Starting a change branch"), ("git commit", "Committing the change"), ("git push", "Pushing the change"),
                          ("gh pr create", "Opening the pull request"), ("git diff", "Reviewing the diff"), ("git log", "Reading the history")):
            if key in c:
                return text
        return f"Running: {c[:60]}"
    if tool in ("TodoWrite", "Task"):
        return "Planning the steps"
    return f"Using {tool}"


def summarize_result(tool: str, cmd: str, content, is_error: bool = False) -> str:
    """a few words on what a tool call found ('182 passed', '6 matches', '120 lines'), shown after its step"""
    text = content if isinstance(content, str) else " ".join(str(c.get("text", "")) for c in content or [] if isinstance(c, dict))
    text = text.strip()
    if is_error:
        return "⚠ " + (text.splitlines()[0][:70] if text else "error")
    if "pytest" in cmd:
        m = re.search(r"(\d+ failed)?[, ]*(\d+ passed)", text)
        return ", ".join(x for x in (m.group(1), m.group(2)) if x) if m else (text.splitlines()[-1][:60] if text else "done")
    lines = [x for x in text.splitlines() if x.strip()]
    if tool == "Grep" or cmd.startswith("grep"):
        return f"{len(lines)} match{'es' if len(lines) != 1 else ''}" if lines else "no matches"
    if tool == "Read":
        return f"{len(lines)} lines"
    if tool == "Glob":
        return f"{len(lines)} files"
    if "gh run list" in cmd:
        return f"{len(lines)} runs"
    if "gh pr create" in cmd:
        m = re.search(r"https://\S+/pull/\d+", text)
        return m.group(0) if m else "opened"
    if tool in ("Edit", "Write", "MultiEdit"):
        return "saved"
    return (lines[0][:60] + ("…" if len(lines[0]) > 60 else "")) if lines else "done"


class Progress:
    """one Telegram message, edited as Claude works: its thinking (live), each step with what it found, and a live preview of the answer"""

    def __init__(self, query: str, header: str, chat: str | None = None, min_gap: float = 2.0):
        self.chat, self.min_gap, self.t0, self.last = chat or _chat(), min_gap, time.time(), 0.0
        self.head = f"{header}\n❓ {query[:200]}"
        self.steps: list[str] = []                      # step text
        self.found: dict[int, str] = {}                 # step index -> what it found
        self.ids: dict[str, int] = {}                   # tool_use_id -> step index
        self.tools: dict[str, tuple[str, str]] = {}     # tool_use_id -> (tool, command)
        self.note = ""                                   # latest thinking / narration
        self.draft = ""                                  # the answer being written
        status = os.environ.get("STATUS", "").strip()   # the Worker already posted "reading your message…": take it over
        self.mid = int(status) if status.isdigit() else None
        if self.mid:
            self._edit(force=True)
        else:
            self.mid = self._post()

    def _text(self, done: bool = False) -> str:
        out = [self.head]
        if self.note and not done:
            out.append("🧠 " + self.note)
        if self.steps:
            shown = list(enumerate(self.steps))[-10:]
            rows = []
            for i, st in shown:
                mark = "✓" if (done or i < len(self.steps) - 1 or i in self.found) else "…"
                rows.append(f"{mark} {st}" + (f" → {self.found[i]}" if i in self.found else ""))
            more = f"(+{len(self.steps) - 10} earlier steps)\n" if len(self.steps) > 10 else ""
            out.append("🔧 Steps\n" + more + "\n".join(rows))
        if self.draft and not done:
            out.append("✍️ Writing the answer…\n" + ("…" if len(self.draft) > 300 else "") + self.draft[-300:])
        if not self.steps and not self.note and not self.draft:
            out.append("… starting")
        n = len(self.steps)
        out.append(f"⏱ {int(time.time() - self.t0)} s · {n} step{'s' if n != 1 else ''}")
        return "\n\n".join(out)

    def _post(self) -> int | None:
        return (_tg("sendMessage", chat_id=self.chat, text=self._text()).get("result") or {}).get("message_id")

    def _edit(self, done: bool = False, force: bool = False) -> None:
        if not force and time.time() - self.last < self.min_gap:
            return
        self.last = time.time()
        if not self.mid:
            print("[progress]", self._text(done).splitlines()[-3:])
            return
        _tg("editMessageText", chat_id=self.chat, message_id=self.mid, text=self._text(done)[:4000])

    def step(self, line: str, tool_id: str = "", tool: str = "", cmd: str = "") -> None:
        self.draft = ""                                  # text before a tool call was narration, not the answer
        self.steps.append(line)
        if tool_id:
            self.ids[tool_id], self.tools[tool_id] = len(self.steps) - 1, (tool, cmd)
        self._edit()

    def result(self, tool_id: str, content, is_error: bool = False) -> None:
        if tool_id in self.ids:
            tool, cmd = self.tools[tool_id]
            self.found[self.ids[tool_id]] = summarize_result(tool, cmd, content, is_error)
            self._edit()

    def thought(self, text: str) -> None:
        t = " ".join(text.split())
        if t:
            self.note = ("…" if len(t) > 400 else "") + t[-400:]
            self._edit()

    def writing(self, delta: str) -> None:
        self.draft += delta
        self._edit()

    def done(self, summary: str) -> None:
        self.head += f"\n{summary}"
        self._edit(done=True, force=True)


def handle_event(ev: dict, prog: Progress) -> dict | None:
    """feed one stream-json event to the progress message; returns the final result event.
    Whole messages: thinking, narration, tool calls (assistant) and tool results (user). Partial messages (stream_event): live thinking and answer text."""
    t = ev.get("type")
    if t == "stream_event":
        e = ev.get("event") or {}
        d = e.get("delta") or {}
        if e.get("type") == "content_block_delta":
            if d.get("type") == "thinking_delta":
                prog.thought(prog.note.lstrip("…") + d.get("thinking", ""))
            elif d.get("type") == "text_delta":
                prog.writing(d.get("text", ""))
    elif t == "assistant":
        for c in (ev.get("message") or {}).get("content") or []:
            if c.get("type") == "tool_use":
                inp = c.get("input") or {}
                line = describe(c.get("name", ""), inp)
                cmd = str(inp.get("command", ""))
                prog.step(line, c.get("id", ""), c.get("name", ""), cmd)
                if c.get("name") == "Bash" and any(k in cmd for k in SYSTEM_ACTIONS):
                    log_action(line, cmd)
            elif c.get("type") == "thinking" and c.get("thinking"):
                prog.thought(c["thinking"])
            elif c.get("type") == "text" and not prog.draft:
                prog.thought(c.get("text", ""))
    elif t == "user":
        for c in (ev.get("message") or {}).get("content") or []:
            if isinstance(c, dict) and c.get("type") == "tool_result":
                prog.result(c.get("tool_use_id", ""), c.get("content"), bool(c.get("is_error")))
    elif t == "result":
        return ev
    return None


def auth_order() -> list[dict]:
    tok = "".join(os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "").split())
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    return [a for a in ({"CLAUDE_CODE_OAUTH_TOKEN": tok} if tok else None, {"ANTHROPIC_API_KEY": key} if key else None) if a] or [{}]


def auth_refused(text: str) -> bool:
    return "401" in text or "authenticat" in text.lower() or "invalid bearer" in text.lower() or "invalid x-api-key" in text.lower()


def stream(text: str) -> int:
    """run Claude Code with live progress in Telegram, then send the answer and remember the turn"""
    import subprocess
    s = settings()
    prompt = build_prompt(text)
    prog = Progress(text, f"🤖 Claude is on it ({s['model']}, effort {s['effort']})")
    cmd = ["claude", "-p", prompt, "--model", MODELS[s["model"]], "--effort", s["effort"], "--append-system-prompt-file", str(ROOT / "docs" / "AGENT.md"),
           "--output-format", "stream-json", "--verbose", "--include-partial-messages", "--max-turns", "60", "--allowedTools", *ALLOWED, "--disallowedTools", *DISALLOWED]
    result = None
    for auth in auth_order():                       # the subscription token first (no extra cost); the pay-per-use API key only if the token is refused
        env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY")} | auth
        result = None
        try:
            p = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            for line in p.stdout:
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                result = handle_event(ev, prog) or result
            p.wait(timeout=60)
        except (OSError, subprocess.SubprocessError) as e:
            print("[chat] claude failed:", e)
        if not (result and auth_refused(str(result.get("result", "")))):
            break
        prog.step("Subscription login refused; trying the API key")
    (ROOT / "chat_result.json").write_text(json.dumps(result or {}))
    n = len(prog.steps)
    prog.done(f"Finished: {n} step{'s' if n != 1 else ''}" + (f", {result.get('num_turns')} turns" if result else " (no answer)"))
    return finish(ROOT / "chat_result.json", text)


if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0] == "control":
        t = a[1] if len(a) > 1 else ""
        msg = control(t)
        if msg is None:
            raise SystemExit(1)
        send(msg, buttons=control_buttons(t), edit=os.environ.get("EDIT") if os.environ.get("TAP") == "cmd" else None)
        raise SystemExit(0)
    if a and a[0] == "prompt":
        s = settings()
        (ROOT / "chat_prompt.txt").write_text(build_prompt(a[1] if len(a) > 1 else ""))
        (ROOT / "chat_args.txt").write_text(f"{MODELS[s['model']]} {s['effort']}")
        send(f"Thinking ({s['model']}, effort {s['effort']})...")
        raise SystemExit(0)
    if a and a[0] == "stream":
        if os.environ.get("TAP") == "say" and os.environ.get("EDIT", "").isdigit():      # a tapped answer: take the buttons off that message
            _tg("editMessageReplyMarkup", chat_id=_chat(), message_id=int(os.environ["EDIT"]), reply_markup={"inline_keyboard": []})
        raise SystemExit(stream(a[1] if len(a) > 1 else ""))
    if a and a[0] == "finish":
        raise SystemExit(finish(Path(a[1]), a[2] if len(a) > 2 else ""))
    raise SystemExit(__doc__)
