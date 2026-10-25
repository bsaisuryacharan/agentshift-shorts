"""Telegram-driven orchestrator: every message you send becomes work; the result comes back in the same chat.

    python -m app.orchestrator listen                                           # run on your Mac: polls your existing bot
    python -m app.orchestrator handle --chat <chat_id> --text "<message>"        # one message (what the GitHub workflow calls)

Messages it understands (plain language also works - an LLM classifies it):
    /new <topic>                 make a new Short
    /status                      what is the current Short and how did it score
    /list                        recent Shorts
    /use <id>                    switch the current Short
    /help
    anything else                = a change request for the CURRENT Short  ("shorter hook", "re-roll image 3", "say 8.3 billion", ...)

State is in the repo (state/<chat>.json, projects/<id>/{spec.json,img/}), so every run can start on a blank machine.
Only the chat in TELEGRAM_CHAT_ID is obeyed. Messages are treated as the owner's instructions for editing a *spec*, never as shell commands.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import traceback
from pathlib import Path

from . import auto

ROOT = Path(__file__).resolve().parents[1]
STATE, PROJ, OUT = ROOT / "state", ROOT / "projects", ROOT / "runs"
HELP = ("Commands:\n/new <topic> - make a Short\n/approve - approve the current Short and get its upload pack\n/upload - retry the YouTube upload of the approved Short (approving already does it)\n/status - current Short\n/list - recent Shorts\n/use <id> - switch\n"
        "Or just describe a change to the current Short: \"shorter hook\", \"re-roll image 3\", \"change 8.3 to 8.2 billion\".")

REVISE_SYSTEM = auto.SYSTEM + """
You are now EDITING an existing spec. Apply ONLY the requested change; keep everything else byte-identical (ids, keys, prompts, seeds, hud).
To re-roll a picture, add/increase an integer "seed" on the beat that first uses it and/or tweak its "prompt". If the prompt of a picture changes,
that picture is regenerated; unchanged pictures are reused. Return the FULL updated spec JSON only."""

CLASSIFY_SYSTEM = """Classify a Telegram message sent by the owner of a YouTube Shorts channel to their production bot. Output ONLY JSON:
{"intent":"new|revise|status|list|help|approve","topic":"(only for new)","instruction":"(only for revise: the change, restated clearly)"}
'new' = wants a different/new video about a topic; 'revise' = wants to change the current video; 'status' = asks how it's going."""


def _state(chat: str) -> dict:
    p = STATE / f"{chat}.json"
    return json.loads(p.read_text()) if p.exists() else {"current": None, "projects": {}}


def _save(chat: str, st: dict) -> None:
    STATE.mkdir(exist_ok=True)
    (STATE / f"{chat}.json").write_text(json.dumps(st, indent=1))


def say(chat: str, text: str) -> None:
    print("[bot]", text, flush=True)
    auto.telegram(text, chat=chat)


def classify(text: str, st: dict) -> dict:
    t = text.strip()
    low = t.lower()
    if low.startswith("/new "):
        return {"intent": "new", "topic": t[5:].strip()}
    for cmd, intent in (("/status", "status"), ("/list", "list"), ("/help", "help"), ("/start", "help")):
        if low.startswith(cmd):
            return {"intent": intent}
    if low in ("/approve", "approve", "approved", "/publish") or low.startswith("/approve "):
        return {"intent": "approve"}
    if low == "/upload" or low.startswith("/upload "):
        return {"intent": "upload"}
    if low.startswith("/use "):
        return {"intent": "use", "id": t[5:].strip()}
    if not st.get("current"):                      # nothing to revise yet -> a bare message is a topic, unless it is chit-chat
        if len(t.split()) < 3 or low.rstrip("!.? ") in ("hi", "hello", "hey", "test", "ping", "ok", "thanks"):
            return {"intent": "help"}
        return {"intent": "new", "topic": t}
    out, _ = auto.ask(CLASSIFY_SYSTEM, f"CURRENT SHORT: {st['projects'][st['current']].get('title')}\nMESSAGE: {t}")
    return out if out.get("intent") in {"new", "revise", "status", "list", "help", "approve"} else {"intent": "revise", "instruction": t}


