import json

from app import auto, lessons, picker


def test_classify_and_rules_need_recurrence(tmp_path):
    p = tmp_path / "n.jsonl"
    spec = {"id": "x", "title": "t", "format": "ranked"}
    lessons.record(spec, {"hook": 6, "polish": 5}, ["Replace the generic AI render of Voyager"], path=p)
    assert lessons.rules(path=p) == []                       # once is not a pattern
    lessons.record(spec, {"hook": 7, "polish": 6}, ["frame 3 looks AI-generated", "Narration says 23 hours but frame 8 says 21"], path=p)
    r = lessons.rules(path=p)
    assert len(r) == 1 and "named real object" in r[0]
    assert lessons.classify("Narration says 23 hours but frame 8 text says 21") == ["number_mismatch"]


def test_format_boost_averages(tmp_path):
    p = tmp_path / "n.jsonl"
    for f, sc in (("ranked", 6), ("ranked", 8), ("scale", 5)):
        lessons.record({"id": "x", "format": f}, {"a": sc}, [], path=p)
    assert lessons.format_boost(path=p) == {"ranked": 7.0}


def test_best_option_prefers_real_pictures(monkeypatch):
    cov = {"Voyager 1": 0.25, "Aurora": 1.0}
    monkeypatch.setattr(picker, "visual_coverage", lambda subs: cov[subs[0]])
    opts = [{"topic": "Voyager facts", "wiki": "Voyager 1", "subjects": ["Voyager 1"]},
            {"topic": "Why auroras glow", "wiki": "Aurora", "subjects": ["Aurora"]},
            {"topic": "Galaxy Buds", "wiki": "Samsung Galaxy Buds", "subjects": ["Aurora"]},
            {"topic": "Used", "wiki": "Tardigrade", "subjects": ["Aurora"]}]
    best = picker.best_option(opts, {"tardigrade"}, auto._norm_topic)
    assert best["wiki"] == "Aurora"


def test_screen_number_must_match_narration():
    spec = json.loads(open("examples/doomsday.json").read())
    b = spec["beats"][1]
    b["say"] += " It is 4321 km away."
    b["hud"].append({"t": "chip", "text": "987654 km", "at": "away"})
    errs = auto.validate_spec(spec, "987654 4321")
    assert any("987654 is never spoken" in e for e in errs)
