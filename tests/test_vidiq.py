import json
from datetime import date

from app import insights, vidiq


def snap(tmp_path, fetched="2026-10-25"):
    p = tmp_path / "vidiq.json"
    p.write_text(json.dumps({"fetched": fetched, "patterns": ["Short questions win."],
                             "keywords": [{"term": "space fun facts", "monthly": 14669, "competition": 45, "growth_pct": 25.8},
                                          {"term": "crowded term", "monthly": 90000, "competition": 90, "growth_pct": 0}],
                             "outliers": [{"title": "Why X falls", "views": 1600000, "subs": 24000, "breakout": 17}]}))
    return p


def test_hint_uses_low_competition_terms_and_outliers(tmp_path):
    h = vidiq.hint(path=snap(tmp_path))
    assert "space fun facts" in h and "crowded term" not in h and "Why X falls" in h


def test_stale_or_missing_snapshot_gives_nothing(tmp_path, monkeypatch):
    assert vidiq.hint(path=tmp_path / "none.json") == ""
    old = snap(tmp_path, fetched="2020-01-01")
    assert vidiq.hint(path=old) == "" and vidiq.topic_ideas(path=old) == []


def test_age_days():
    assert vidiq.age_days({"fetched": "2026-10-20"}, today=date(2026, 10, 25)) == 5


def test_committed_snapshot_is_valid():
    d = vidiq.load()
    assert d["keywords"] and d["outliers"] and d["patterns"]


def test_insights_hint_includes_vidiq(monkeypatch, tmp_path):
    monkeypatch.setattr(vidiq, "PATH", snap(tmp_path))
    monkeypatch.setattr(vidiq, "hint", lambda *a, **k: "VIDIQ-LINE")
    assert insights.hint().endswith("VIDIQ-LINE")


def test_hint_leads_with_channel_results(tmp_path):
    p = snap(tmp_path)
    d = json.loads(p.read_text())
    d["channel"] = {"findings": ["Space beats AI tutorials."], "direction": "Space Shorts.", "visual_level": "Cinematic."}
    p.write_text(json.dumps(d))
    assert vidiq.hint(path=p).startswith("vidIQ market data".replace("vidIQ market data", "This channel's own results"))


def test_committed_snapshot_has_channel_direction():
    ch = vidiq.load()["channel"]
    assert ch["findings"] and ch["direction"] and ch["visual_level"]
