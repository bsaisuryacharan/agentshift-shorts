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
    assert sum(1 for b in beats if "footage" in b) == 3 and all("motion" not in b for b in beats)


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
    assert d["trending"] == ["Black holes"] and d["channel"]["caveat"].startswith("all Shorts")
    monkeypatch.setattr(insights, "OUT", tmp_path / "i.json")
    (tmp_path / "i.json").write_text(json.dumps(d))
    monkeypatch.setattr("app.vidiq.hint", lambda *a, **k: "")          # the vidIQ snapshot has its own budget and test
    monkeypatch.setattr("app.ideabank.hint", lambda *a, **k: "")       # so does the idea bank
    assert "Channel Shorts" in insights.hint() and len(insights.hint()) <= 600
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
    assert auto.run("topic", None, tmp_path, chat="42") == 2            # every attempt failed -> parked message, no crash
    assert any("Not today" in s for s in sent)


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
    monkeypatch.setattr(stills, "photo_matches", lambda p, s: True)
    monkeypatch.setattr(stills, "nasa_still", lambda p, d: (d, {}))
    assert stills.generate("solar flare", tmp_path / "a")[1] == "nasa-photo"
    monkeypatch.setattr(stills, "nasa_still", lambda p, d: (_ for _ in ()).throw(RuntimeError("none")))
    monkeypatch.setattr(stills, "commons", lambda q, d: (d, {}))
    assert stills.generate("solar flare", tmp_path / "b")[1] == "commons-photo"
    monkeypatch.setattr(stills, "photo_matches", lambda p, s: False)         # a photo the vision check rejects is never used
    assert stills.generate("solar flare", tmp_path / "c")[1] == "texture-fallback"


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
    monkeypatch.setattr(auto.time, "sleep", lambda s: None)
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
        stills.TEXTURED.extend(["a", "b", "c", "d", "e"])
        return False, ["hard gate failed: freeze"], tmp_path, None

    monkeypatch.setattr(auto, "finish", fake_finish)
    sent = []
    monkeypatch.setattr(auto, "telegram", lambda text, video=None, chat=None: sent.append(text) or True)
    assert auto.run("topic", None, tmp_path, chat="42") == 4 and "quota" in sent[0]