def _persist(st: dict, spec: dict, run_dir: Path, j: dict | None, status: str, images: bool = True) -> None:
    base = spec["id"].rsplit("-r", 1)[0]
    d = PROJ / spec["id"]
    d.mkdir(parents=True, exist_ok=True)
    (d / "spec.json").write_text(json.dumps(spec, ensure_ascii=False, indent=1))
    if (run_dir / "img").exists():
        if images:
            shutil.copytree(run_dir / "img", d / "img", dirs_exist_ok=True)
        elif (run_dir / "img" / "credits.json").exists():        # the daily Short keeps only its credits in the repo (pictures would bloat it)
            (d / "img").mkdir(exist_ok=True)
            shutil.copy(run_dir / "img" / "credits.json", d / "img" / "credits.json")
    if (run_dir / "vid" / "credits.json").exists():
        (d / "vid").mkdir(exist_ok=True)
        shutil.copy(run_dir / "vid" / "credits.json", d / "vid" / "credits.json")
    scores = (j or {}).get("scores")
    if scores is None and (run_dir / "vision.json").exists():          # DRAFTs carry the judge's scores in vision.json
        try:
            scores = json.loads((run_dir / "vision.json").read_text()).get("scores")
        except ValueError:
            scores = None
    st["projects"][spec["id"]] = {"title": spec["title"], "base": base, "status": status, "scores": scores, "run_id": os.environ.get("GITHUB_RUN_ID")}
    st["current"] = spec["id"]


def changed_pictures(old: dict, new: dict) -> set[str]:
    """names of stills that must be regenerated: prompt or seed changed (or new)."""
    def pics(s):
        d = {}
        for b in s["beats"]:
            for x in [b] + b.get("cuts", []):
                if x.get("img") and x.get("prompt") and x["img"] not in d:
                    d[x["img"]] = (x["prompt"], x.get("seed", 7), x.get("photo"))
        return d
    o, n = pics(old), pics(new)
    return {k for k, v in n.items() if o.get(k) != v}


def do_new(chat: str, st: dict, topic: str) -> None:
    say(chat, f"On it: researching and writing a Short about “{topic}”. This takes ~10-15 min.")
    rc = auto.run(topic, None, OUT, deliver=True, chat=chat)
    register_last(st, rc)
    if rc == 3:
        say(chat, f"No Short about “{topic}” passed the quality review, so nothing was sent. Try another topic or angle with /new.")


def register_last(st: dict, rc: int = 0, images: bool = True) -> bool:
    """make the Short auto.run just produced (runs/_last.json) the current one so /status, /list and /approve know it"""
    last = OUT / "_last.json"
    if rc not in (0, 3) or not last.exists():
        return False
    info = json.loads(last.read_text())
    spec = json.loads(Path(info["spec"]).read_text())
    _persist(st, spec, OUT / spec["id"], None, "draft" if (rc == 3 or info.get("draft")) else "delivered", images=images)
    return True


