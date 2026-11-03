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


def base(monkeypatch, tmp_path):
    monkeypatch.setattr(chat, 'ROOT', tmp_path)
    (tmp_path / 'docs').mkdir()
    (tmp_path / 'docs/AGENT.md').write_text('Rules')
    monkeypatch.setenv('GROQ_API_KEY', 'test')
    monkeypatch.setattr(chat, 'Progress', lambda *a: SimpleNamespace(step=lambda *a: None, done=lambda *a: None))
    monkeypatch.setattr(chat, 'send', lambda text, **kw: 123)
    monkeypatch.setattr(chat, 'remember', lambda *args: None)
    monkeypatch.setattr(groq_chat, 'DEAD', set())


def test_groq_tool_loop_sends_answer(tmp_path, monkeypatch):
    base(monkeypatch, tmp_path)
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
    assert remembered[0][2]['provider'] == 'groq' and remembered[0][2]['model'] == groq_chat.MODEL
    assert len(calls) == 2


def test_prompt_keeps_head_and_new_message(tmp_path, monkeypatch):
    base(monkeypatch, tmp_path)
    monkeypatch.setattr(chat, 'memory', lambda: 'M' * 2990)                            # a fat memory (capped at 3000 chars)
    monkeypatch.setattr(chat, 'actions', lambda: [{'ts': '2026-11-03T10:00:00', 'what': 'Ran the cycle', 'detail': 'd' * 300}])
    monkeypatch.setattr(chat, 'status_block', lambda: 'S' * 1200)
    long = 'a' * 1500                                                                  # a fat old turn; only this may be dropped
    monkeypatch.setattr(chat, 'history', lambda: [{'user': 'old q', 'reply': long}, {'user': 'new q', 'reply': 'new a'}])
    p = groq_chat.build_user_prompt('did the short go out today?')
    assert 'M' * 100 in p and ('d' * 300) in p and ('S' * 1200) in p                   # head is never cut
    assert 'did the short go out today?' in p                                              # the new message is never cut
    assert 'OWNER: old q' not in p and 'OWNER: new q' in p                                 # only old conversation gives way
    assert len(p) <= groq_chat.PROMPT_CHARS + 2000                                         # head + newest turn always stay; oldest goes first


def test_falls_back_after_429_and_reports_the_working_model(tmp_path, monkeypatch):
    base(monkeypatch, tmp_path)
    sent, remembered, seen = [], [], []
    monkeypatch.setattr(chat, 'send', lambda text, **kw: sent.append(text) or 123)
    monkeypatch.setattr(chat, 'remember', lambda *args: remembered.append(args))
    class Client:
        def __init__(self, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def post(self, url, **kwargs):
            seen.append(kwargs['json']['model'])
            if len(seen) == 1:                                                             # the primary model: quota used up
                return SimpleNamespace(status_code=429, json=lambda: {})
            return SimpleNamespace(status_code=200, json=lambda: {'choices': [{'message': {'role': 'assistant', 'content': 'Up. Yesterday the Short posted at 6:00 UTC.'}}]})
    monkeypatch.setattr(groq_chat.httpx, 'Client', Client)
    assert groq_chat.run('is it up?') == 0 and not remembered[0][2]['error']
    assert seen[0] == groq_chat.MODEL and seen[1] in groq_chat.FALLBACKS
    assert remembered[0][2]['model'] == seen[1]


def test_quota_message_when_every_model_is_rate_limited(tmp_path, monkeypatch):
    base(monkeypatch, tmp_path)
    sent, remembered = [], []
    monkeypatch.setattr(chat, 'send', lambda text, **kw: sent.append(text) or 123)
    monkeypatch.setattr(chat, 'remember', lambda *args: remembered.append(args))
    class Client:
        def __init__(self, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def post(self, url, **kwargs): return SimpleNamespace(status_code=429, json=lambda: {})
    monkeypatch.setattr(groq_chat.httpx, 'Client', Client)
    assert groq_chat.run('hello') == 1
    assert 'free quota' in sent[0] and remembered[0][2]['error'] is True


def test_retired_model_is_never_asked_again(tmp_path, monkeypatch):
    base(monkeypatch, tmp_path)
    monkeypatch.setattr(chat, 'send', lambda text, **kw: 123)
    monkeypatch.setattr(chat, 'remember', lambda *args: None)
    seen = []
    class Client:
        def __init__(self, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def post(self, url, **kwargs):
            seen.append(kwargs['json']['model'])
            if kwargs['json']['model'] == 'openai/gpt-oss-120b':                           # pretend Groq retired the primary today
                return SimpleNamespace(status_code=404, json=lambda: {})
            return SimpleNamespace(status_code=200, json=lambda: {'choices': [{'message': {'role': 'assistant', 'content': 'Fine.'}}]})
    monkeypatch.setattr(groq_chat.httpx, 'Client', Client)
    assert groq_chat.run('status?') == 0
    assert seen.count('openai/gpt-oss-120b') == 1                                          # one 404, then skipped forever this run


def test_empty_answer_gets_a_nudge_before_failing(tmp_path, monkeypatch):
    base(monkeypatch, tmp_path)
    messages_seen = []
    class Client:
        def __init__(self, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def post(self, url, **kwargs):
            messages_seen.append(kwargs['json']['messages'])
            payload = ({'role': 'assistant', 'content': ''} if len(messages_seen) == 1
                       else {'role': 'assistant', 'content': 'The Short went out at 6:00 UTC.'})
            return SimpleNamespace(status_code=200, json=lambda: {'choices': [{'message': payload}]})
    monkeypatch.setattr(groq_chat.httpx, 'Client', Client)
    monkeypatch.setattr(chat, 'send', lambda text, **kw: 123)
    monkeypatch.setattr(chat, 'remember', lambda *args: None)
    assert groq_chat.run('did it go out?') == 0
    assert 'Answer now' in messages_seen[1][-1]['content']                                 # the retry asks for visible text