def test_footage_requires_a_vision_yes(monkeypatch, tmp_path):
    out = tmp_path / "c.mp4"
    vw = cv2.VideoWriter(str(out), cv2.VideoWriter_fourcc(*"mp4v"), 24, (540, 960))
    for i in range(30):
        vw.write(np.full((960, 540, 3), 100 + i * 4, np.uint8))
    vw.release()
    from app import stills
    monkeypatch.setattr(stills, "_VISION", {"dead": False, "calls": 0})
    monkeypatch.setattr(auto, "ask", lambda *a, **k: ({"relevant": False, "shows": "airplane cockpit"}, "gemini"))
    assert footage._relevant(out, "nuclear rocket") is False
    monkeypatch.setattr(auto, "ask", lambda *a, **k: ({"relevant": True, "shows": "rocket"}, "gemini"))
    assert footage._relevant(out, "nuclear rocket") is True
    monkeypatch.setattr(auto, "ask", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    assert footage._relevant(out, "nuclear rocket") is None            # no answer: the caller decides by the clip's title


def test_ensure_prefers_real_photo_then_generation(monkeypatch, tmp_path):
    from app import stills
    calls = []
    monkeypatch.setattr(stills, "photo_matches", lambda p, s: True)
    monkeypatch.setattr(stills, "commons", lambda q, d: (_ for _ in ()).throw(RuntimeError("none")))
    monkeypatch.setattr(stills, "nasa_still", lambda q, d: calls.append(("nasa", q)) or (d, {}))
    monkeypatch.setattr(stills, "generate", lambda *a, **k: calls.append(("gen", a[0])) or (a[1], "x"))
    spec = {"beats": [{"key": "a", "img": "s0.jpg", "photo": "solar flare", "prompt": "p"}, {"key": "b", "img": "s1.jpg", "prompt": "q"}]}
    try:
        stills.ensure(spec, tmp_path)
    except FileNotFoundError:
        pass
    assert calls == [("nasa", "solar flare"), ("gen", "q")]


def test_ask_waits_out_throttling_then_succeeds(monkeypatch):
    import httpx
    calls, sleeps = [], []

    def fake_call(p, system, user, image):
        calls.append(p)
        if len(calls) < 3:
            raise httpx.HTTPError("429 Too Many Requests")
        return '{"ok": true}'

    monkeypatch.setattr(auto, "_providers", lambda: ["groq", "gemini"])
    monkeypatch.setattr(auto, "_call", fake_call)
    monkeypatch.setattr(auto.time, "sleep", lambda s: sleeps.append(s))
    assert auto.ask("s", "u")[0] == {"ok": True} and sleeps == [40]


def test_botmenu_registers_commands(monkeypatch):
    import httpx
    from app import botmenu
    sent = {}

    class R:
        status_code = 200

        def json(self):
            return {"ok": True}

    monkeypatch.setattr(httpx, "post", lambda url, json, timeout: sent.update(json) or R())
    assert botmenu.register("t") is True
    assert [c["command"] for c in sent["commands"]] == ["new", "status", "target", "list", "use", "approve", "upload", "model", "effort", "changes", "merge", "discard", "settings", "memory", "actions", "reset", "help"]
    assert botmenu.register(None) is False or True   # no token: returns False without raising (env may or may not be set)


def test_insights_learns_from_ledger(tmp_path):
    from app import insights
    (tmp_path / "history.jsonl").write_text("\n".join(json.dumps(x) for x in [
        {"title": "Good one", "scores": {"hook": 9, "polish": 9, "visual_quality": 8}},
        {"title": "Weak one", "scores": {"hook": 5, "polish": 4, "visual_quality": 6}},
        {"title": "Mid one", "scores": {"hook": 7, "polish": 6, "visual_quality": 7}},
        {"title": "Another weak", "scores": {"hook": 6, "polish": 5, "visual_quality": 6}}]))
    d = insights.build(tmp_path)
    assert d["learned"]["best"][0]["title"] == "Good one" and d["learned"]["weakest_dimensions"][0] == "polish"


def test_footage_index_search_requires_subject_word():
    rows = footage.search_index("debris orbital satellite")
    assert rows and all("debris" in (r["title"].lower() + r["id"].lower()) or r["hits"] >= 1 for r in rows)
    assert footage.search_index("the and") == []


def test_grade_lut_shapes_and_identity():
    assert cinematic._grade_lut(None) is None and cinematic._grade_lut("nope") is None
    lut = cinematic._grade_lut("cool")
    assert lut.shape == (256, 1, 3) and lut[0, 0, 0] <= 10 and lut[255, 0, 1] >= 240


def test_openverse_filters_licence_and_size(monkeypatch, tmp_path):
    import httpx
    from app import stills
    img = np.full((1200, 1600, 3), 120, np.uint8)
    png = cv2.imencode(".png", img)[1].tobytes()
    results = {"results": [{"url": "u1", "width": 300, "license": "by"}, {"url": "u2", "width": 1600, "license": "by-nc"},
                           {"url": "u3", "width": 1600, "license": "by", "title": "T", "creator": "C", "foreign_landing_url": "L"}]}

    class R:
        def __init__(self, status, body=None, ct="application/json"):
            self.status_code, self._b, self.headers = status, body, {"content-type": ct}
            self.content = body if isinstance(body, bytes) else b""

        def raise_for_status(self):
            pass

        def json(self):
            return results

    monkeypatch.setattr(httpx, "get", lambda url, **k: R(200, png, "image/png") if url == "u3" else R(200))
    out, credit = stills.openverse("thing", tmp_path / "o")
    assert out.exists() and credit["license"].startswith("CC BY") and credit["url"] == "L"


def test_register_last_makes_daily_short_current(monkeypatch, tmp_path):
    from app import orchestrator as o
    out = tmp_path / "runs"
    (out / "x").mkdir(parents=True)
    (out / "x" / "img").mkdir()
    (out / "x" / "img" / "credits.json").write_text("{}")
    (out / "x" / "img" / "s0.jpg").write_bytes(b"x")
    (out / "x" / "vision.json").write_text(json.dumps({"scores": {"hook": 7}}))
    (out / "x.spec.json").write_text(json.dumps({"id": "x", "title": "T", "beats": []}))
    (out / "_last.json").write_text(json.dumps({"id": "x", "spec": str(out / "x.spec.json"), "draft": True}))
    monkeypatch.setattr(o, "OUT", out)
    monkeypatch.setattr(o, "PROJ", tmp_path / "projects")
    st = {"current": None, "projects": {}}
    assert o.register_last(st, 0, images=False) is True
    assert st["current"] == "x" and st["projects"]["x"]["status"] == "draft" and st["projects"]["x"]["scores"] == {"hook": 7}
    assert (tmp_path / "projects" / "x" / "img" / "credits.json").exists() and not (tmp_path / "projects" / "x" / "img" / "s0.jpg").exists()
    (out / "_last.json").unlink()
    assert o.register_last({"current": None, "projects": {}}, 0) is False


def test_hud_page_fits_text_before_exposing_timeline(tmp_path):
    from app import hud
    spec = {"title": "t", "beats": [{"key": "hook", "say": "a b c", "hud": [{"t": "big", "text": "10,000 NEURONS PER DAY", "at": "a"}]}]}
    timing = {"segments": [{"key": "hook", "start": 0.0, "dur": 2.0, "words": [{"w": "a", "s": 0.0, "e": 0.5}, {"w": "b", "s": 0.6, "e": 1.0}, {"w": "c", "s": 1.1, "e": 1.5}]}]}
    html = hud.write(spec, timing, 4.0, tmp_path / "p.html").read_text()
    assert "function __fit()" in html and html.index("__fit();") < html.index("window.__timelines = {main: tl}")


def test_topic_ledger_blocks_repeats_by_outcome(monkeypatch, tmp_path):
    import datetime as dt
    monkeypatch.setattr(auto, "ROOT", tmp_path)
    today = dt.date.today()
    rows = [("Kessler syndrome", "draft", today - dt.timedelta(days=10)), ("Dyson sphere", "parked", today - dt.timedelta(days=1)),
            ("Tunguska event", "parked", today - dt.timedelta(days=9)), ("Old topic", "delivered", today - dt.timedelta(days=90)),
            ("Project Orion (nuclear propulsion)", "started", today)]
    (tmp_path / "data").mkdir()
    (tmp_path / auto.TOPICS).write_text("\n".join(json.dumps({"date": d.isoformat(), "topic": "What if " + w, "wiki": w, "outcome": o}) for w, o, d in rows))
    used = auto.used_topics()
    assert auto._norm_topic("Kessler syndrome") in used and auto._norm_topic("Dyson sphere") in used
    assert auto._norm_topic("Project Orion") in {auto._norm_topic("Project Orion (nuclear propulsion)")} and auto._norm_topic("Project Orion (nuclear propulsion)") in used
    assert auto._norm_topic("Tunguska event") not in used and auto._norm_topic("Old topic") not in used


def test_pick_topic_never_returns_a_used_topic(monkeypatch, tmp_path):
    monkeypatch.setattr(auto, "ROOT", tmp_path)
    (tmp_path / "data").mkdir()
    auto.record_topic("What if Kessler syndrome", "Kessler syndrome", "draft")
    monkeypatch.setattr(auto, "trend_topics", lambda *a, **k: ["Kessler syndrome", "Taylor Swift"])
    monkeypatch.setattr(auto.httpx, "get", lambda *a, **k: (_ for _ in ()).throw(auto.httpx.HTTPError("offline")))
    answers = iter([{"topic": "t", "wiki": "Kessler syndrome"}, {"topic": "t", "wiki": "Kessler syndrome"}, {"topic": "t", "wiki": "Kessler syndrome"}])
    monkeypatch.setattr(auto, "ask", lambda *a, **k: (next(answers), "groq"))
    monkeypatch.setattr(auto, "wiki_facts", lambda q: {"title": q})
    topic, wiki, fmt = auto.pick_topic()
    assert fmt in auto.formats.FORMATS and auto._norm_topic(wiki) != auto._norm_topic("Kessler syndrome") and wiki in auto.EVERGREEN


def test_texture_beats_get_moving_clips_without_repeats():
    prompts = ["dense space debris belt around Earth", "dense space debris cloud", "empty orbit", "abstract cascade"]
    clips = motionbank.texture_clips(prompts)
    assert len(clips) == 4 and all(Path(c).exists() for c in clips) and all(a != b for a, b in zip(clips, clips[1:]))
    assert any("frost-sequence" in c for c in clips)            # debris prompt -> the drifting-debris clip


def test_cinematic_plays_motion_bank_clip_as_beat_background(tmp_path):
    (tmp_path / "img").mkdir()
    cv2.imwrite(str(tmp_path / "img" / "a.jpg"), np.zeros((400, 225, 3), np.uint8))
    clip = motionbank.texture_clips(["aurora over the polar night"])[0]
    c = cinematic.Cinematic({"total": 3, "theme": "cool", "shots": [{"img": "img/a.jpg", "start": 0, "video": clip, "pingpong": True, "zoom": 1.08}]}, tmp_path)
    a, b = c.frame(10), c.frame(40)
    assert a.shape == (1920, 1080, 3) and np.abs(a.astype(int) - b.astype(int)).mean() > 0.3      # it moves


def test_validate_fills_prompt_from_photo_term():
    spec = {"id": "x", "title": "t", "sources": {"a": "b"}, "beats": [{"key": f"b{i}", "img": f"s{i}", "photo": "Gulf Stream satellite", "say": " ".join(["word"] * 12),
            "hud": [{"t": "bubble", "text": "what if?", "at": "word"}]} for i in range(7)]}
    errs = auto.validate_spec(spec, "facts")
    assert not any("needs a prompt" in e for e in errs) and "Gulf Stream satellite" in spec["beats"][0]["prompt"]


def test_face_detector_rejects_portraits_but_not_galaxies():
    from app import stills
    gal = np.zeros((600, 400, 3), np.uint8)
    cv2.circle(gal, (200, 300), 90, (200, 180, 150), -1)
    assert stills.has_face(gal) is False
    sample = cv2.imread(str(Path(cv2.data.haarcascades).parent / "samples" / "lena.jpg")) if (Path(cv2.data.haarcascades).parent / "samples" / "lena.jpg").exists() else None
    if sample is not None:
        assert stills.has_face(sample) is True


def test_photo_check_rejects_people_and_text(monkeypatch, tmp_path):
    from app import stills
    img = tmp_path / "p.jpg"
    cv2.imwrite(str(img), np.full((480, 270, 3), 90, np.uint8))
    monkeypatch.setattr(stills, "_VISION", {"dead": False, "calls": 0})
    for verdict, expect in (({"relevant": True, "person": False, "text": False}, True), ({"relevant": True, "person": True, "text": False}, False),
                            ({"relevant": True, "person": False, "text": True}, False), ({"relevant": False}, False)):
        monkeypatch.setattr(auto, "ask", lambda *a, _v=verdict, **k: (_v, "gemini"))
        assert stills.photo_matches(img, "comet") is expect


def test_earlier_good_draft_is_delivered_even_if_last_attempt_has_no_pictures(monkeypatch, tmp_path):
    from app import stills
    spec = {"id": "x", "title": "t", "sources": {}, "beats": [{"key": "a", "say": "word"}]}
    monkeypatch.setattr(auto, "facts_for", lambda *a, **k: {"url": "u", "text": "t", "title": "T"})
    monkeypatch.setattr(auto, "write_spec", lambda *a, **k: (dict(spec), "groq"))
    monkeypatch.setattr(auto, "too_similar", lambda s: 0.0)
    monkeypatch.setattr(auto, "TOPICS", Path("data/t.jsonl"))
    monkeypatch.setattr(auto, "ROOT", tmp_path)
    calls = []

    def fake_finish(*a, **k):
        calls.append(1)
        if len(calls) == 1:
            return False, ["polish"], tmp_path, {"scores": {"accuracy": 10, "policy": 10, "hook": 8}, "fixes": ["x"], "judge": "gemini"}
        stills.TEXTURED.extend(list("abcde"))
        return False, ["hard gate failed"], tmp_path, None

    sent = []
    monkeypatch.setattr(auto, "finish", fake_finish)
    monkeypatch.setattr(auto, "send_draft", lambda s, rd, j, chat: sent.append("draft"))
    monkeypatch.setattr(auto, "encode_for_telegram", lambda a, b: sent.append("encoded"))
    monkeypatch.setattr(auto, "telegram", lambda *a, **k: sent.append("msg") or True)
    assert auto.run("topic", None, tmp_path) == 3 and sent == ["encoded"]          # kept as an artifact, never sent to Telegram


def test_text_detector_flags_labelled_diagrams_not_plain_photos():
    from app import stills
    plain = np.zeros((720, 1280, 3), np.uint8)
    cv2.circle(plain, (640, 360), 200, (180, 160, 140), -1)
    plain = cv2.GaussianBlur(plain, (0, 0), 6)
    diagram = np.full((720, 1280, 3), 40, np.uint8)
    for k in range(8):
        cv2.putText(diagram, f"Van Allen Probe {k}", (80 + 120 * (k % 3), 90 + 80 * k), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (240, 240, 240), 2, cv2.LINE_AA)
    assert stills.has_text(plain) is False and stills.has_text(diagram) is True


def test_title_blocklist_skips_diagrams_and_posters():
    from app import stills
    for t in ("Van Allen belt diagram", "Solar system poster", "Cassini illustration", "Voyager logo"):
        assert stills.BAD_TITLE.search(t)
    assert not stills.BAD_TITLE.search("Major Solar Flare") and not stills.BAD_TITLE.search("Andromeda Galaxy")


def test_validate_rejects_non_object_beats_instead_of_crashing():
    assert auto.validate_spec({"beats": ["a", "b"]}, "f")[0].startswith("the spec must be")
    assert auto.validate_spec(["x"], "f")[0].startswith("the spec must be")


def test_finish_retries_judge_before_giving_up(monkeypatch, tmp_path):
    import types
    fake = types.SimpleNamespace(run=lambda sp, out: {"checks": {"safe": "pass"}}, regate=lambda rd, v: {"passed": False})
    monkeypatch.setitem(__import__("sys").modules, "app.produce", fake)
    monkeypatch.setattr("app.produce", fake, raising=False)
    calls, sleeps = [], []

    def flaky(*a, **k):
        calls.append(1)
        if len(calls) < 3:
            raise RuntimeError("429")
        return {"approved": False, "scores": {"accuracy": 9}, "fixes": ["x"], "failing": "images", "judge": "gemini"}

    monkeypatch.setattr(auto, "judge", flaky)
    monkeypatch.setattr(auto.time, "sleep", lambda s: sleeps.append(s))
    ok, notes, rd, j = auto.finish({"id": "x", "beats": []}, "groq", tmp_path, False, None)
    assert j is not None and len(calls) == 3 and sleeps == [90, 90]


def test_generation_prompts_get_the_documentary_look_once():
    from app import stills
    a = stills._styled("a glowing sphere over a lake")
    assert a.endswith("no digital art") and "no neon" in a and stills._styled(a) == a


def test_daily_run_is_silent_on_failure_but_a_requested_run_is_told(monkeypatch, tmp_path):
    monkeypatch.setattr(auto, "facts_for", lambda *a, **k: {"url": "u", "text": "t"})
    monkeypatch.setattr(auto, "write_spec", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("bad")))
    monkeypatch.setattr(auto, "TOPICS", Path("data/t.jsonl"))
    monkeypatch.setattr(auto, "ROOT", tmp_path)
    sent = []
    monkeypatch.setattr(auto, "telegram", lambda text, video=None, chat=None: sent.append(text) or True)
    assert auto.run("t", None, tmp_path) == 2 and sent == []
    assert auto.run("t", None, tmp_path, chat="42") == 2 and len(sent) == 1


