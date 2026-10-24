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


def test_stills_keywords_drop_style_words():
    from app import stills
    assert stills.keywords("Photoreal cinematic aerial view of a solar flare erupting from the sun, dramatic lighting") == "solar flare"


def test_generate_falls_back_to_real_photos(monkeypatch, tmp_path):
    from app import stills
    monkeypatch.setattr("time.sleep", lambda s: None)
    monkeypatch.setattr(stills, "_DEAD", set())
    monkeypatch.setattr(stills, "_MISSES", {})
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "x")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "y")
    monkeypatch.setattr(stills, "flux", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("429")))
    monkeypatch.setattr(stills, "pollinations", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("402")))
    monkeypatch.setattr(stills, "nasa_still", lambda p, d: (d, {}))
    assert stills.generate("solar flare", tmp_path / "a")[1] == "nasa-photo"
    monkeypatch.setattr(stills, "nasa_still", lambda p, d: (_ for _ in ()).throw(RuntimeError("none")))
    monkeypatch.setattr(stills, "commons", lambda q, d: (d, {}))
    assert stills.generate("solar flare", tmp_path / "b")[1] == "commons-photo"


def test_generate_never_raises_texture_is_last_resort(monkeypatch, tmp_path):
    from app import stills
    monkeypatch.setattr("time.sleep", lambda s: None)
    monkeypatch.setattr(stills, "_DEAD", set())
    monkeypatch.setattr(stills, "_MISSES", {})
    for n in ("flux", "pollinations", "nasa_still"):
        monkeypatch.setattr(stills, n, lambda *a, **k: (_ for _ in ()).throw(RuntimeError("out")))
    monkeypatch.setattr(stills, "commons", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("none")))
    f, prov = stills.generate("intricate electrical substation", tmp_path / "t")
    assert prov == "texture-fallback" and f.exists()
    im = cv2.imread(str(f))
    assert im.shape == (1920, 1080, 3)


def test_ask_retries_malformed_json_once(monkeypatch):
    calls = []

    def fake_call(p, system, user, image):
        calls.append(p)
        return "not json" if len(calls) == 1 else '{"ok": true}'

    monkeypatch.setattr(auto, "_providers", lambda: ["gemini"])
    monkeypatch.setattr(auto, "_call", fake_call)
    assert auto.ask("s", "u") == ({"ok": True}, "gemini") and calls == ["gemini", "gemini"]


def test_finish_survives_unavailable_judge(monkeypatch, tmp_path):
    import types
    run_dir = tmp_path / "x"
    run_dir.mkdir()
    fake = types.SimpleNamespace(run=lambda sp, out: {"checks": {"safe": "pass"}})
    monkeypatch.setitem(__import__("sys").modules, "app.produce", fake)
    monkeypatch.setattr("app.produce", fake, raising=False)
    monkeypatch.setattr(auto, "judge", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no judge")))
    ok, notes, rd, j = auto.finish({"id": "x", "beats": []}, "groq", tmp_path, False, None)
    assert ok is False and j is None and "judge unavailable" in notes[0]


def test_word_time_matches_glued_tts_boundaries():
    from app import voice
    timing = {"segments": [{"key": "b", "words": [{"w": "In 1960", "s": 0.5, "e": 1.0}, {"w": "scientists", "s": 1.1, "e": 1.5}]}]}
    assert voice.word_time(timing, "b", "1960") == 0.5 and voice.word_time(timing, "b", "In") == 0.5 and voice.word_time(timing, "b", "scientists") == 1.1


def test_validate_accepts_type_key_for_hud_elements():
    spec = {"id": "x", "title": "t", "sources": {"a": "b"}, "beats": [{"key": f"b{i}", "img": f"s{i}", "prompt": "an old brass watch", "say": " ".join(["word"] * 12),
            "hud": [{"type": "bubble", "text": "what if?", "at": "word"}]} for i in range(7)]}
    errs = auto.validate_spec(spec, "facts")
    assert not any("bad hud type" in e for e in errs) and spec["beats"][0]["hud"][0]["t"] == "bubble"


def test_run_parks_early_when_pictures_cannot_be_sourced(monkeypatch, tmp_path):
    from app import stills
    spec = {"id": "x", "title": "t", "sources": {}, "beats": [{"key": "a", "say": "word"}]}
    monkeypatch.setattr(auto, "facts_for", lambda *a, **k: {"url": "u", "text": "t"})
    monkeypatch.setattr(auto, "write_spec", lambda *a, **k: (dict(spec), "groq"))
    monkeypatch.setattr(auto, "too_similar", lambda s: 0.0)

    def fake_finish(*a, **k):
        stills.TEXTURED.extend(["a", "b", "c"])
        return False, ["hard gate failed: freeze"], tmp_path, None

    monkeypatch.setattr(auto, "finish", fake_finish)
    sent = []
    monkeypatch.setattr(auto, "telegram", lambda text, video=None, chat=None: sent.append(text) or True)
    assert auto.run("topic", None, tmp_path) == 4 and "quotas" in sent[0]
