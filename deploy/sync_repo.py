"""Push the current code + workflows to your GitHub repo (run on your Mac after code changes):  python3 deploy/sync_repo.py [owner/repo]"""
import subprocess, sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import provision  # noqa: E402

repo = sys.argv[1] if len(sys.argv) > 1 and "/" in sys.argv[1] else "bsaisuryacharan/agentshift-shorts"
wd = Path(tempfile.mkdtemp()) / "r"
subprocess.run(["gh", "repo", "clone", repo, str(wd)], check=True)

def cloud_changes(wd: Path) -> list[str]:
    """code changes merged in the cloud by the Telegram chat agent (commits 'chat: ...') since the last sync from this Mac"""
    log = subprocess.run(["git", "log", "--format=%s"], cwd=wd, capture_output=True, text=True).stdout.splitlines()
    out = []
    for subj in log:
        if subj == "sync code":
            break
        if subj.startswith("chat:") and subj != "chat: conversation memory":
            out.append(subj)
    return out


pending = cloud_changes(wd)
if pending and "--force" not in sys.argv:
    print("STOP: Claude changed the system from Telegram since your last sync, and syncing now would overwrite it:")
    print("\n".join("  - " + p for p in pending))
    print("Bring those changes to this Mac first:  python3 deploy/pull_cloud.py   (then sync again; or add --force to discard them)")
    sys.exit(1)
keep_insights = wd / "assets" / "insights.json"       # written by the weekly cloud job: the repo copy is newer than anything on the Mac
saved = keep_insights.read_bytes() if keep_insights.exists() else None
for item in list(wd.iterdir()):                      # replace code, keep state/ projects/ data/ .git
    if item.name in provision.ALLOW or item.name == ".github":
        subprocess.run(["rm", "-rf", str(item)], check=True)
provision.stage(wd)
if saved is not None:
    keep_insights.parent.mkdir(parents=True, exist_ok=True)
    keep_insights.write_bytes(saved)
subprocess.run(["git", "add", "-A"], cwd=wd, check=True)
subprocess.run(["git", "-c", "user.name=shorts-bot", "-c", "user.email=shorts-bot@users.noreply.github.com", "commit", "-qm", "sync code"], cwd=wd)
subprocess.run(["git", "pull", "--rebase", "-q"], cwd=wd)
subprocess.run(["git", "push"], cwd=wd, check=True)
print("synced to", repo)
wk = Path(tempfile.mkdtemp())                         # redeploy the Worker (its secrets persist)
(wk / "worker.js").write_text((Path(__file__).parent / "worker.js").read_text())
(wk / "wrangler.toml").write_text('name = "shorts-orchestrator"\nmain = "worker.js"\ncompatibility_date = "2025-01-01"\n')
subprocess.run(["npx", "--yes", "wrangler", "deploy"], cwd=wk, check=True)
print("worker redeployed")