def do_revise(chat: str, st: dict, instruction: str) -> None:
    cur = st["current"]
    old = json.loads((PROJ / cur / "spec.json").read_text())
    facts = old.get("_facts", {"url": "", "text": ""})
    say(chat, f"Got it: “{instruction[:120]}”. Re-rendering only what changed (~8-12 min).")
    user = f"FACTS (source {facts['url']}):\n{facts['text']}\n\nCURRENT SPEC:\n{json.dumps({k: v for k, v in old.items() if k != '_facts'}, ensure_ascii=False)}\n\nREQUESTED CHANGE: {instruction}"
    new, writer = None, None
    for _ in range(3):
        cand, prov = auto.ask(REVISE_SYSTEM, user, prefer=["groq", "gemini", "openrouter"])
        errs = auto.validate_spec(cand, facts["text"])
        if not errs:
            new, writer = cand, prov
            break
        user += "\nThat JSON failed validation: " + "; ".join(errs) + "\nReturn corrected full JSON."
    if new is None:
        say(chat, f"I couldn't apply that change safely ({'; '.join(errs)[:300]}). Try rewording it.")
        return
    n = sum(1 for k in st["projects"] if k.startswith(old["id"].rsplit("-r", 1)[0]))
    new["id"] = f"{old['id'].rsplit('-r', 1)[0]}-r{n}"
    new["_facts"], new["_writer"] = facts, writer
    run_dir = OUT / new["id"]
    img = run_dir / "img"
    img.mkdir(parents=True, exist_ok=True)
    if (PROJ / cur / "img").exists():
        shutil.copytree(PROJ / cur / "img", img, dirs_exist_ok=True)
    redo = changed_pictures(old, new)
    for name in redo:
        for f in img.glob(Path(name).stem + ".*"):
            f.unlink()
    ok, notes, run_dir, j = auto.finish(new, writer, OUT, True, chat)
    draft = (not ok) and j and j["scores"].get("accuracy", 0) >= 9 and j["scores"].get("policy", 0) >= 10
    if draft:
        auto.send_draft(new, run_dir, j, chat)
    _persist(st, new, run_dir, j, "delivered" if ok else "draft" if draft else "needs-work")
    if ok:
        say(chat, f"Done. Regenerated pictures: {sorted(redo) or 'none'}. Reply with more changes any time.")
    elif draft:
        say(chat, f"Done (sent as a draft). Regenerated pictures: {sorted(redo) or 'none'}.")
    else:
        say(chat, "The edited version didn't pass my checks, so I did not send it. Reasons: " + "; ".join(notes)[:500] + "\nTell me how to adjust.")


def publish_pack(spec: dict, proj: Path) -> str:
    """title / description / tags / credits for the owner to paste into YouTube Studio (uploading stays a human step: private-until-audit rule)."""
    from . import pack
    text = pack.build(spec, [proj / "img" / "credits.json", proj / "vid" / "credits.json"])
    (proj / "publish.md").write_text(text)
    return text


def do_upload(chat: str, st: dict) -> None:
    """/upload: only for the current Short, only after /approve, once. Private + scheduled; the owner stays in control of making it public."""
    from . import pack, upload
    cur = st.get("current")
    p = st["projects"].get(cur) if cur else None
    if not p:
        say(chat, "Nothing to upload yet.")
    elif p.get("uploaded"):
        say(chat, f"Already uploaded: {p['uploaded']['url']}")
    elif p.get("status") != "approved":
        say(chat, "Approve it first with /approve (only Shorts that passed the review can be approved), then send /upload.")
    elif not p.get("run_id"):
        say(chat, "I can't find the video of this Short (no run id was recorded).")
    else:
        spec = json.loads((PROJ / cur / "spec.json").read_text())
        parts = pack.parts(spec, [PROJ / cur / "img" / "credits.json", PROJ / cur / "vid" / "credits.json"])
        try:
            say(chat, "Uploading to YouTube (private, scheduled)...")
            video = upload.fetch_video(p["run_id"], cur)
            slot = upload.next_slot()
            res = upload.upload(video, parts, slot)
        except upload.UploadError as e:
            say(chat, f"Upload did not happen: {e}")
            return
        p["uploaded"] = res
        priv = res.get("privacy") or "private"
        say(chat, f"Uploaded: {res['url']}\nVisibility now: {priv}; scheduled to go public {res['publish_at']}.\n"
                  "Open YouTube Studio to check the copyright/audit result before it goes live. Pinned comment to add:\n" + parts["pinned"])


