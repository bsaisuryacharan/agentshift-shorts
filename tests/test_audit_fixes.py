"""Regression tests for the 2026-11-10 audit: the learning loop saw only the 12 OLDEST Shorts, topics were ranked by stock-footage coverage, styles were chosen by format only."""
import json
import random
from datetime import UTC, datetime, timedelta

from app import auto, formats, learning, looks, monitor, picker, strategy, stylemap, targets, topicscore

# the channel's real results on 2026-11-10 (title, views, age in hours)
REAL = [("Space Is Too Big For Your Brain", 1692, 587), ("These 4 Brain Facts Sound Fake (But They're True)", 1115, 588), ("Inside a Submarine: 5 Systems", 1100, 200),
        ("The Antarctic Ozone Hole: Myth vs. Fact", 980, 210), ("What If Jupiter's Magnetic Shield Protected Earth?", 873, 330), ("How the Turing Test Works", 511, 90),
        ("4 Extreme CMB Facts", 55, 70), ("Solar Sails: Not Flimsy Curtains", 39, 300), ("The 600 Billion Dollar Bug", 37, 100), ("5 AI Prompts 99% of People Don't Know", 24, 687),
        ("3 FREE AI Tricks to Get More Interview Calls", 32, 660), ("What If Grandma Could Just ASK Her Phone? Free AI Tool", 33, 693)]
SHORTS = [{"title": t, "views": v, "age_h": a} for t, v, a in REAL]


def test_topic_classes():
    assert topicscore.topic_class("What if Krakatoa erupted today?") == "what_if"
    assert topicscore.topic_class("Inside a Submarine, 5 Systems") == "inside_machine"
    assert topicscore.topic_class("5 AI Prompts 99% of People Don't Know") == "ai_tips"
    assert topicscore.topic_class("The truth about the Antarctic ozone hole") == "myth_fact"
    assert topicscore.topic_class("Cosmic Microwave Background") == "jargon_science"
    assert topicscore.topic_class("something plain") == "general"


def test_curiosity_prefers_familiar_nouns_and_punishes_jargon():
    assert topicscore.curiosity("Inside a Submarine, 5 Systems") > topicscore.curiosity("4 extreme facts about the Cosmic Microwave Background")
    assert topicscore.curiosity("What if the Moon vanished?") > topicscore.curiosity("How the NASA Program Office grew its centre")
    assert topicscore.curiosity("5 AI prompts nobody knows") < topicscore.curiosity("Space is too big for your brain")


def test_class_stats_shrink_and_cap():
    cs = topicscore.class_stats(SHORTS)
    assert all(abs(v["boost"]) <= topicscore.MAX_BOOST for v in cs.values())
    assert cs["ai_tips"]["boost"] < 0 < cs["inside_machine"]["boost"] or cs["ai_tips"]["boost"] < cs["myth_fact"]["boost"]
    one = topicscore.class_stats([{"title": "What if X", "views": 10_000_000, "age_h": 900}, {"title": "plain", "views": 10, "age_h": 900}])
    assert abs(one["what_if"]["boost"]) < topicscore.MAX_BOOST + 1e-9                       # a single outlier cannot swing the pick unboundedly


def test_format_of_titles():
    assert topicscore.format_of("What If Jupiter's Magnetic Shield Protected Earth?") == "what_if"
    assert topicscore.format_of("Inside a Submarine: 5 Systems") == "anatomy"
    assert topicscore.format_of("The Antarctic Ozone Hole: Myth vs. Fact") == "myth_vs_fact"
    assert topicscore.format_of("Space Is Too Big For Your Brain") == "scale"
    assert topicscore.format_of("zzz") == "other"


def _row(i, views, hours_ago, now):
    pub = (now - timedelta(hours=hours_ago)).isoformat().replace("+00:00", "Z")
    return {"spec_id": None, "video_id": f"v{i}", "title": f"Short {i}", "views": views, "likes": 1, "comments": 0, "published_at": pub, "channel_id": "c"}


def test_summarise_keeps_every_short_newest_first():
    now = datetime(2026, 11, 10, tzinfo=UTC)
    rows = [_row(i, 100 + i, 24 * (30 - i), now) for i in range(30)]          # i=0 is the OLDEST (30 days), i=29 the newest (1 day)
    perf = monitor.summarise(rows, 17, now)
    assert len(perf["shorts"]) == 30                                           # the old code kept only shorts[-12:]
    ages = [s["age_h"] for s in perf["shorts"]]
    assert ages == sorted(ages) and perf["shorts"][0]["video_id"] == "v29"    # newest first
    assert perf["cohort"]["n"] >= 1 and all("rel" in s for s in perf["shorts"])


def test_relative_status_has_a_gradient_where_the_million_target_had_none():
    cohort = {"median": 200}
    assert targets.relative(2_000, 720, cohort) == "breakout"
    assert targets.relative(400, 720, cohort) == "above"
    assert targets.relative(200, 720, cohort) == "typical"
    assert targets.relative(20, 720, cohort) == "below"
    assert targets.relative(5, 2, cohort) == "too_early"
    assert targets.status(1692, 587)["status"] == "far_behind"                 # the old absolute view: every Short is "far behind"


