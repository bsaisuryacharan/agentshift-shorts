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


def test_scaled_numbers_count_as_spoken():
    sp = auto._values("It spins 100 million times and weighs 2.5 billion tonnes, about 1,400 km wide.")
    assert auto._said("100000000", sp) and auto._said("2,500,000,000", sp) and auto._said("1400", sp) and not auto._said("21", sp)


def test_hf_repair_and_duplicates_and_long_script():
    from app import gallery_hf
    el = {"t": "hf", "name": "kinetic-type-swap", "vars": {"prefix": "Orbit becomes", "options": ["crowded"] * 20, "accent": "blue", "junk": 1}, "at": "x"}
    gallery_hf.repair(el)
    assert gallery_hf.check(el) == [] and len(el["vars"]["options"]) <= 90


def test_low_coverage_options_are_refused(monkeypatch):
    monkeypatch.setattr(picker, "visual_coverage", lambda subs: 0.33)
    assert picker.best_option([{"topic": "Boltzmann brain", "wiki": "Boltzmann brain", "subjects": ["x"]}], set(), auto._norm_topic) is None
    assert picker.best_option([{"topic": "Boltzmann brain", "wiki": "Boltzmann brain", "subjects": ["x"]}], set(), auto._norm_topic, min_coverage=0) is not None


def test_numbers_need_matching_context_in_facts():
    facts = ("The depth figure is accurate to ± 22 meters. The bottom pressure is 1,086 bar, or eight tons per square inch. "
             "It is about 2,550 km long. As of 2022, 22 crewed descents have been achieved.")
    assert auto._number_supported("1,086", facts, "pressure 1,086 bar")
    assert auto._number_supported("8", facts, "8 tons on every square inch")
    assert auto._number_supported("2,550", facts, "2,550 kilometers long")          # distinctive numbers need no shared word
    assert auto._number_supported("22", facts, "22 crewed descents")
    assert not auto._number_supported("22", facts, "22 humans walked there")
    assert not auto._number_supported("92", facts, "92% of the crust")


def test_caption_groups_never_end_on_a_dangling_word():
    from app.hud import caption_groups
    ws = [{"w": x} for x in "At 10.6 kilometers deep we found life on every square inch.".split()]
    groups = [" ".join(w["w"] for w in g) for g in caption_groups(ws)]
    assert not any(g.split()[-1].lower() in ("we", "on", "every", "the", "and") for g in groups), groups


def test_delivered_today_reads_the_ledger(tmp_path, monkeypatch):
    import datetime as dt
    monkeypatch.setattr(auto, "ROOT", tmp_path)
    (tmp_path / "data").mkdir()
    assert not auto.delivered_today()
    auto.record_topic("t", "w", "started")
    assert not auto.delivered_today()
    auto.record_topic("t", "w", "delivered", 7.5)
    assert auto.delivered_today()