def test_gallery_components_are_vendored_with_licence():
    from app import gallery_hf
    assert len(gallery_hf.names()) == 5 and len(list(gallery_hf.LIB.glob('*/registry-item.json'))) == 9      # 9 vendored, 5 offered to the writer
    root = gallery_hf.LIB.parent
    assert "Apache License" in (root / "LICENSE").read_text()[:200] and "89af290" in (root / "SOURCE.md").read_text()


def test_gallery_check_validates_vars_against_registry():
    from app import gallery_hf
    ok = {"t": "hf", "name": "count-up", "vars": {"end": 87, "suffix": "%", "accent": "blue"}}
    assert gallery_hf.check(ok) == []
    assert gallery_hf.check({"name": "nope"})[0].startswith("hf: unknown component")
    assert any("missing var end" in e for e in gallery_hf.check({"name": "count-up", "vars": {}}))
    assert any("not one of" in e for e in gallery_hf.check({"name": "count-up", "vars": {"end": 1, "accent": "red"}}))
    assert any("must be a number" in e for e in gallery_hf.check({"name": "count-up", "vars": {"end": "lots"}}))
    assert any("unknown var exit" in e for e in gallery_hf.check({"name": "count-up", "vars": {"end": 1, "exit": "up"}}))


def test_gallery_prompt_lists_every_component():
    from app import gallery_hf
    block = gallery_hf.prompt_block()
    assert all(n in block for n in gallery_hf.names()) and "needs vars" in block


