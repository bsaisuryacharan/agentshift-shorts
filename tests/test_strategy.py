from datetime import UTC, date, datetime, timedelta

from app import strategy

GOAL = {"views": 1_000_000, "start": "2026-10-30", "deadline": "2026-11-29"}


def snaps(start_views, per_day, days):
    t0 = datetime(2026, 10, 30, 6, tzinfo=UTC)
    return [(t0 + timedelta(hours=6 * i), int(start_views + per_day * i / 4)) for i in range(days * 4 + 1)]


def test_progress_behind_and_on_track():
    slow = strategy.progress(snaps(5600, 500, 3), GOAL, today=date(2026, 11, 2))
    assert slow["gained"] == 1500 and slow["pace_per_day"] == 500 and not slow["on_track"]
    assert slow["needed_per_day"] == (1_000_000 - 1500) // 27 and slow["days_left"] == 27
    fast = strategy.progress(snaps(5600, 60_000, 3), GOAL, today=date(2026, 11, 2))
    assert fast["on_track"] and fast["projected"] >= 1_000_000


def test_no_measurements_yet():
    p = strategy.progress([], GOAL, today=date(2026, 10, 30))
    assert p["measured"] is False and "measuring starts" in strategy.status_line({"progress": p})


def test_plan_doubles_down_on_winners_and_raises_volume_when_behind():
    shorts = [{"title": "Space Is Too Big For Your Brain", "views": 1689, "age_h": 300}, {"title": "These 4 Brain Facts Sound Fake", "views": 1110, "age_h": 330},
              {"title": "5 AI Prompts 99% of People Don't Know", "views": 21, "age_h": 400}, {"title": "Grandma phone tool", "views": 24, "age_h": 410}]
    p = strategy.plan({"on_track": False}, shorts, {"scale": 7.4, "ranked": 5.9})
    assert p["shorts_per_day"] == 2 and p["winners"][0]["title"].startswith("Space") and p["flops"][0]["views"] == 21
    assert "space" in p["focus_words"] and p["best_formats"][0] == "scale"
    assert strategy.plan({"on_track": True}, shorts)["shorts_per_day"] == 1


def test_report_reads_well():
    st = {"progress": strategy.progress(snaps(5600, 500, 3), GOAL, today=date(2026, 11, 2)), "actions": ["Make 2 Shorts a day."]}
    r = strategy.report(st)
    assert "1,000,000" in r and "BEHIND" in r and "• Make 2 Shorts a day." in r
