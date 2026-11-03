"""Groq tool loop for the Telegram system agent, using the existing chat memory."""
import json
import os
import shlex
import subprocess
from pathlib import Path

import httpx

from . import chat

MODEL = "openai/gpt-oss-120b"
TOOLS = [{"type": "function", "function": {"name": "repository", "description":
    "Read or write a repository file (path/content), list files (path), or run an allowed command (command). Commands are argv strings, no shell operators. Read docs/AGENT.md for system rules. Code changes must go on chat/* branches and through a PR; never push main.",
    "parameters": {"type": "object", "properties": {
        "action": {"type": "string", "enum": ["read", "write", "list", "command"]},
        "path": {"type": "string"}, "content": {"type": "string"}, "command": {"type": "string"}}, "required": ["action"]}}}]


def safe_path(value):
    p = (chat.ROOT / value).resolve()
    rel = p.relative_to(chat.ROOT.resolve())
    if any(x.startswith('.') for x in rel.parts) or p.name in ("token.json", "oauth_client.json"):
        raise ValueError("Protected path")
    return p


def execute(args, user_text):
    action = args['action']
    if action in ('read', 'write', 'list'):
        p = safe_path(args.get('path', ''))
        if action == 'read':
            return p.read_text()[:18000]
        if action == 'list':
            return '\n'.join(x.name for x in p.iterdir() if not x.name.startswith('.'))[:8000]
        rel = p.relative_to(chat.ROOT)
        branch = subprocess.run(['git', 'branch', '--show-current'], cwd=chat.ROOT, capture_output=True, text=True, check=True).stdout.strip()
        if str(rel) != 'state/chat/memory.md' and not branch.startswith('chat/'):
            raise ValueError('Create a chat/* branch before editing code')
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(args['content'])
        return 'Saved ' + str(rel)
    if action != 'command':
        raise ValueError('Unknown action')
    argv = shlex.split(args.get('command', ''))
    prefixes = [shlex.split(x[5:-1].removesuffix(':*')) for x in chat.ALLOWED if x.startswith('Bash(')]
    # Enforce literal argv prefixes without invoking a shell. Branch names are checked separately.
    branch_prefixes = [('git', 'switch', '-c'), ('git', 'push', '-u', 'origin')]
    branch_ok = any(tuple(argv[:len(pre)]) == pre and len(argv) > len(pre) and argv[len(pre)].startswith('chat/') for pre in branch_prefixes)
    allowed = any(argv[:len(pre)] == pre for pre in prefixes if pre not in [list(x) + ['chat/'] for x in branch_prefixes])
    if not (allowed or branch_ok) or any(x in (';', '|', '&&', '||', '>','<') for x in argv):
        raise ValueError('Command outside allow-list')
    # grep/ls can read outside the checkout; use the bounded file tools instead.
    if argv[0] in ('grep', 'ls') or any(x.startswith('--git-dir') or x.startswith('--work-tree') for x in argv):
        raise ValueError('Use bounded repository tools')
    if '--force' in argv or '-f' in argv and argv[0] == 'git':
        raise ValueError('Force operations are disabled')
    if 'app.orchestrator' in argv:
        cmd = argv[argv.index('--text') + 1] if '--text' in argv else ''
        if cmd.split(' ')[0] in ('/upload', '/approve') and cmd.split(' ')[0] not in user_text:
            raise ValueError('Owner must explicitly request upload/approve')
    result = subprocess.run(argv, cwd=chat.ROOT, capture_output=True, text=True, timeout=180)
    chat.log_action('Groq command', shlex.join(argv))
    return f'exit={result.returncode}\n' + (result.stdout + result.stderr)[-16000:]


def run(text):
    if not os.environ.get('GROQ_API_KEY'):
        chat.send('Groq is not connected: GROQ_API_KEY is missing.')
        return 1
    prog = chat.Progress(text, f'🤖 Groq is on it ({MODEL})')
    system = (chat.ROOT / 'docs/AGENT.md').read_text().replace('Claude', 'Groq').replace(' <noreply@anthropic.com>', ' <noreply@users.noreply.github.com>')
    system += '\nYou use Groq, not Claude. Use the repository tool for actions and observation. Never claim an action succeeded without a successful tool result. Effort is ' + chat.settings()['effort'] + '. Keep answers short.'
    messages = [{'role': 'system', 'content': system}, {'role': 'user', 'content': chat.build_prompt(text)[-18000:]}]
    reply, error = '', False
    try:
        with httpx.Client(timeout=90) as client:
            for turn in range(20):
                r = client.post('https://api.groq.com/openai/v1/chat/completions', headers={'Authorization': 'Bearer ' + os.environ['GROQ_API_KEY']}, json={
                    'model': MODEL, 'messages': messages, 'tools': TOOLS, 'max_completion_tokens': 4096, 'temperature': 0.3})
                if r.status_code != 200:
                    raise RuntimeError(f'Groq HTTP {r.status_code}')
                msg = r.json()['choices'][0]['message']
                messages.append({k: v for k, v in msg.items() if k in ('role', 'content', 'tool_calls')})
                calls = msg.get('tool_calls') or []
                if not calls:
                    reply = (msg.get('content') or '').strip()
                    if not reply:
                        raise RuntimeError('Groq returned no answer')
                    break
                for call in calls:
                    prog.step('Checking the system / carrying out the requested action')
                    try:
                        if call['function']['name'] != 'repository':
                            raise ValueError('Unknown tool')
                        out = execute(json.loads(call['function']['arguments']), text)
                    except Exception as exc:
                        out = 'Tool failed: ' + type(exc).__name__ + ': ' + str(exc)[:300]
                    messages.append({'role': 'tool', 'tool_call_id': call['id'], 'content': out})
            else:
                raise RuntimeError('Tool step limit reached')
    except Exception as exc:
        error = True
        reply = f'Groq could not finish ({type(exc).__name__}). Please try again shortly.'
        print('[groq-chat]', type(exc).__name__, str(exc)[:80] if isinstance(exc, RuntimeError) else '')
    prog.done('Finished' if not error else 'Failed')
    body, buttons = chat.split_buttons(reply)
    mid = chat.send(body, buttons=buttons)
    chat.remember(text, body, {'model': MODEL, 'provider': 'groq', 'error': error})
    print('[groq-chat] reply delivered:', bool(mid), 'model:', MODEL, 'error:', error)
    return int(error or not mid)