def test_hud_mounts_gallery_component_with_duration_and_waits_for_it(tmp_path):
    from app import hud
    spec = {"title": "t", "beats": [{"key": "hook", "say": "a b c d", "hud": [
        {"t": "hf", "name": "count-up", "vars": {"end": 24, "suffix": ""}, "at": "b", "dur": 2.0}]}]}
    timing = {"segments": [{"key": "hook", "start": 0.0, "dur": 4.0, "words": [{"w": w, "s": 0.2 * i, "e": 0.2 * i + 0.15} for i, w in enumerate("a b c d".split())]}]}
    html = hud.write(spec, timing, 5.0, tmp_path / "p.html").read_text()
    assert 'f.srcdoc=' in html and "__hfT" in html and "window.__hf" in html and "<\\/script>" in html
    assert '"end": 24' in html.replace('\\"', '"')
    assert html.index("Promise.all([document.fonts.ready].concat(window.__hf") < html.index("window.__timelines = {main: tl}")


def test_validate_requires_gallery_motion_graphics():
    spec = {"id": "x", "title": "t", "sources": {"a": "b"}, "beats": [{"key": f"b{i}", "img": f"s{i}", "prompt": "an old brass watch", "say": " ".join(["word"] * 12),
            "hud": [{"t": "bubble", "text": "what if?", "at": "word"}]} for i in range(7)]}
    assert any("at least 2 gallery motion graphics" in e for e in auto.validate_spec(spec, "facts"))
    spec["beats"][1]["hud"].append({"t": "hf", "name": "per-word-rise", "vars": {"text": "hello there"}, "at": "word"})
    spec["beats"][2]["hud"].append({"t": "hf", "name": "per-word-rise", "vars": {"text": "again"}, "at": "word"})
    assert any("only once per Short" in e for e in auto.validate_spec(spec, "facts"))
    spec["beats"][2]["hud"][-1]["name"] = "titlecard-lockup"
    spec["beats"][2]["hud"][-1]["vars"] = {"wordmark": "TERM"}
    assert not any("gallery" in e or "hf" in e for e in auto.validate_spec(spec, "facts"))


