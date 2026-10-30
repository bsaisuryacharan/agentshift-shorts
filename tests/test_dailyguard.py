from datetime import UTC, datetime, timedelta

from app import dailyguard

NOW = datetime(2026, 10, 30, 9, 30, tzinfo=UTC)


def run(i, minutes_ago, status="completed", conclusion="success", event="schedule"):
    return {"id": i, "created_at": (NOW - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%SZ"), "status": status, "conclusion": conclusion, "event": event}


def test_a_second_run_while_the_first_is_active_is_a_duplicate():
    assert dailyguard.duplicate([run(1, 2, "in_progress", None)], 2, NOW)["id"] == 1
    assert dailyguard.duplicate([run(1, 2, "in_progress", None)], 1, NOW) is None          # the first run itself is never a duplicate


def test_old_cancelled_or_failed_runs_do_not_count():
    assert dailyguard.duplicate([run(1, 40)], 5, NOW) is None                               # older than 25 minutes
    assert dailyguard.duplicate([run(1, 5, conclusion="cancelled"), run(2, 5, conclusion="failure")], 9, NOW) is None


def test_scheduled_run_after_a_fresh_success_skips_but_a_manual_one_may_repeat():
    done = [run(1, 10)]
    assert dailyguard.duplicate(done, 2, NOW)["id"] == 1
    assert dailyguard.duplicate(done, 2, NOW, manual=True) is None
    assert dailyguard.duplicate([run(1, 3, "queued", None)], 2, NOW, manual=True)["id"] == 1   # a double tap is still caught
