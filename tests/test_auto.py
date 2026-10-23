"""Offline tests for the free autonomous driver (no network, no render)."""
import json
from pathlib import Path

from app import auto

ROOT = Path(__file__).resolve().parents[1]
SPEC = json.loads((ROOT / "examples" / "doomsday.json").read_text())
for _i, _b in enumerate(SPEC["beats"]):
    _b.setdefault("prompt", f"photoreal cinematic scene {_i}, no text")   # the shipped example uses pre-made stills
FACTS = "In 1960 von Foerster published in Science. 24 estimates over 2,000 years. 3,015,470,894 in 1960; 8,300,678,395 in 2026. 13 November 2026. 50% half. 1993."


def test_good_spec_validates():
    assert auto.validate_spec(SPEC, FACTS) == []


def test_unknown_number_rejected():
    bad = json.loads(json.dumps(SPEC))
    bad["beats"][2]["hud"][1]["text"] = "7,777"
    assert any("7,777" in e for e in auto.validate_spec(bad, FACTS))


def test_hud_anchor_must_be_spoken_word():
    bad = json.loads(json.dumps(SPEC))
    bad["beats"][1]["hud"][0]["at"] = "zebra"
    auto.validate_spec(bad, FACTS)          # now auto-repaired to a spoken word instead of failing
    assert bad["beats"][1]["hud"][0]["at"] != "zebra"


def test_first_use_of_image_needs_prompt():
    bad = json.loads(json.dumps(SPEC))
    for b in bad["beats"]:
        b.pop("prompt", None)
    assert any("needs a prompt" in e for e in auto.validate_spec(bad, FACTS))


def test_write_spec_retries_with_feedback(monkeypatch):
    sent = []
    good = json.loads(json.dumps(SPEC))
    for i, b in enumerate(good["beats"]):
        b.setdefault("prompt", f"photoreal cinematic scene {i}")
    replies = iter([({"id": "Bad Slug"}, "groq"), (good, "groq")])

    def fake(system, user, image=None, prefer=None, exclude=None):
        sent.append(user)
        return next(replies)
    monkeypatch.setattr(auto, "ask", fake)
    spec, prov = auto.write_spec("t", {"url": "u", "text": FACTS})
    assert prov == "groq" and "failed validation" in sent[1] and spec["id"] == SPEC["id"]


def test_judge_uses_other_provider_and_gates(tmp_path, monkeypatch):
    (tmp_path / "sheet.jpg").write_bytes(b"x")
    seen = {}
    scores = dict(hook=9, visual_quality=9, accuracy=9, originality=8, policy=10, visual_variety=9, polish=8, hierarchy=8, consistency=8, payoff=8)

    def fake(system, user, image=None, prefer=None, exclude=None):
        seen["exclude"] = exclude
        return {"scores": scores, "fixes": []}, "gemini"
    monkeypatch.setattr(auto, "ask", fake)
    j = auto.judge(tmp_path, SPEC, writer="groq")
    assert seen["exclude"] == "groq" and j["approved"]
    v = json.loads((tmp_path / "vision.json").read_text())
    assert v["verdict"] == "approve" and "safe_zone" in v["scores"]
    scores["visual_quality"] = 6
    assert not auto.judge(tmp_path, SPEC, writer="groq")["approved"]


def test_similarity_blocks_repeat(tmp_path, monkeypatch):
    monkeypatch.setattr(auto, "ROOT", tmp_path)
    (tmp_path / "data").mkdir()
    blob = SPEC["title"].lower() + " " + " ".join(b["say"].lower() for b in SPEC["beats"])
    (tmp_path / "data/history.jsonl").write_text(json.dumps({"blob": blob}) + "\n")
    assert auto.too_similar(SPEC) > 0.9