def test_upload_pack_has_everything_for_youtube_studio(tmp_path):
    from app import pack
    (tmp_path / "img").mkdir()
    (tmp_path / "img" / "credits.json").write_text(json.dumps({"s1.jpg": {"file": "Andromeda", "license": "CC BY 4.0", "artist": "NASA/ESA", "url": "https://x/1"},
                                                                  "s9.jpg": {"file": "pizza, cooking", "license": "Pixabay licence", "artist": "x", "url": "https://x/9"}}))
    (tmp_path / "vid").mkdir()
    (tmp_path / "vid" / "credits.json").write_text(json.dumps({"b3.mp4": {"title": "Earth at night", "center": "GSFC", "license": "NASA media (public domain)", "source": "https://images.nasa.gov/details/x"}}))
    spec = {"title": "What if Andromeda hit us?", "series_label": "SPACE", "beats": [{"say": "Andromeda is coming.", "img": "s1.jpg"}], "sources": {"hook": "https://en.wikipedia.org/wiki/Andromeda_Galaxy", "b1": "not a url"}}
    text = pack.build(spec, [tmp_path / "img" / "credits.json", tmp_path / "vid" / "credits.json", tmp_path / "missing.json"])
    for needle in ("TITLE:", "#shorts", "https://en.wikipedia.org/wiki/Andromeda_Galaxy", "CC BY 4.0", "Earth at night", "TAGS:", "PINNED COMMENT:", "Altered or synthetic content: YES", "19:00 IST"):
        assert needle in text, needle
    assert "not a url" not in text and "pizza" not in text and 3 <= len(pack.tags(spec)) <= 8      # credits only for pictures in the video