def handle(chat: str, text: str) -> int:
    allowed = os.environ.get("TELEGRAM_CHAT_ID")
    if allowed and str(chat) != str(allowed):
        print("ignored: chat not allowed")
        return 0
    st = _state(chat)
    try:
        c = classify(text, st)
        it = c["intent"]
        if it == "help":
            say(chat, HELP)
        elif it == "list":
            say(chat, "\n".join(f"{'→ ' if k == st['current'] else '  '}{k}: {v['title']} [{v['status']}]" for k, v in list(st["projects"].items())[-10:]) or "No Shorts yet. /new <topic>")
        elif it == "use":
            if c["id"] in st["projects"]:
                st["current"] = c["id"]
                say(chat, f"Current Short: {c['id']}")
            else:
                say(chat, "Unknown id. /list")
        elif it == "status":
            cur = st["current"]
            say(chat, "No Short yet." if not cur else f"{cur}: {st['projects'][cur]['title']} [{st['projects'][cur]['status']}] scores {st['projects'][cur].get('scores')}")
        elif it == "approve":
            cur = st.get("current")
            if not cur:
                say(chat, "Nothing to approve yet. /new <topic>")
            else:
                if st["projects"][cur].get("status") == "draft":
                    say(chat, "The current Short never passed the quality review, so it was not sent and cannot be approved. Wait for the next one, or /new <topic>.")
                    _save(chat, st)
                    return 0
                spec = json.loads((PROJ / cur / "spec.json").read_text())
                st["projects"][cur]["status"] = "approved"
                ledger = ROOT / auto.LIMITS["history"]
                ledger.parent.mkdir(parents=True, exist_ok=True)
                with open(ledger, "a") as f:
                    f.write(json.dumps({"id": cur, "title": spec["title"], "blob": spec["title"].lower() + " " + " ".join(b["say"].lower() for b in spec["beats"])}) + "\n")
                say(chat, "Approved. Publish pack:\n\n" + publish_pack(spec, PROJ / cur))
                _save(chat, st)
                do_upload(chat, st)                       # approving is the only step: the upload (private, scheduled) follows by itself
        elif it == "upload":
            do_upload(chat, st)
        elif it == "new":
            do_new(chat, st, c["topic"])
        else:
            if not st.get("current"):
                say(chat, "There's no current Short to change. /new <topic>")
            else:
                do_revise(chat, st, c.get("instruction") or text)
        _save(chat, st)
        return 0
    except SystemExit as e:
        say(chat, f"Stopped: {e}")
        _save(chat, st)
        return 1
    except Exception as e:   # always tell the owner, never fail silently
        traceback.print_exc()
        say(chat, f"Something broke: {e!r}"[:600])
        return 1


def extract(updates: list[dict], allowed: str | None) -> list[tuple[int, str, str]]:
    """(update_id, chat, text) for text messages from the owner's chat only."""
    out = []
    for u in updates:
        m = u.get("message") or u.get("edited_message") or {}
        if m.get("text") and (not allowed or str(m["chat"]["id"]) == str(allowed)):
            out.append((u["update_id"], str(m["chat"]["id"]), m["text"]))
    return out


def listen() -> int:
    """Long-poll the existing Telegram bot (works on your Mac, no webhook/Cloudflare/GitHub needed). Run: python -m app.orchestrator listen
    Reads TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID / LLM keys from the project's .env via python-dotenv (never printed)."""
    import time

    import httpx
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    tok, allowed = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not tok:
        raise SystemExit("TELEGRAM_BOT_TOKEN missing in .env")
    off_file = STATE / "offset.txt"
    STATE.mkdir(exist_ok=True)
    offset = int(off_file.read_text()) if off_file.exists() else 0
    print("listening for Telegram messages (Ctrl+C to stop)", flush=True)
    while True:
        try:
            r = httpx.get(f"https://api.telegram.org/bot{tok}/getUpdates", params={"offset": offset, "timeout": 50}, timeout=65)
            r.raise_for_status()
            ups = r.json().get("result", [])
        except (httpx.HTTPError, ValueError) as e:
            print("poll error:", type(e).__name__, flush=True)
            time.sleep(5)
            continue
        for u in ups:
            offset = u["update_id"] + 1
            off_file.write_text(str(offset))                  # advance first: a crash never replays a message
        for _, chat, text in extract(ups, allowed):
            print("message:", text[:80], flush=True)
            handle(chat, text)


def register_cli() -> int:
    """after the daily cloud run: register runs/_last.json for the owner's chat (TELEGRAM_CHAT_ID) and save state"""
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if not chat:
        print("TELEGRAM_CHAT_ID not set; nothing registered")
        return 0
    st = _state(chat)
    ok = register_last(st, 0, images=False)
    if ok:
        _save(chat, st)
    print("registered" if ok else "no fresh Short to register")
    return 0


if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0] == "register":
        raise SystemExit(register_cli())
    if a and a[0] == "listen":
        raise SystemExit(listen())
    if a and a[0] == "handle":
        raise SystemExit(handle(a[a.index("--chat") + 1], a[a.index("--text") + 1]))
    raise SystemExit(__doc__)
