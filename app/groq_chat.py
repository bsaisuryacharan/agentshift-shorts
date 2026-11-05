"""Tool loop for the Telegram system agent: OpenCode's GLM-5.3-Flash (the owner's OpenRouter key) with the existing Groq free models as
fallbacks, using the existing chat memory."""
import json
import os
import shlex
import subprocess
from pathlib import Path

import httpx

from . import chat

# the ladder: OpenCode's own model first (same GLM the owner's OpenCode subscription uses), then the free Groq models
MODEL = "z-ai/glm-5.3-flash"
FALLBACKS = ("openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.8-27b")   # only models that really exist on Groq (live model list)
APIS = {                                   # candidate -> (chat-completions URL, env key). Both are OpenAI-compatible.
    "z-ai/glm-5.3-flash": ("https://openrouter.ai/api/v1/chat/completions", "OPENROUTER_API_KEY"),
    "openai/gpt-oss-120b": ("https://api.groq.com/openai/v1/chat/completions", "GROQ_API_KEY"),
    "openai/gpt-oss-20b": ("https://api.groq.com/openai/v1/chat/completions", "GROQ_API_KEY"),
    "qwen/qwen3.8-27b": ("https://api.groq.com/openai/v1/chat/completions", "GROQ_API_KEY"),
}
DEAD = set()                                             # models a provider retired (HTTP 404); never asked again this run
PROMPT_CHARS = 6000                                      # the free Groq models are tight on tokens/minute
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


def build_user_prompt(text):
    """memory + recent actions + live system status + recent conversation + the new message, all inside PROMPT_CHARS.
    The head (memory, status) and the new message are never cut; only old conversation turns get dropped when the budget is tight."""
    mem = chat.memory() or "(empty)"
    if len(mem) > 3000:
        mem = "…(older part trimmed)\n" + mem[-3000:]        # chat.memory() already keeps the newest part
    acts = "\n".join(f"{a['ts'][:16]} {a['what']}" + (f" - {a['detail']}" if a.get("detail") else "") for a in chat.actions())
    head = ("LONG-TERM MEMORY:\n" + mem + "\n\n"
            "WHAT WAS ACTUALLY DONE RECENTLY (automatic log, oldest first):\n" + (acts or "(nothing yet)") + "\n\n"
            "LIVE SYSTEM STATUS (read from the repo just now):\n" + (chat.status_block() or "(none)") + "\n\n")
    new = "NEW MESSAGE FROM THE OWNER (Telegram):\n" + text
    rows = [f"OWNER: {h['user']}\nYOU: {h['reply'][:1500]}" for h in chat.history()]
    turns = "RECENT CONVERSATION WITH THE OWNER (oldest first):\n"
    room = PROMPT_CHARS - len(head) - len(new) - len(turns)
    while len(rows) > 1 and sum(len(r) for r in rows) + 2 * len(rows) > room:
        rows.pop(0)                                          # drop the OLDEST turn, keep the recent context
    convo = (turns + "\n\n".join(rows) + "\n\n") if rows and room > 0 else ""
    return head + convo + new + "\n\nAnswer the owner. Plain text, short, no markdown tables."


def _ask(client, candidate, messages):
    """one model on one provider, one call; returns the response"""
    url, key_env = APIS.get(candidate, APIS["openai/gpt-oss-120b"])
    headers = {'Authorization': 'Bearer ' + os.environ[key_env]}
    if 'openrouter.ai' in url:
        headers.update({'HTTP-Referer': 'https://github.com/bsaisuryacharan/agentshift-shorts', 'X-Title': 'AgentShift Telegram agent'})
    return client.post(url, headers=headers, json={
        'model': candidate, 'messages': messages, 'tools': TOOLS, 'max_completion_tokens': 2048, 'temperature': 0.3})


def provider(model: str) -> str:
    return 'openrouter' if 'openrouter' in APIS.get(model, APIS["openai/gpt-oss-120b"])[0] else 'groq'


def run(text):
    available = [m for m in (MODEL, *FALLBACKS) if os.environ.get(APIS.get(m, ('', 'X-GONE'))[1])]   # only ladder entries whose key exists
    if not available:
        chat.send('No model is connected: neither OPENROUTER_API_KEY nor GROQ_API_KEY is set.')
        return 1
    prog = chat.Progress(text, f'🤖 On it ({(available[0] or "?").split("/")[-1]})')
    system = (chat.ROOT / 'docs/AGENT.md').read_text().replace('Claude', 'the model').replace(' <noreply@anthropic.com>', ' <noreply@users.noreply.github.com>')
    system += '\nYou are the Agent Shift Telegram assistant (GLM-5.3-Flash via OpenRouter, with Groq free models as backup). Use the repository tool for actions and observation. Never claim an action succeeded without a successful tool result. Effort is ' + chat.settings()['effort'] + '. Keep answers short.'
    messages = [{'role': 'system', 'content': system}, {'role': 'user', 'content': build_user_prompt(text)}]
    reply, error, active_model, candidates = '', False, available[0], available
    try:
        with httpx.Client(timeout=90) as client:
            nudges = 0                                      # retries after a reasoning-only answer with no text
            for turn in range(20):
                candidates = [m for m in dict.fromkeys([active_model or available[0], *available]) if m not in DEAD]
                if not candidates:
                    raise RuntimeError('No working model for this run (every candidate failed or was retired)')
                statuses, model_used = set(), None
                for candidate in candidates:
                    r = _ask(client, candidate, messages)
                    if r.status_code == 200:
                        model_used = candidate
                        break
                    statuses.add(r.status_code)
                    print('[chat] model unavailable:', candidate, 'HTTP', r.status_code)
                    if r.status_code in (404, 400, 403):
                        DEAD.add(candidate)                 # gone from the provider: stop asking, use the next model
                if model_used is None:
                    active_model = None
                    if statuses <= {429, 402}:
                        raise RuntimeError('quota')
                    raise RuntimeError('HTTP ' + '/'.join(str(s) for s in sorted(statuses)))
                active_model = model_used
                msg = r.json()['choices'][0]['message']
                calls = msg.get('tool_calls') or []
                if not calls:
                    reply = (msg.get('content') or '').strip()
                    if not reply:                           # reasoning ate the whole reply budget: nudge for actual text
                        if nudges >= 2:
                            raise RuntimeError('Groq sent an empty answer (reply budget spent on reasoning)')
                        nudges += 1
                        messages.append({'role': 'user', 'content': 'Answer now: one short plain-text paragraph for the owner.'})
                        continue
                    break
                messages.append({k: v for k, v in msg.items() if k in ('role', 'content', 'tool_calls')})
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
        if 'quota' in str(exc):
            reply = 'Every model is rate-limited right now (GLM or its Groq backups). Try again in an hour, or ask something small.'
        else:
            reply = f'The model could not finish ({type(exc).__name__}). Please try again shortly.'
        print('[chat]', type(exc).__name__, str(exc)[:100])
    prog.done('Finished' if not error else 'Failed')
    body, buttons = chat.split_buttons(reply)
    mid = chat.send(body, buttons=buttons)
    chat.remember(text, body, {'model': active_model or 'none', 'provider': provider(active_model or 'openai/gpt-oss-120b'), 'error': error})
    print('[chat] reply delivered:', bool(mid), 'model:', active_model or 'none', 'error:', error)
    return int(error or not mid)
