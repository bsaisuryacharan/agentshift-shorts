import json

from app import chat


def setup(monkeypatch, tmp_path):
    monkeypatch.setattr(chat, "DIR", tmp_path / "chat")
    monkeypatch.setattr(chat, "ROOT", tmp_path)
    monkeypatch.setenv("CHAT", "42")
    sent = []
    monkeypatch.setattr(chat, "send", lambda text, chat=None: sent.append(text))
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
