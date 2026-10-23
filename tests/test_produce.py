"""Offline tests for the one-command pipeline (no network, no browser, no ffmpeg render)."""
import json
from pathlib import Path

import pytest

from app import hud, produce, stills, voice

ROOT = Path(__file__).resolve().parents[1]
SPEC = json.loads((ROOT / "examples" / "doomsday.json").read_text())


def fake_timing(spec):
    t, segs = 0.0, []
    for b in spec["beats"]:
        words, s = [], t
        for w in b["say"].split():
            words.append({"w": w, "s": round(s, 3), "e": round(s + 0.3, 3)})
            s += 0.35
        segs.append({"key": b["key"], "text": b["say"], "start": round(t, 3), "dur": round(s - t, 3), "words": words})
        t = s + 0.18
    return {"total": round(t, 3), "segments": segs}


def test_word_time_finds_word_and_default():
    tm = fake_timing(SPEC)
    key = SPEC["beats"][0]["key"]
    first = SPEC["beats"][0]["say"].split()[0]
    assert voice.word_time(tm, key, first) == tm["segments"][0]["words"][0]["s"]
    assert voice.word_time(tm, key, "zzzz-not-there", default=9.5) == 9.5


def test_shotlist_is_ordered_and_covers_every_beat():
    tm = fake_timing(SPEC)
    sl = produce.shotlist(SPEC, tm, tm["total"] + produce.TAIL_S)
    starts = [s["start"] for s in sl["shots"]]
    assert starts == sorted(starts) and starts[0] == 0.0
    assert len(sl["shots"]) >= len(SPEC["beats"])
    assert sl["overlay_step"] == 2 and sl["total"] > tm["total"]


def test_onscreen_text_collected_for_glyph_audit():
    txt = produce.onscreen_text(SPEC)
    assert "NOT INFINITY" in txt.upper() or "not infinity" in txt.lower()


def test_hud_page_respects_safe_zone_css():
    tm = fake_timing(SPEC)
    html = hud.Page(SPEC, tm, tm["total"] + produce.TAIL_S).build()
    assert "bottom:540px" in html.replace(" ", "") and "right:150px" in html.replace(" ", "")
    assert "__timelines" in html


def test_stills_ensure_names_every_missing_prompt(tmp_path):
    with pytest.raises(FileNotFoundError) as e:
        stills.ensure(SPEC, tmp_path)
    assert "s0.jpg" in str(e.value)


def test_stills_ensure_passes_when_present(tmp_path):
    img = tmp_path / "img"
    img.mkdir()
    for b in SPEC["beats"]:
        for s in [b] + b.get("cuts", []):
            if "img" in s:
                (img / s["img"]).write_bytes(b"x")
    assert stills.ensure(SPEC, tmp_path)


def test_every_motion_element_builds_and_stays_in_stage():
    from app import hud, motion
    tm = fake_timing(SPEC)
    els = [{"t": "bars", "items": [["a", "3", "ir"], ["b", "8", "ok"]], "unit": "B"}, {"t": "line", "values": [1, 2, 4], "labels": ["a", "b"]},
           {"t": "ring", "pct": 62, "label": "x"}, {"t": "delta", "text": "+1%", "dir": "down"}, {"t": "kinetic", "text": "a *b* c"},
           {"t": "tape", "text": "X"}, {"t": "toast", "title": "t", "sub": "s"}, {"t": "cursor", "text": "GO"}, {"t": "title", "html": "x", "fx": "shine"}]
    spec = json.loads(json.dumps(SPEC))
    first = spec["beats"][1]
    first["hud"] = [dict(e, at=first["say"].split()[0]) for e in els]
    html = hud.Page(spec, tm, tm["total"] + produce.TAIL_S).build()
    for cls in ("bars", "linec", "ringw", "delta", "kin", "tape", "toast", "curw", "shw"):
        assert f'class="{cls}' in html
    assert motion.CSS in html


def test_malformed_hud_element_is_skipped_not_fatal(tmp_path):
    import json as _j
    from pathlib import Path as _P
    from app import hud
    spec = _j.loads((_P(__file__).resolve().parents[1] / "examples" / "doomsday.json").read_text())
    tm = {"segments": [], "fps": 30}
    # build timing from the spec itself: one fake word per spoken word
    t = 0.0
    for b in spec["beats"]:
        words = []
        for w in b["say"].split():
            words.append({"w": w, "s": round(t, 2), "e": round(t + .3, 2)})
            t += .3
        tm["segments"].append({"key": b["key"], "text": b["say"], "start": words[0]["s"], "dur": t - words[0]["s"], "words": words})
    spec["beats"][1]["hud"] = [{"t": "stamp"}, {"t": "big", "text": "1960", "count": 1960, "at": spec["beats"][1]["say"].split()[0].strip(".,'")}]
    out = hud.write(spec, tm, t + 2, tmp_path / "p.html")
    assert "window.__timelines" in out.read_text()
