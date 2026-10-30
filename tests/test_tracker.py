import datetime as dt
import json

from app import tracker

TODAY = dt.date(2026, 10, 30)


def ledger(tmp_path, rows):
    p = tmp_path / "topics.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows))
    return p


def test_same_subject_in_other_words_is_a_repeat(tmp_path):
    p = ledger(tmp_path, [{"date": "2026-10-29", "topic": "Nobody can explain the Mariana Trench", "wiki": "Mariana Trench", "outcome": "delivered"},
                          {"date": "2026-10-30", "topic": "How Hubble became the eye", "wiki": "Hubble Space Telescope", "outcome": "started"}])
    assert tracker.repeat_of("Mariana Trench", path=p, today=TODAY)["outcome"] == "delivered"
    assert tracker.repeat_of("Hubble Deep Field", path=p, today=TODAY)["wiki"] == "Hubble Space Telescope"        # shares the distinctive word
    assert tracker.repeat_of("James Webb Space Telescope", path=p, today=TODAY) is None                            # 'space' and 'telescope' alone never match
    assert tracker.repeat_of("Black hole", path=p, today=TODAY) is None


def test_outcome_decides_how_long_a_subject_stays_blocked(tmp_path):
    p = ledger(tmp_path, [{"date": "2026-10-20", "wiki": "Voyager 1", "topic": "t", "outcome": "parked"},
                          {"date": "2026-10-20", "wiki": "Krakatoa", "topic": "t", "outcome": "draft"},
                          {"date": "2025-01-01", "wiki": "Tardigrade", "topic": "t", "outcome": "delivered"}])
    assert tracker.repeat_of("Voyager 1", path=p, today=TODAY) is None          # a failed try may be retried after 3 days
    assert tracker.repeat_of("Krakatoa", path=p, today=TODAY) is not None       # a draft blocks for 90 days
    assert tracker.repeat_of("Tardigrade", path=p, today=TODAY) is not None     # a delivered Short blocks forever


def test_covered_lists_newest_first(tmp_path):
    p = ledger(tmp_path, [{"date": "2026-10-28", "wiki": "A thing", "topic": "t", "outcome": "draft"}, {"date": "2026-10-29", "wiki": "Mariana Trench", "topic": "t", "outcome": "delivered"}])
    assert tracker.covered(path=p, today=TODAY)[0] == "Mariana Trench (delivered 2026-10-29)"