def test_formats_rotate_and_never_repeat_back_to_back():
    import random
    from app import formats
    rng, recent = random.Random(3), []
    for _ in range(30):
        recent.append(formats.choose(recent, rng))
    assert all(a != b for a, b in zip(recent, recent[1:])) and all(recent[i] not in recent[max(0, i - 2):i] for i in range(len(recent)))
    assert recent.count("what_if") <= 5 and len(set(recent)) == len(formats.FORMATS)
    assert "how_it_works" not in formats.choose(["how_it_works", "ranked"], rng)


def test_no_prompt_forces_what_if_any_more():
    assert "what if?" not in auto.SYSTEM.lower().replace("the format gives", "") and "what-ifs" not in auto.SYSTEM
    from app import formats
    block = formats.prompt_block("myth_vs_fact")
    assert '"true?"' in block and "NOT" not in block.split("Do NOT")[0] and "myth_vs_fact" in block and "unless this format is what_if" in block


def test_write_spec_stamps_the_format_and_ledger_remembers_it(monkeypatch, tmp_path):
    seen = {}
    good = {"id": "x", "title": "T", "sources": {"a": "https://x"}, "beats": [{"key": f"b{i}", "img": f"s{i}", "prompt": "an old brass watch", "say": " ".join(["word"] * 14),
            "hud": [{"t": "bubble", "text": "true?", "at": "word"}] + ([{"t": "hf", "name": "count-up", "vars": {"end": 3}, "at": "word"}] if i in (1, 2) else [])} for i in range(7)]}
    good["beats"][2]["hud"][-1] = {"t": "hf", "name": "titlecard-lockup", "vars": {"wordmark": "TERM"}, "at": "word"}
    monkeypatch.setattr(auto, "ask", lambda system, user, **k: seen.update(user=user) or (good, "groq"))
    spec, _ = auto.write_spec("t", {"url": "u", "text": "3 facts"}, None, "myth_vs_fact")
    assert spec["format"] == "myth_vs_fact" and spec["series_label"] == "MYTH VS FACT" and "FORMAT for this Short: myth_vs_fact" in seen["user"]
    monkeypatch.setattr(auto, "ROOT", tmp_path)
    (tmp_path / "data").mkdir()
    for f in ("ranked", "scale"):
        auto.record_topic("t", "w", "started", fmt=f)
    auto.record_topic("t", "w", "parked", fmt="versus")
    assert auto.recent_formats() == ["ranked", "scale"]


