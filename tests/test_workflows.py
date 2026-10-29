from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")
ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("path", sorted((ROOT / "scripts").glob("*.yml")) + [ROOT / "deploy" / "orchestrator.yml"], ids=lambda p: p.name)
def test_workflow_files_parse(path):
    d = yaml.safe_load(path.read_text())
    assert d.get("jobs") and (d.get(True) or d.get("on"))        # a broken file silently loses its triggers on GitHub
