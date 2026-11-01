import json

from app import refs


def test_video_id_from_any_link():
    for u in ("https://youtube.com/shorts/tnzcWTxhR9c?si=abc", "https://www.youtube.com/watch?v=tnzcWTxhR9c", "https://youtu.be/tnzcWTxhR9c", "tnzcWTxhR9c"):
        assert refs.video_id(u) == "tnzcWTxhR9c"
    assert refs.video_id("https://example.com/x") is None


def test_add_saves_analysis_only_and_plans_ideas(monkeypatch, tmp_path):
    monkeypatch.setattr(refs, "DIR", tmp_path)
    monkeypatch.setattr(refs, "fetch_meta", lambda vid, key=None, client=None: {"id": vid, "title": "T", "channel": "C", "views": 5})
    monkeypatch.setattr(refs, "fetch_transcript", lambda vid: "a long third-party script " * 50)
    a = {"reuse": "take a machine apart", "why_it_works": ["x", "y"], "adaptations": ["How a jet engine works, taken apart", "How a watch works, taken apart"]}
    r = refs.add("https://youtu.be/tnzcWTxhR9c", note="great", analysis=a)
    saved = json.loads((tmp_path / "tnzcWTxhR9c.json").read_text())
    assert saved["note"] == "great" and "transcript_excerpt" not in saved and "third-party script" not in json.dumps(saved) and r["id"] == "tnzcWTxhR9c"
    assert refs.ideas(tmp_path) == a["adaptations"] and "take a machine apart" in refs.hint(path=tmp_path)
    assert "How a jet engine works" in refs.summary(tmp_path) or "Planned from them: 2" in refs.summary(tmp_path)


def test_picked_subject_crosses_off_its_idea(monkeypatch, tmp_path):
    (tmp_path / "x.json").write_text(json.dumps({"id": "x", "saved": "2026-11-01", "analysis": {"adaptations": ["How a jet engine works, taken apart", "How a mechanical watch works"]}, "adaptations_used": []}))
    assert refs.mark_used("Turbofan jet engine How a jet engine works", tmp_path) == 1
    assert refs.ideas(tmp_path) == ["How a mechanical watch works"]


def test_committed_reference_is_clean():
    r = json.loads((refs.DIR / "tnzcWTxhR9c.json").read_text())
    assert r["analysis"]["adaptations"] and r["analysis"]["avoid"] and "transcript_excerpt" not in r


def test_anatomy_format_and_look():
    from app import formats, looks
    assert "anatomy" in formats.FORMATS and looks.DEFAULT_BY_FORMAT["anatomy"] == "blueprint"
    assert formats.frame("anatomy", "a jet engine") == "Inside a jet engine, part by part"
