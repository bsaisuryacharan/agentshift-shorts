"""Variety supervisor (rolling style ledger -> prompt brief + code-level look rotation) and the style radar's bookkeeping paths."""
import json

import pytest

from app import looks, variety


@pytest.fixture
def ledger(monkeypatch, tmp_path):
    monkeypatch.setattr(variety, "PATH", tmp_path / "style_ledger.json")
    return tmp_path / "style_ledger.json"


def entry(fmt="myth_vs_fact", look="swiss-grid", theme="cool", tech=None):
    return {"id": "x", "title": "t", "format": fmt, "look": look, "theme": theme, "techniques": tech or []}


def test_empty_ledger_briefs_nothing_and_defaults_midnight(ledger):
    assert variety.entries() == [] and variety.brief("versus") == ""
    assert variety.adjust_look(None, "versus") == "explainer-diagram"        # no history: the look the writer chose stands


def test_record_trims_and_captures_techniques(ledger):
    try:
        from app import gallery_hf
        hf = gallery_hf.names()[0] if gallery_hf.names() else "count-up"
    except Exception:
        hf = "count-up"
    spec = {"id": "a", "title": "A", "format": "myth_vs_fact", "look": "swiss-grid", "theme": "cool",
            "beats": [{"key": "hook", "hud": [{"t": "bubble", "text": "true?"}, {"t": "hf", "name": hf}]},
                      {"key": "b1", "graphic": True, "hud": [{"t": "bars", "items": [["a", 1, "cy"]]}]},
                      {"key": "b2", "graphic": True, "hud": [{"t": "ring", "pct": 50}]}]}
    for i in range(variety.KEEP + 3):                                       # the ledger rolls, it never grows unbounded
        variety.record({**spec, "id": f"a{i}"})
    runs = variety.entries()
    assert len(runs) == variety.KEEP and runs[-1]["id"] == f"a{variety.KEEP + 2}"
    assert hf and "hf" in runs[-1]["techniques"] and "bars" in runs[-1]["techniques"] and "ring" in runs[-1]["techniques"]
    assert "pure_graphic" in runs[-1]["techniques"]


def test_adjust_look_rotates_away_from_recent(ledger):
    for look, fmt in [("swiss-grid", "myth_vs_fact"), ("swiss-grid", "myth_vs_fact"), ("poster-pop", "ranked")]:
        variety.record(entry(fmt=fmt, look=look))
    got = variety.adjust_look(None, "myth_vs_fact")                          # swiss-grid was just used twice -> another fitting look
    assert got in looks.CANDIDATES["myth_vs_fact"] and got != "swiss-grid"


def test_brief_bans_recent_look_and_asks_for_fresh_technique(ledger):
    for i, (look, fmt, tech) in enumerate([("swiss-grid", "myth_vs_fact", ["bars"]), ("swiss-grid", "myth_vs_fact", ["rows"]),
                                           ("poster-pop", "ranked", ["ring"])]):
        variety.record(entry(fmt=fmt, look=look, tech=tech))
    brief = variety.brief("myth_vs_fact")
    assert "STAND OUT" in brief and "swiss-grid" in brief and "USED OUT" in brief   # the previous Shorts' looks are named and banned
    for used in ("bars", "rows"):
        assert used in brief                                                  # too-recent techniques are listed as 'do not lead with'
    assert "FEATURE one motion idea" in brief


def test_radar_short_circuits_when_fresh_and_never_loses_takeaways(monkeypatch, tmp_path):
    from app import trends
    from app.settings import Settings
    import datetime as dt
    fresh = {"generated_at": (dt.datetime.now(dt.UTC)).isoformat(), "status": "ok",
             "takeaways": ["count numbers on the spoken word", "one accent colour per Short"]}
    path = tmp_path / "style_radar.json"
    path.write_text(json.dumps(fresh))
    called = []
    monkeypatch.setattr(trends, "STYLE_JSON", path)
    monkeypatch.setattr(trends, "STYLE_DOC", tmp_path / "STYLE_UPDATES.md")
    got = trends.style_radar(Settings(), distill=lambda *a: called.append(1) or {})  # no network, no LLM: fresh radar is reused
    assert not called and got == fresh


def test_radar_searches_distills_and_writes_a_bounded_log(monkeypatch, tmp_path):
    from app import trends
    from app.settings import Settings
    import datetime as dt
    old = {"generated_at": (dt.datetime.now(dt.UTC) - dt.timedelta(days=9)).isoformat(), "status": "ok",
           "takeaways": ["old idea"]}
    path = tmp_path / "style_radar.json"
    path.write_text(json.dumps(old))
    doc = tmp_path / "STYLE_UPDATES.md"
    doc.write_text("\n---\n".join(f"## 2026-10-0{i} — faceless-Short style radar\n- old" for i in range(1, 9)))   # 8 sections already
    monkeypatch.setattr(trends, "STYLE_JSON", path)
    monkeypatch.setattr(trends, "STYLE_DOC", doc)
    settings = Settings(youtube_api_key="k")

    class Resp:
        def __init__(self, payload):
            self.payload = payload
        def raise_for_status(self):
            pass
        def json(self):
            return self.payload

    class Client:
        def get(self, url, **kw):
            if url.endswith("videos"):
                return Resp({"items": [{"id": "v1", "snippet": {"title": "Kinetic typography shorts that hit", "publishedAt": "2026-10-10T00:00:00Z"},
                                        "statistics": {"viewCount": 900000}}]})
            return Resp({"items": [{"id": {"videoId": "v1"}}]})

    def distill(system, user):
        assert "Kinetic typography" in user and "HTML/CSS" in system
        return {"takeaways": ["slam the key number on the spoken word", 7], "avoid": ["stock transitions"],
                "styles_to_watch": ["chunky kinetic type with counters"]}

    radar = trends.style_radar(settings, client=Client(), distill=distill)
    assert [t for t in radar["takeaways"] if isinstance(t, str)] == ["slam the key number on the spoken word"]   # non-strings filtered
    assert len(radar["signals"]) == 1 and radar["signals"][0]["query"] == trends.STYLE_SEARCHES[0]
    saved = json.loads(path.read_text())
    assert saved["status"] == "ok"
    sections = doc.read_text().split("\n---\n")
    assert len([s for s in sections if "style radar" in s]) <= trends.RADAR_KEEP_SECTIONS                     # the log stays bounded
    assert "slam the key number" in sections[0]          # newest section on top of docs/STYLE_UPDATES.md