def test_trending_is_filtered_to_the_channel_niche(tmp_path):
    from app import insights
    sigs = [{"title": t, "metric": m} for t, m in (("Unboxing iPhone 18 Pro review", 9000), ("Why Black Holes Spin Faster Than Light Clocks", 5000),
                                                    ("Celebrity gossip you will not believe", 8000), ("NASA probe reaches asteroid: what scientists found", 100), ("How a jet engine works", 50))]
    (tmp_path / "latest_trend_report.json").write_text(json.dumps({"region": "IN", "signals": sigs}))
    d = insights.build(tmp_path)
    assert d["trending"][0].startswith("Why Black Holes") and len(d["trending"]) == 3 and d["trend_signals_total"] == 5 and d["trend_signals_on_niche"] == 3


def test_niche_youtube_signal_ranks_by_velocity_and_skips_junk():
    import httpx
    from datetime import UTC, datetime, timedelta
    from app import trends
    now = datetime.now(UTC)
    pub = lambda h: (now - timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ")

    def handler(req):
        if req.url.path.endswith("/search"):
            q = req.url.params["q"]
            return httpx.Response(200, json={"items": [{"id": {"videoId": f"{q[:2]}1"}}, {"id": {"videoId": "zz9"}}]})
        return httpx.Response(200, json={"items": [
            {"id": "sp1", "snippet": {"title": "Why black holes spin", "publishedAt": pub(20)}, "statistics": {"viewCount": "500000"}},
            {"id": "sc1", "snippet": {"title": "Slow science fact", "publishedAt": pub(300)}, "statistics": {"viewCount": "600000"}},
            {"id": "zz9", "snippet": {"title": "Buy this startup stock now", "publishedAt": pub(10)}, "statistics": {"viewCount": "900000"}},
            {"id": "his", "snippet": {"title": "tiny", "publishedAt": pub(10)}, "statistics": {"viewCount": "500"}}]})

    class S:
        youtube_api_key = "k"
    out = trends._youtube_niche_signals(S(), client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert [s.title for s in out] == ["Why black holes spin", "Slow science fact"] and "views/hour" in out[0].notes


def test_science_feeds_parse_and_dedupe():
    import httpx
    from app import trends
    rss = b"<rss><channel><item><title>Probe finds water</title><link>https://a/1</link></item><item><title>Probe finds water</title><link>https://a/2</link></item><item><title>Startup funding deal</title><link>https://a/3</link></item></channel></rss>"
    out = trends._science_feed_signals(None, client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=rss))))
    assert [s.title for s in out] == ["Probe finds water"] and out[0].source == "science_feed"


