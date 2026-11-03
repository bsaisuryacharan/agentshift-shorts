import json
from types import SimpleNamespace

import pytest

from app import chat, groq_chat


def test_protected_paths_and_commands(tmp_path, monkeypatch):
    monkeypatch.setattr(chat, 'ROOT', tmp_path)
    for path in ('.env', '../outside', '.git/config', 'token.json'):
        with pytest.raises(ValueError):
            groq_chat.safe_path(path)
    for command in ('git push origin main', 'sh -c env', 'git push -u origin main', 'ls /tmp', 'grep token .env'):
        with pytest.raises(ValueError):
            groq_chat.execute({'action': 'command', 'command': command}, '')


def test_groq_tool_loop_sends_answer(tmp_path, monkeypatch):
    monkeypatch.setattr(chat, 'ROOT', tmp_path)
    (tmp_path / 'docs').mkdir()
    (tmp_path / 'docs/AGENT.md').write_text('Rules')
    monkeypatch.setenv('GROQ_API_KEY', 'test')
    monkeypatch.setattr(chat, 'build_prompt', lambda text: text)
    monkeypatch.setattr(chat, 'Progress', lambda *a: SimpleNamespace(step=lambda *a: None, done=lambda *a: None))
    sent, remembered, calls = [], [], []
    monkeypatch.setattr(chat, 'send', lambda text, **kw: sent.append(text) or 123)
    monkeypatch.setattr(chat, 'remember', lambda *args: remembered.append(args))
    monkeypatch.setattr(groq_chat, 'execute', lambda args, text: 'System healthy')
    replies = [ {'role': 'assistant', 'content': None, 'tool_calls': [{'id': '1', 'type': 'function', 'function': {'name': 'repository', 'arguments': json.dumps({'action': 'list'})}}]}, {'role': 'assistant', 'content': 'Groq is connected. System healthy.'} ]
    class Client:
        def __init__(self, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def post(self, url, **kwargs):
            calls.append(kwargs['json'])
            msg = replies.pop(0)
            return SimpleNamespace(status_code=200, json=lambda: {'choices': [{'message': msg}]})
    monkeypatch.setattr(groq_chat.httpx, 'Client', Client)
    assert groq_chat.run('Check system') == 0
    assert sent == ['Groq is connected. System healthy.']
    assert remembered[0][2]['provider'] == 'groq'
    assert len(calls) == 2
