import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("provision", ROOT / "deploy" / "provision.py")
prov = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prov)


def test_stage_never_copies_secrets(tmp_path, monkeypatch):
    fake = tmp_path / "proj"
    (fake / "app").mkdir(parents=True)
    (fake / "deploy").mkdir()
    (fake / "app" / "x.py").write_text("x=1")
    (fake / "app" / ".env").write_text("SECRET=1")
    (fake / "token.json").write_text("{}")
    (fake / "deploy" / "orchestrator.yml").write_text("name: o")
    (fake / "pyproject.toml").write_text("")
    monkeypatch.setattr(prov, "ROOT", fake)
    dest = tmp_path / "out"
    dest.mkdir()
    prov.stage(dest)
    names = {p.name for p in dest.rglob("*") if p.is_file()}
    assert "x.py" in names and "orchestrator.yml" in names and ".gitignore" in names
    assert ".env" not in names and "token.json" not in names
    assert ".env" in (dest / ".gitignore").read_text()
