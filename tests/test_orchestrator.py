"""Offline tests for the Telegram orchestrator (LLM, render and Telegram are mocked)."""
import json
from pathlib import Path

import pytest

from app import auto, orchestrator as o

ROOT = Path(__file__).resolve().parents[1]
SPEC = json.loads((ROOT / "examples" / "doomsday.json").read_text())
for _i, _b in enumerate(SPEC["beats"]):
    _b.setdefault("prompt", f"photoreal scene {_i}, no text")
FACTS = {"url": "http://x", "text": "In 1960 von Foerster published in Science. 24 estimates over 2,000 years. 3,015,470,894 in 1960; 8,300,678,395 in 2026. 13 November 2026. 50% half. 1993."}


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(o, "STATE", tmp_path / "state")
    monkeypatch.setattr(o, "PROJ", tmp_path / "projects")
    monkeypatch.setattr(o, "OUT", tmp_path / "runs")
    sent = []
    monkeypatch.setattr(auto, "telegram", lambda text, video=None, chat=None: sent.append((chat, text)) or True)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    return sent


def test_shortcuts_and_bare_message_is_topic():
    assert o.classify("/new black holes", {"current": None, "projects": {}}) == {"intent": "new", "topic": "black holes"}
    assert o.classify("/status", {})["intent"] == "status"
    assert o.classify("what if the moon vanished", {"current": None, "projects": {}})["intent"] == "new"


def test_unauthorised_chat_ignored(env):
    assert o.handle("999", "/new anything") == 0
    assert env == []


def test_help_and_status(env):
    o.handle("42", "/help")
    o.handle("42", "/status")
    assert "Commands" in env[0][1] and "No Short yet" in env[1][1]


def test_changed_pictures_detects_prompt_and_seed():
    new = json.loads(json.dumps(SPEC))
    new["beats"][1]["prompt"] = "different"
    new["beats"][2]["seed"] = 9
    assert o.changed_pictures(SPEC, new) == {new["beats"][1]["img"], new["beats"][2]["img"]}
    assert o.changed_pictures(SPEC, SPEC) == set()


def test_revise_regenerates_only_changed_still(env, monkeypatch, tmp_path):
    spec = json.loads(json.dumps(SPEC))
    spec["id"], spec["_facts"] = "doom", FACTS
    d = o.PROJ / "doom"
    (d / "img").mkdir(parents=True)
    (d / "spec.json").write_text(json.dumps(spec))
    for b in spec["beats"]:
        (d / "img" / b["img"]).write_bytes(b"x")
    st = {"current": "doom", "projects": {"doom": {"title": "t", "status": "delivered"}}}
    o._save("42", st)
    edited = json.loads(json.dumps(spec))
    edited["beats"][1]["seed"] = 11                                      # re-roll picture of beat 1
    monkeypatch.setattr(auto, "ask", lambda *a, **k: (edited, "gemini"))
    seen = {}

    def fake_finish(sp, writer, out, deliver, chat):
        run = out / sp["id"]
        seen["present"] = sorted(p.name for p in (run / "img").glob("*"))
        return True, [], run, {"scores": {"hook": 9}}
    monkeypatch.setattr(auto, "finish", fake_finish)
    o.handle("42", "re-roll image 2")
    gone = edited["beats"][1]["img"]
    assert gone not in seen["present"] and len(seen["present"]) == len({b["img"] for b in spec["beats"]}) - 1
    st2 = o._state("42")
    assert st2["current"] == "doom-r1" and (o.PROJ / "doom-r1" / "spec.json").exists()
    assert any("Done" in t for _, t in env)


def test_failed_revise_does_not_send_video_and_tells_owner(env, monkeypatch):
    spec = json.loads(json.dumps(SPEC))
    spec["id"], spec["_facts"] = "doom", FACTS
    (o.PROJ / "doom").mkdir(parents=True)
    (o.PROJ / "doom" / "spec.json").write_text(json.dumps(spec))
    o._save("42", {"current": "doom", "projects": {"doom": {"title": "t", "status": "delivered"}}})
    monkeypatch.setattr(auto, "ask", lambda *a, **k: (spec, "gemini"))
    monkeypatch.setattr(auto, "finish", lambda *a, **k: (False, ["visual_quality 5"], o.OUT / "x", None))
    o.handle("42", "make it pop")
    assert any("didn't pass my checks" in t for _, t in env)


def test_extract_keeps_only_owner_text():
    ups = [{"update_id": 1, "message": {"chat": {"id": 42}, "text": "hi"}},
           {"update_id": 2, "message": {"chat": {"id": 7}, "text": "intruder"}},
           {"update_id": 3, "message": {"chat": {"id": 42}, "photo": []}},
           {"update_id": 4, "edited_message": {"chat": {"id": 42}, "text": "fix"}}]
    assert o.extract(ups, "42") == [(1, "42", "hi"), (4, "42", "fix")]


