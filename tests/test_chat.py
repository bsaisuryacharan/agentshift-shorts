import json

from app import chat


def setup(monkeypatch, tmp_path):
    monkeypatch.setattr(chat, "DIR", tmp_path / "chat")
    monkeypatch.setattr(chat, "ROOT", tmp_path)
    monkeypatch.setenv("CHAT", "42")
    sent = []
    monkeypatch.setattr(chat, "send", lambda text, chat=None, **kw: sent.append(text))
    return sent


def test_model_and_effort_controls_persist(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path)
    assert "sonnet" in chat.control("/model")
    assert "opus" in chat.control("/model opus") and chat.settings()["model"] == "opus"
    assert chat.control("/effort high").startswith("Effort set to high") and chat.settings()["effort"] == "high"
    assert "Choose one" in chat.control("/effort turbo") and chat.settings()["effort"] == "high"
    assert chat.control("what is going on?") is None              # plain text is for Claude


def test_memory_reset_and_prompt(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path)
    chat.remember("why was it rejected?", "the judge saw AI renders")
    p = chat.build_prompt("and now?")
    assert "why was it rejected?" in p and "and now?" in p and "LIVE SYSTEM STATUS" in p
    chat.control("/reset")
    assert chat.history() == [] and chat.settings()["model"] == "sonnet"


def test_finish_sends_answer_and_remembers(monkeypatch, tmp_path):
    sent = setup(monkeypatch, tmp_path)
    r = tmp_path / "r.json"
    r.write_text(json.dumps({"result": "Done: PR #3 lowers nothing.", "num_turns": 7, "total_cost_usd": 0.12, "is_error": False}))
    chat.finish(r, "make the hook shorter")
    assert sent == ["Done: PR #3 lowers nothing."] and chat.history()[-1]["user"] == "make the hook shorter"
    chat.finish(tmp_path / "missing.json", "x")
    assert "did not finish" in sent[-1]


def test_merge_gate_uses_only_chat_branches(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path)
    calls = []

    def gh(*a):
        calls.append(a)
        if a[:2] == ("pr", "list"):
            return json.dumps([{"number": 5, "title": "chat: hook", "headRefName": "chat/hook", "url": "u5"},
                               {"number": 6, "title": "other", "headRefName": "feature/x", "url": "u6"}])
        return "ok"
    monkeypatch.setattr(chat, "_gh", gh)
    assert "#5" in chat.control("/changes") and "#6" not in chat.control("/changes")
    assert "Merged #5" in chat.control("/merge")
    assert ("pr", "merge", "5", "--squash", "--delete-branch") in calls


def test_progress_lines_from_stream_events(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    prog = chat.Progress("why rejected?", "Claude is on it", min_gap=0)
    events = [
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "Let me look at the judge notes first."}]}},
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Read", "input": {"file_path": str(chat.ROOT / "data/judge_notes.jsonl")}}]}},
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {"command": "python -m pytest -q"}}]}},
        {"type": "result", "result": "Because of AI renders.", "num_turns": 3},
    ]
    results = [chat.handle_event(e, prog) for e in events]
    assert prog.steps == ["Reading data/judge_notes.jsonl", "Running the tests"]
    assert "judge notes" in prog.note and results[-1]["result"] == "Because of AI renders."
    text = prog._text()
    assert "✓ Reading data/judge_notes.jsonl" in text and "… Running the tests" in text


def test_describe_never_leaks_long_commands():
    assert chat.describe("Bash", {"command": "gh run view 123 --log | grep judge"}) == "Reading a run's log"
    assert len(chat.describe("Bash", {"command": "x" * 500})) < 80


def test_subscription_token_is_tried_before_the_api_key(monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "tok\nen ")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "key")
    assert chat.auth_order() == [{"CLAUDE_CODE_OAUTH_TOKEN": "token"}, {"ANTHROPIC_API_KEY": "key"}]
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN")
    assert chat.auth_order() == [{"ANTHROPIC_API_KEY": "key"}]
    assert chat.auth_refused("Failed to authenticate. API Error: 401 Invalid bearer token") and not chat.auth_refused("All good")


def test_buttons_for_controls_and_claude_choices(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path)
    rows = chat.control_buttons("/model")
    assert [b[0] for b in rows[0]] == ["opus", "✓ sonnet", "haiku"] and rows[0][0][1] == "cmd:/model opus"
    assert any("✓ medium" == b[0] for row in chat.control_buttons("/effort") for b in row)
    kb = chat.keyboard(chat.control_buttons("/settings"))
    assert kb["inline_keyboard"][-1][0]["callback_data"] == "cmd:/reset"
    body, buttons = chat.split_buttons("Post the Mariana Short now?\nBUTTONS: Yes, post it | Not now")
    assert body == "Post the Mariana Short now?" and buttons == [[("Yes, post it", "say:Yes, post it"), ("Not now", "say:Not now")]]
    assert chat.split_buttons("plain answer") == ("plain answer", None)
    assert all(len(b["callback_data"].encode()) <= 64 for row in chat.keyboard([[("x" * 90, "say:" + "y" * 90)]])["inline_keyboard"] for b in row)


def test_memory_and_action_log_reach_the_prompt(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path)
    (tmp_path / "chat").mkdir(parents=True, exist_ok=True)
    (tmp_path / "chat" / "memory.md").write_text("## Decisions\n- 2026-10-29 auto-post approved Shorts\n")
    prog = chat.Progress("post it", "Claude", min_gap=0)
    chat.handle_event({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash",
                       "input": {"command": 'python -m app.orchestrator handle --chat "$CHAT" --text "/upload"'}}]}}, prog)
    chat.handle_event({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Read", "input": {"file_path": "x"}}]}}, prog)
    acts = chat.actions()
    assert len(acts) == 1 and acts[0]["what"] == "Asking the orchestrator: /upload"         # reads are not system actions
    p = chat.build_prompt("what did we decide?")
    assert "auto-post approved Shorts" in p and "Asking the orchestrator: /upload" in p
    assert "auto-post" in chat.control("/memory") and "/upload" in chat.control("/actions")


def test_memory_is_capped(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path)
    (tmp_path / "chat").mkdir(parents=True, exist_ok=True)
    (tmp_path / "chat" / "memory.md").write_text("x" * 20000 + "LATEST")
    m = chat.memory()
    assert len(m) < 8200 and m.endswith("LATEST")
