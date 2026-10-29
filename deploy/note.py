"""Tell the Telegram chat agent about a change made on this Mac: appends a dated line to its long-term memory in the cloud repo.

    python3 deploy/note.py "Captions are now 10% larger"            # goes under "Changes made (outside the chat ...)"
    python3 deploy/note.py --section "Open items" "Check the voice pronunciation of Latin names"
"""
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

repo = "bsaisuryacharan/agentshift-shorts"
a = sys.argv[1:]
section = "Changes made"
if a[:1] == ["--section"]:
    section, a = a[1], a[2:]
if not a:
    sys.exit(__doc__)
line = f"- {date.today().isoformat()} {' '.join(a)}"
wd = Path(tempfile.mkdtemp()) / "r"
subprocess.run(["gh", "repo", "clone", repo, str(wd), "--", "-q", "--depth", "1"], check=True)
mem = wd / "state" / "chat" / "memory.md"
text = mem.read_text() if mem.exists() else "# Agent Shift - long-term memory\n"
lines = text.splitlines()
at = next((i for i, x in enumerate(lines) if x.startswith("## ") and section.lower() in x.lower()), None)
if at is None:
    lines += ["", f"## {section}", line]
else:
    end = next((i for i in range(at + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    while end > at + 1 and not lines[end - 1].strip():
        end -= 1
    lines.insert(end, line)
mem.parent.mkdir(parents=True, exist_ok=True)
mem.write_text("\n".join(lines) + "\n")
subprocess.run(["git", "add", str(mem)], cwd=wd, check=True)
subprocess.run(["git", "-c", "user.name=shorts-bot", "-c", "user.email=shorts-bot@users.noreply.github.com", "commit", "-qm", f"memory: {line[:60]}"], cwd=wd, check=True)
subprocess.run(["git", "push", "-q"], cwd=wd, check=True)
print("noted:", line)