def test_approve_intent_and_publish_pack(env, tmp_path, monkeypatch):
    monkeypatch.setattr(auto, "LIMITS", {**auto.LIMITS, "history": tmp_path / "hist.jsonl"})
    assert o.classify("/approve", {})["intent"] == "approve"
    assert o.classify("approve", {"current": None})["intent"] == "approve"
    spec = dict(SPEC, id="demo-a1")
    d = o.PROJ / "demo-a1"
    (d / "img").mkdir(parents=True)
    (d / "spec.json").write_text(json.dumps(spec))
    (d / "img" / "credits.json").write_text(json.dumps({"s1.jpg": {"file": "File:HvF 01.jpg", "license": "CC BY-SA 4.0", "artist": "U of I", "url": "https://commons.wikimedia.org/wiki/File:HvF_01.jpg"}}))
    o._save("42", {"current": "demo-a1", "projects": {"demo-a1": {"title": spec["title"], "status": "delivered"}}})
    assert o.handle("42", "/approve") == 0
    assert o._state("42")["projects"]["demo-a1"]["status"] == "approved"
    assert "#shorts" in env[-1][1] and "CC BY-SA 4.0" in env[-1][1]
    assert (tmp_path / "hist.jsonl").exists()


def test_hud_anchor_autorepair():
    spec = json.loads(json.dumps(SPEC))
    spec["beats"][1]["hud"][0]["at"] = "zzzzqq"
    auto.validate_spec(spec, FACTS["text"])
    sw = {w.strip(".,!?'").lower() for w in spec["beats"][1]["say"].split()}
    assert spec["beats"][1]["hud"][0]["at"].lower() in sw



def test_a_draft_that_failed_review_cannot_be_approved(env, tmp_path):
    o._save("42", {"current": "d1", "projects": {"d1": {"title": "t", "status": "draft"}}})
    assert o.handle("42", "/approve") == 0
    assert o._state("42")["projects"]["d1"]["status"] == "draft" and "quality review" in env[-1][1]


def _prep_upload(tmp_path, status="approved", run_id="777"):
    spec = dict(SPEC, id="demo-a1")
    d = o.PROJ / "demo-a1"
    (d / "img").mkdir(parents=True, exist_ok=True)
    (d / "spec.json").write_text(json.dumps(spec))
    o._save("42", {"current": "demo-a1", "projects": {"demo-a1": {"title": spec["title"], "status": status, "run_id": run_id}}})


def test_upload_requires_an_approved_short(env, tmp_path):
    assert o.classify("/upload", {})["intent"] == "upload"
    _prep_upload(tmp_path, status="delivered")
    assert o.handle("42", "/upload") == 0
    assert "Approve it first" in env[-1][1]
    _prep_upload(tmp_path, status="draft")
    assert o.handle("42", "/upload") == 0 and "Approve it first" in env[-1][1]


def test_upload_happy_path_is_private_scheduled_and_only_once(env, tmp_path, monkeypatch):
    from app import upload
    _prep_upload(tmp_path)
    seen = {}
    monkeypatch.setattr(upload, "fetch_video", lambda run_id, spec_id: seen.update(run=run_id, spec=spec_id) or tmp_path / "v.mp4")
    monkeypatch.setattr(upload, "upload", lambda video, parts, when: seen.update(parts=parts, when=when) or
                        {"id": "abc", "url": "https://youtube.com/watch?v=abc", "privacy": "private", "publish_at": "2026-10-26T13:30:00Z"})
    assert o.handle("42", "/upload") == 0
    assert seen["run"] == "777" and seen["spec"] == "demo-a1" and seen["parts"]["title"].endswith("#shorts") and seen["when"].tzinfo is not None
    assert "https://youtube.com/watch?v=abc" in env[-1][1] and "private" in env[-1][1]
    assert o._state("42")["projects"]["demo-a1"]["uploaded"]["id"] == "abc"
    assert o.handle("42", "/upload") == 0 and "Already uploaded" in env[-1][1]


def test_upload_failure_is_reported_and_nothing_is_marked_uploaded(env, tmp_path, monkeypatch):
    from app import upload
    _prep_upload(tmp_path)
    monkeypatch.setattr(upload, "fetch_video", lambda *a: tmp_path / "v.mp4")
    monkeypatch.setattr(upload, "upload", lambda *a: (_ for _ in ()).throw(upload.UploadError("YouTube refused the upload (403 forbidden).")))
    assert o.handle("42", "/upload") == 0
    assert "Upload did not happen" in env[-1][1] and "403" in env[-1][1]
    assert "uploaded" not in o._state("42")["projects"]["demo-a1"]


def test_upload_slot_is_next_19_ist_with_lead_time():
    from datetime import UTC, datetime
    from app import upload
    assert upload.next_slot(datetime(2026, 10, 25, 12, 0, tzinfo=UTC)) == datetime(2026, 10, 25, 13, 30, tzinfo=UTC)
    assert upload.next_slot(datetime(2026, 10, 25, 13, 0, tzinfo=UTC)) == datetime(2026, 10, 26, 13, 30, tzinfo=UTC)     # < 45 min ahead -> tomorrow


def test_upload_without_secret_or_scope_explains_what_to_do(monkeypatch):
    from app import upload
    monkeypatch.delenv("YOUTUBE_TOKEN_JSON", raising=False)
    try:
        upload.credentials()
        raise AssertionError("expected UploadError")
    except upload.UploadError as e:
        assert "YOUTUBE_TOKEN_JSON" in str(e)
    monkeypatch.setenv("YOUTUBE_TOKEN_JSON", json.dumps({"token": "x", "refresh_token": "r", "client_id": "c", "client_secret": "s",
                                                       "scopes": ["https://www.googleapis.com/auth/yt-analytics.readonly"]}))
    try:
        upload.credentials()
        raise AssertionError("expected UploadError")
    except upload.UploadError as e:
        assert "permission to upload" in str(e) and "authorize-youtube" in str(e)