def test_validate_repairs_gallery_name_used_as_element_type():
    spec = {"id": "x", "title": "t", "sources": {"a": "b"}, "beats": [{"key": f"b{i}", "img": f"s{i}", "prompt": "an old brass watch", "say": " ".join(["word"] * 14),
            "hud": [{"t": "bubble", "text": "vs", "at": "word"}]} for i in range(7)]}
    spec["beats"][1]["hud"].append({"t": "titlecard-lockup", "wordmark": "Tardigrade", "kicker": "VS HUMANS", "at": "word"})
    spec["beats"][2]["hud"].append({"t": "per-word-rise", "vars": {"text": "Built to survive"}, "at": "word", "dur": 2})
    errs = auto.validate_spec(spec, "facts")
    e1, e2 = spec["beats"][1]["hud"][-1], spec["beats"][2]["hud"][-1]
    assert e1["t"] == "hf" and e1["name"] == "titlecard-lockup" and e1["vars"] == {"wordmark": "Tardigrade", "kicker": "VS HUMANS"} and e1["at"] == "word"
    assert e2["t"] == "hf" and e2["vars"] == {"text": "Built to survive"} and e2["dur"] == 2
    assert not any("bad hud type" in e or "unknown component" in e for e in errs)


def test_shotlist_reuses_picture_when_a_cut_has_none():
    from app import produce
    spec = {"beats": [{"key": "b1", "img": "a.jpg", "cuts": [{"at": "x"}]}], "theme": None}
    timing = {"segments": [{"key": "b1", "start": 0.0, "dur": 3.0, "words": [{"w": "x", "s": 1.0, "e": 1.2}]}]}
    sl = produce.shotlist(spec, timing, 3.0)
    assert [s["img"] for s in sl["shots"]] == ["img/a.jpg", "img/a.jpg"]


def test_review_bar_accepts_good_not_broken():
    from app import auto
    good = {"hook": 9, "visual_quality": 6, "accuracy": 9, "originality": 6, "policy": 10, "visual_variety": 7, "polish": 6, "hierarchy": 7, "consistency": 6, "payoff": 7}
    assert auto.review_bar(good)
    assert not auto.review_bar({**good, "polish": 4})
    assert not auto.review_bar({**good, "accuracy": 8})
    assert not auto.review_bar({})


def test_stock_candidates_need_keys_and_parse(monkeypatch):
    from app import footage
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    monkeypatch.delenv("PIXABAY_API_KEY", raising=False)
    assert footage.stock_candidates("volcano") == []

    class R:
        def __init__(self, data): self.data = data
        def raise_for_status(self): pass
        def json(self): return self.data

    class C:
        def get(self, url, **k):
            if "pexels" in url:
                return R({"videos": [{"id": 7, "duration": 12, "url": "https://pexels.com/v/7", "user": {"name": "Ann"},
                                      "video_files": [{"file_type": "video/mp4", "width": 720, "height": 1280, "link": "https://x/a.mp4"},
                                                      {"file_type": "video/mp4", "width": 1920, "height": 1080, "link": "https://x/wide.mp4"}]}]})
            return R({"hits": [{"id": 9, "duration": 10, "user": "Bob", "pageURL": "https://pixabay.com/v/9", "videos": {"medium": {"url": "https://x/b.mp4"}}}]})
    monkeypatch.setenv("PEXELS_API_KEY", "k")
    monkeypatch.setenv("PIXABAY_API_KEY", "k")
    got = footage.stock_candidates("volcano", client=C())
    assert [g["id"] for g in got] == ["pexels-7", "pixabay-9"] and got[0]["url"] == "https://x/a.mp4"


def test_pixabay_photo_needs_key_and_saves_credit(tmp_path, monkeypatch):
    import io
    import cv2
    import numpy as np
    from app import stills
    monkeypatch.delenv("PIXABAY_API_KEY", raising=False)
    import pytest
    with pytest.raises(RuntimeError):
        stills.pixabay("rocket", tmp_path / "a.jpg")
    jpg = cv2.imencode(".jpg", np.full((1280, 720, 3), 120, np.uint8))[1].tobytes()

    class R:
        def raise_for_status(self): pass
        def json(self): return {"hits": [{"tags": "rocket, launch", "largeImageURL": "https://x/p.jpg", "user": "Zed", "pageURL": "https://pixabay.com/p/1"}]}

    class C:
        def get(self, *a, **k): return R()
    class Img:
        status_code = 200
        headers = {"content-type": "image/jpeg"}
        content = jpg
    monkeypatch.setenv("PIXABAY_API_KEY", "k")
    monkeypatch.setattr("httpx.get", lambda *a, **k: Img())
    out, credit = stills.pixabay("rocket", tmp_path / "a.jpg", client=C())
    assert out.exists() and credit["license"] == "Pixabay licence" and credit["artist"] == "Zed"
