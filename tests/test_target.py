import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from app import learning, monitor, orchestrator as o, scorecard, targets


def test_target_status_follows_the_curve():
    assert targets.status(100, 0.4)["status"] == "too_early"
    assert targets.status(400_000, 24)["status"] == "on_track"
    assert targets.status(120_000, 24)["status"] == "behind"
    assert targets.status(40_000, 24)["status"] == "far_behind"
    assert targets.status(5_000, 72)["status"] == "far_behind"
    assert targets.status(350_000, 24)["projected_30d"] == 1_000_000


def test_ypp_progress_uses_published_thresholds():
    y = targets.ypp_progress(8, 5417, 1)
    assert y["tier2_ads"]["subs_pct"] == 0.8 and not y["tier2_ads"]["views_ok"]
    y = targets.ypp_progress(1200, 11_000_000, 5)
    assert y["tier2_ads"]["subs_ok"] and y["tier2_ads"]["views_ok"] and y["tier1_fan_funding"]["uploads_ok"]


def test_stage_grades_and_weakest_stage():
    scores = {"hook": 9.5, "accuracy": 9, "originality": 8, "payoff": 8, "visual_quality": 5, "visual_variety": 6, "consistency": 7, "polish": 7, "hierarchy": 8, "policy": 10}
    st = scorecard.stages(scores)
    assert st["hook"]["grade"] == "A" and st["visuals"]["grade"] == "D" and st["policy"]["grade"] == "A"
    spec = {"theme": "cool", "sources": {"a": "https://x"}, "beats": [{"say": "w " * 80, "img": "s0", "hud": []}]}
    card = scorecard.build(spec, Path("/nonexistent"), scores, features_path=Path("/nonexistent/f.jsonl"))
    assert card["weakest"] == "visuals" and not card["on_target"] and "real pictures" in card["fix_first"]


def test_policy_hard_checks(tmp_path):
    spec = {"theme": "cool", "sources": {}, "beats": [{"say": "w " * 80, "img": "s0", "hud": []}]}
    (tmp_path / "img").mkdir()
    (tmp_path / "img" / "credits.json").write_text(json.dumps({"a.jpg": {"file": "F", "artist": "x"}}))        # no licence, no url
    (tmp_path / "manifest.json").write_text(json.dumps({"video_s": 75}))
    card = scorecard.build(spec, tmp_path, {"hook": 8}, features_path=tmp_path / "none.jsonl")
    failed = {c["check"] for c in card["policy"]["checks"] if c["hard"] and not c["ok"]}
    assert failed == {"sources", "third_party_credits", "length_under_60s"} and not card["policy"]["ok"]


def test_repeated_template_warning(tmp_path):
    f = tmp_path / "f.jsonl"
    f.write_text("\n".join(json.dumps({"theme": "cool", "beats": 8}) for _ in range(3)))
    spec = {"theme": "cool", "sources": {"a": "https://x"}, "beats": [{"say": "w " * 80, "hud": []}] * 8}
    card = scorecard.build(spec, tmp_path, {"hook": 8}, features_path=f)
    assert any(c["check"] == "not_a_repeated_template" and not c["ok"] for c in card["policy"]["checks"])


def test_playbook_needs_enough_history_then_reports_a_gap(tmp_path):
    now = datetime.now(UTC)
    fp, pp = tmp_path / "f.jsonl", tmp_path / "p.jsonl"
    assert learning.lessons(pp, fp) == []
    for sid, mood, views in (("a", "space", 50000), ("b", "space", 60000), ("c", "history", 4000), ("d", "history", 5000)):
        fp.open("a").write(json.dumps({"spec_id": sid, "mood": mood, "theme": "cool", "hook_words": "<=7", "hf": 2}) + "\n")
        pp.open("a").write(json.dumps({"spec_id": sid, "views": views, "published_at": (now - timedelta(hours=100)).isoformat()}) + "\n")
    out = learning.lessons(pp, fp)
    assert len(out) == 1 and "'space'" in out[0] and "n=4" in out[0]
    pp.write_text("\n".join(json.dumps({"spec_id": s, "views": 9, "published_at": (now - timedelta(hours=2)).isoformat()}) for s in "abcd"))
    assert learning.lessons(pp, fp) == []                    # too young to judge: no lessons


def test_monitor_reads_stats_and_writes_summary(tmp_path):
    (tmp_path / "state").mkdir()
    pub = (datetime.now(UTC) - timedelta(hours=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    (tmp_path / "state" / "42.json").write_text(json.dumps({"projects": {"s1": {"title": "T1", "uploaded": {"id": "v1", "url": "u"}}, "s2": {"title": "no upload"}, "s3": {"title": "T3", "uploaded": {"id": "v3"}}}}))

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/videos"):
            return httpx.Response(200, json={"items": [{"id": "v1", "statistics": {"viewCount": "120000", "likeCount": "9000", "commentCount": "300"},
                                                        "snippet": {"publishedAt": pub, "channelId": "UC1"}}]})
        return httpx.Response(200, json={"items": [{"statistics": {"subscriberCount": "640"}}]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    perf = monitor.run(tmp_path / "state", tmp_path / "perf.jsonl", tmp_path / "ins.json", key="K", client=client)
    assert perf["shorts"][0]["views"] == 120000 and perf["shorts"][0]["status"] == "behind"
    assert perf["not_public_or_missing"] == ["v3"] and perf["ypp"]["subscribers"] == 640
    assert json.loads((tmp_path / "ins.json").read_text())["performance"]["best"]["views"] == 120000
    assert len((tmp_path / "perf.jsonl").read_text().splitlines()) == 1


def test_target_card_before_and_after_data(tmp_path):
    empty = tmp_path / "e.json"
    empty.write_text("{}")
    assert "No uploaded Shorts to measure yet" in o.target_report(empty)
    full = tmp_path / "f.json"
    full.write_text(json.dumps({"weakest_stage": "visuals", "stage_averages": {"visuals": 6.1}, "performance": {
        "updated": "now", "shorts": [{"title": "T", "views": 5000, "age_h": 30, "status": "behind", "projected_30d": 14000}], "on_track": 0, "behind": 1,
        "ypp": targets.ypp_progress(8, 5000, 1), "lessons": ["topic type: 'space' averaged 9 vs 3"]}}))
    card = o.target_report(full)
    for needle in ("1,000,000 views", "5,000 views after 30h", "behind", "0.8% of 1,000", "weakest stage lately is 'visuals'", "Learned so far", "Checked every hour"):
        assert needle in card, needle
