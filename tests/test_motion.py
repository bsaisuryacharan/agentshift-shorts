import json
from pathlib import Path

import cv2
import numpy as np

from app import auto, cinematic, footage, motionbank


def _spec(*says, **kw):
    return {"title": kw.get("title", "Kessler syndrome"), "beats": [{"key": f"b{i}", "say": s, **kw.get("b", {})} for i, s in enumerate(says)]}


def test_bank_is_small_and_text_free_roles():
    m = motionbank.manifest()
    assert len(m) >= 20 and sum(c["kb"] for c in m) < 6000
    assert {c["role"] for c in m} == {"ambient", "wash", "object"}
    assert all((motionbank.BANK / c["file"]).exists() for c in m)


def test_pick_never_repeats_back_to_back_and_skips_objects():
    spec = _spec(*["Satellite debris orbit collision."] * 9)
    fx = motionbank.pick(spec)
    names = [f["clip"] for f in fx]
    assert len(set(names)) <= 5 and all(a != b for a, b in zip(names, names[1:]))
    roles = {c["name"]: c["role"] for c in motionbank.manifest()}
    assert all(roles[n] != "object" for n in names)


def test_pick_respects_explicit_and_off():
    spec = _spec("one", "two", "three")
    spec["beats"][0]["motion"] = "godrays"
    spec["beats"][1]["motion"] = False
    fx = motionbank.pick(spec)
    assert fx[0]["clip"] == "godrays" and fx[1] is None and fx[2]


def test_mood_inference():
    assert "space" in motionbank.mood_of("A satellite in orbit hits debris")
    assert motionbank.mood_of("nothing special here") == ["tech"]


def test_blend_keeps_shape_and_brightens_only_with_screen():
    f = np.full((64, 48, 3), 60, np.uint8)
    c = np.full((64, 48, 3), 200, np.uint8)
    out = motionbank.blend(f, c, 0.5, "screen")
    assert out.shape == f.shape and out.mean() > f.mean()
    assert np.array_equal(motionbank.blend(f, c, 0.0, "screen"), f)


def test_footage_terms_and_search_floor(monkeypatch):
    assert footage._terms("the asteroid impact with NASA") == {"asteroid", "impact"}
    rows = [{"nasa_id": "a", "title": "Asteroid impact test", "description": "an impact", "keywords": []},
            {"nasa_id": "b", "title": "Bees", "description": "asteroid impact", "keywords": []}]
    monkeypatch.setattr(footage, "_query", lambda q: rows)
    got = footage.search("asteroid impact")
    assert [g["id"] for g in got] == ["a"]            # the first word must be in the title/keywords


def test_validate_sanitises_footage_and_motion():
    spec = {"id": "x", "title": "t", "sources": {"a": "b"}, "beats": []}
    beats = [{"key": f"b{i}", "img": f"s{i}", "prompt": "p", "say": " ".join(["word"] * 12), "hud": [{"t": "bubble", "text": "what if?", "at": "word"}],
              "footage": "asteroid impact", "motion": "nope"} for i in range(7)]
    spec["beats"] = beats
    auto.validate_spec(spec, "facts")
    assert sum(1 for b in beats if "footage" in b) == 2 and all("motion" not in b for b in beats)


def test_cinematic_renders_video_and_motion_shots(tmp_path):
    (tmp_path / "img").mkdir()
    for n in ("a", "b"):
        cv2.imwrite(str(tmp_path / "img" / f"{n}.jpg"), np.random.randint(0, 255, (400, 225, 3), np.uint8))
    vw = cv2.VideoWriter(str(tmp_path / "v.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), 24, (540, 960))
    for i in range(30):
        vw.write(np.full((960, 540, 3), i * 8, np.uint8))
    vw.release()
    sl = {"total": 4, "shots": [{"img": "img/a.jpg", "start": 0, "fx": {"clip": "aurora", "blend": "screen", "op": 0.5}},
                                {"img": "img/b.jpg", "start": 2, "video": "v.mp4", "zoom": 1.08, "fx": {"clip": "aurora", "blend": "screen", "op": 0.5}}]}
    c = cinematic.Cinematic(sl, tmp_path)
    for t in (0.5, 1.9, 2.2, 3.5):
        f = c.frame(int(t * 30))
        assert f.shape == (1920, 1080, 3)


def test_insights_hint_is_advisory_and_bounded(tmp_path, monkeypatch):
    from app import insights
    (tmp_path / "latest_channel_analytics.json").write_text(json.dumps({"status": "ok", "current_period": {"start": "a", "end": "b", "short_rows": 1,
        "summary": {"views": 10, "averageViewDuration": 20, "averageViewPercentage": 61.0, "netSubscribers": 2}}}))
    (tmp_path / "latest_trend_report.json").write_text(json.dumps({"region": "US", "signals": [{"title": "Black holes #shorts", "metric": 5}, {"title": "பிளாக்", "metric": 9}]}))
    d = insights.build(tmp_path)
    assert d["trending"] == ["Black holes"] and d["channel"]["caveat"] == "tiny sample"
    monkeypatch.setattr(insights, "OUT", tmp_path / "i.json")
    (tmp_path / "i.json").write_text(json.dumps(d))
    assert "tiny sample" in insights.hint() and len(insights.hint()) <= 600
    monkeypatch.setattr(insights, "OUT", tmp_path / "missing.json")
    assert insights.hint() == ""


def test_validate_rejects_people_prompts_but_allows_silhouettes():
    def spec(prompt):
        return {"id": "x", "title": "t", "sources": {"a": "b"}, "beats": [{"key": f"b{i}", "img": f"s{i}", "prompt": prompt, "say": " ".join(["word"] * 12),
                "hud": [{"t": "bubble", "text": "what if?", "at": "word"}]} for i in range(7)]}
    assert any("shows a person" in e for e in auto.validate_spec(spec("photoreal portrait of an old scientist, 9:16"), "f"))
    assert not any("shows a person" in e for e in auto.validate_spec(spec("silhouette of an astronaut from behind facing a huge dish"), "f"))
    assert not any("shows a person" in e for e in auto.validate_spec(spec("macro of a brass pocket watch on a desk"), "f"))


def test_write_spec_rotates_provider_and_run_survives_writer_failure(monkeypatch, tmp_path):
    prefers = []

    def bad_ask(system, user, **kw):
        prefers.append(kw["prefer"][0])
        return {"id": "x"}, kw["prefer"][0]

    monkeypatch.setattr(auto, "ask", bad_ask)
    try:
        auto.write_spec("t", {"url": "u", "text": "facts"})
        raise AssertionError("expected failure")
    except RuntimeError:
        pass
    assert prefers == ["groq", "groq", "gemini", "gemini", "openrouter"]
    monkeypatch.setattr(auto, "write_spec", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("bad json")))
    monkeypatch.setattr(auto, "facts_for", lambda *a, **k: {"url": "u", "text": "t"})
    sent = []
    monkeypatch.setattr(auto, "telegram", lambda text, video=None, chat=None: sent.append(text) or True)
    assert auto.run("topic", None, tmp_path) == 2            # every attempt failed -> parked message, no crash
    assert any("Parked" in s for s in sent)