def test_lessons_key_by_video_and_recover_features_from_titles(tmp_path):
    now = datetime.now(UTC)
    perf = tmp_path / "performance.jsonl"
    rows = []
    for i, (t, v, a) in enumerate(REAL):
        pub = (now - timedelta(hours=a + 100)).isoformat().replace("+00:00", "Z")
        rows.append({"spec_id": None, "video_id": f"v{i}", "title": t, "views": v, "published_at": pub})
    perf.write_text("\n".join(json.dumps(r) for r in rows))
    out = learning.lessons(perf, tmp_path / "none.jsonl")
    assert out and any("topic type" in x for x in out)                        # before: all spec_id-null rows collapsed into one, so no lesson could ever form
    assert not any("'?'" in x for x in out)


def test_stylemap_fits_topic_and_never_repeats_the_last_two():
    spec = {"title": "Inside a Submarine, 5 Systems", "beats": [{"say": "A submarine is a machine."}]}
    a = stylemap.choose(spec, "anatomy", [], random.Random(1), recent=[])
    assert a["class"] == "inside_machine" and a["look"] in ("blueprint", "explainer-diagram", "graphite-ui") and a["lemo_style"]
    recent = [{"look": "blueprint", "theme": "cool"}, {"look": "explainer-diagram", "theme": "cool"}]
    for seed in range(20):
        b = stylemap.choose(spec, "anatomy", [], random.Random(seed), recent=recent)
        assert b["look"] not in ("blueprint", "explainer-diagram") and b["look"] in looks.LOOKS


def test_stylemap_spreads_themes():
    spec = {"title": "Space is too big", "beats": []}
    recent = [{"look": "x", "theme": "cool"}, {"look": "y", "theme": "cool"}, {"look": "z", "theme": "cool"}]
    t = {stylemap.choose(spec, "scale", [], random.Random(s), recent=recent)["theme"] for s in range(10)}
    assert "cool" not in t                                                     # three coolers in a row: the next is not cool (59 of 66 recent Shorts were)


def test_stylemap_exploits_a_look_that_worked():
    spec = {"title": "What if the Moon vanished?", "beats": []}
    feats = {f"s{i}": {"spec_id": f"s{i}", "look": "paper-cut"} for i in range(3)} | {f"t{i}": {"spec_id": f"t{i}", "look": "graphite-ui"} for i in range(3)}
    shorts = [{"spec_id": f"s{i}", "views": 5000, "age_h": 400} for i in range(3)] + [{"spec_id": f"t{i}", "views": 50, "age_h": 400} for i in range(3)]
    picks = [stylemap.choose(spec, "what_if", shorts, random.Random(s), recent=[], feats=feats)["look"] for s in range(40)]
    assert picks.count("paper-cut") > picks.count("graphite-ui")


def test_new_looks_are_vendored_and_render():
    for name in ("time-travel", "paper-cut", "ink-line", "swiss-kinetic"):
        assert name in looks.LOOKS and (looks.LIB / name / "STYLE.md").exists()
        assert looks.background(name).shape == (1920, 1080, 3)
    for fmt, cands in looks.CANDIDATES.items():
        assert all(c in looks.LOOKS for c in cands), fmt


def test_format_bandit_follows_results_but_keeps_exploring():
    boost = {"anatomy": 1.2, "what_if": 0.9, "scale": 0.8, "timeline": -1.0, "story": -1.0}
    rng = random.Random(3)
    picks = [formats.choose(["how_it_works", "ranked"], rng, boost) for _ in range(400)]
    assert picks.count("anatomy") + picks.count("what_if") > picks.count("timeline") + picks.count("story")
    assert len(set(picks)) >= 6 and "how_it_works" not in picks and "ranked" not in picks


def test_picker_ranks_by_curiosity_not_only_footage(monkeypatch):
    monkeypatch.setattr(picker, "visual_coverage", lambda subjects: 1.0)
    monkeypatch.setattr(picker, "live_shorts", lambda: SHORTS)
    opts = [{"topic": "4 extreme facts about the Cosmic Microwave Background", "wiki": "Cosmic microwave background", "subjects": ["a"]},
            {"topic": "Inside a Submarine, 5 Systems", "wiki": "Submarine", "subjects": ["a"]}]
    best = picker.best_option(opts, set(), lambda s: s.lower())
    assert best["wiki"] == "Submarine"


def test_writer_cannot_name_a_picture_like_a_video_file():
    spec = {"beats": [{"key": "b1", "img": "s1.mp4"}, {"key": "b2", "img": "s2.jpg"}, {"key": "b3", "img": "s3"}]}
    auto._normalise_imgs(spec)
    assert [b["img"] for b in spec["beats"]] == ["s1.jpg", "s2.jpg", "s3.jpg"]


def test_strategy_reports_the_gap_honestly_and_carries_a_ladder():
    prog = {"goal": 1_000_000, "deadline": "2026-11-29", "days_left": 19, "measured": True, "gained": 4873, "pct": 0.49, "needed_per_day": 49756, "pace_per_day": 284,
            "projected": 10571, "on_track": False, "subs": 17}
    assert "gap" in strategy.status_line({"progress": prog})
    p = strategy.plan(prog, [dict(s, rel="x") for s in SHORTS], {})
    assert p["ladder"][0]["name"] == "typical Short" and p["cohort"]["median"] and p["win_classes"] is not None
    assert "Step goals" in strategy.report({"progress": prog, "ladder": p["ladder"], "actions": ["x"]})
