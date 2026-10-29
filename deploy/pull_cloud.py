"""Copy code changes the Telegram chat agent merged in the cloud into this Mac folder (run before deploy/sync_repo.py when it says so).

    python3 deploy/pull_cloud.py [owner/repo]

Only files under the synced folders (provision.ALLOW) that changed since the last 'sync code' commit are copied; each is listed. Review them with git diff.
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import provision  # noqa: E402

repo = sys.argv[1] if len(sys.argv) > 1 and "/" in sys.argv[1] else "bsaisuryacharan/agentshift-shorts"
here = Path(__file__).resolve().parents[1]
wd = Path(tempfile.mkdtemp()) / "r"
subprocess.run(["gh", "repo", "clone", repo, str(wd)], check=True)
log = subprocess.run(["git", "log", "--format=%H %s"], cwd=wd, capture_output=True, text=True).stdout.splitlines()
base = next((line.split()[0] for line in log if line.split(" ", 1)[1] == "sync code"), None)
if not base:
    sys.exit("no 'sync code' commit found; nothing to compare against")
files = subprocess.run(["git", "diff", "--name-only", f"{base}..HEAD"], cwd=wd, capture_output=True, text=True).stdout.split()
files = [f for f in files if f.split("/")[0] in provision.ALLOW]
if not files:
    print("no code changes in the cloud since the last sync")
for f in files:
    src, dst = wd / f, here / f
    if src.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        print("updated", f)
    elif dst.exists():
        dst.unlink()
        print("removed", f)
print("Review with git diff, run the tests, commit, then python3 deploy/sync_repo.py --force")
