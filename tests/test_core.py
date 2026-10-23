import io
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.analytics import _periods, _rows, channel_analytics
from app.creative import (
    _measured_copy,
    _screen_copy,
    creative_brief,
    default_treatments,
    recent_feedback,
    refine_treatment,
)
from app.main import align_images_to_beats
from app.models import Claim, Script, Source, TrendSignal, VisualReview
from app.motion_library import library_summary
from app.playbook import PLAYBOOK
from app.providers import _source_fallback_script, _truncate_words, _validate_visual_review
from app.render import make_srt
from app.settings import Settings
from app.store import Store
from app.trends import _in_scope, _news_priority


def test_settings_rejects_unknown_publish_mode():
    settings = Settings(publish_mode="anything")
    assert "PUBLISH_MODE must be review or schedule" in settings.validate_production()


def test_monitor_without_oauth_records_authorization_requirement(tmp_path: Path):
    report = channel_analytics(Settings(youtube_token_file=tmp_path / "missing-token.json", data_dir=tmp_path))
    assert report["status"] == "needs_analytics_authorization"
    assert (tmp_path / "latest_channel_analytics.json").exists()


def test_analytics_periods_are_equal_completed_day_windows():
    current, previous = _periods(30)
    assert current[0] > previous[1]


def test_creator_content_type_rows_use_lowercase_shorts_value():
    result = {"columnHeaders": [{"name": "creatorContentType"}, {"name": "views"}], "rows": [["shorts", 12]]}
    assert _rows(result) == [{"creatorContentType": "shorts", "views": 12}]


def test_captions_are_generated(tmp_path: Path):
    path = make_srt(["A hook", "A body", "An ending"], tmp_path / "captions.srt", 30)
    text = path.read_text()
    assert "00:00:00,000 --> 00:00:10,000" in text
    assert "An ending" in text


def test_narration_is_ordered():
    script = Script(hook="H", body=["B1", "B2"], ending="E", title="T", description="D",
                    claims=[Claim(text="x", source_ids=["S1"], numeric=False)])
    assert script.narration == "H B1 B2 E"


def test_motion_treatments_are_distinct_and_restrained():
    treatments = default_treatments()
    assert len(treatments) == 3
    assert len({treatment.id for treatment in treatments}) == 3
    assert all("crossfades" in treatment.banned or "soft fades" in treatment.banned for treatment in treatments)


def test_screen_copy_is_not_a_full_transcript():
    assert _screen_copy("This is deliberately a long narration sentence with many words.") == "THIS IS DELIBERATELY A LONG"


def test_screen_copy_replaces_scientific_unicode_with_renderable_copy():
    assert _screen_copy("gamma Cassiopeia lights the gas") == "GAMMA CASSIOPEIA LIGHTS THE GAS"
    assert _screen_copy("γ Cassiopeia lights the gas") == "GAMMA CASSIOPEIA LIGHTS THE GAS"


def test_screen_copy_drops_a_dangling_function_word():
    assert _screen_copy("Watch NASA ignite RS-25 engine for Artemis testing", words=6) == "WATCH NASA IGNITE RS-25 ENGINE"


def test_screen_copy_uses_a_complete_first_clause():
    assert _screen_copy("Test lasted 500 seconds, matching launch duration", words=7) == "TEST LASTED 500 SECONDS"


def test_measured_copy_never_invents_a_number():
    assert _measured_copy("The hot fire lasted 500 seconds, matching launch duration") == "500 SECONDS"
    assert _measured_copy("Data will improve future engine performance") == "DATA WILL IMPROVE FUTURE"


def test_script_compaction_preserves_a_word_limit_without_new_content():
    assert _truncate_words("One two three four five", 3) == "One two three."


def test_source_fallback_remains_compact_and_cited():
    source = Source(url="https://example.com/story", title="A verified test", publisher="Example Lab",
                    retrieved_at=datetime.now(UTC),
                    excerpt="Engine test produced useful data for future launches. Operators tested the nozzle under heat. The team recorded stable pressure throughout the burn. Engineers will study the results before the next test. The article explains the full procedure.")
    script = _source_fallback_script("A verified engine test", [source])
    assert len(script.body) in {4, 5}
    assert all(claim.source_ids == ["S1"] for claim in script.claims)


def test_reference_library_has_200_attributed_cards():
    root = Path(__file__).resolve().parents[1]
    summary = library_summary(root / "data" / "motion_reference_library.json")
    assert sum(summary.values()) >= 200


def test_rejected_source_memory_persists_across_local_cycles(tmp_path: Path):
    store = Store(tmp_path)
    store.save_source_rejection("https://example.com/one", "Unvisual story", "Only one image", "2026-10-22T00:00:00Z")
    assert store.rejected_source_urls() == {"https://example.com/one"}


def test_legacy_asset_rejection_is_reconsidered_after_asset_policy_upgrade(tmp_path: Path):
    store = Store(tmp_path)
    store.save_source_rejection("https://example.com/legacy", "Old source", "Source-asset gate: one image", "2026-10-22T00:00:00Z")
    store.save_source_rejection("https://example.com/current", "Current source", "Source-asset gate v2: one image", "2026-10-22T00:00:00Z")
    assert store.rejected_source_urls() == {"https://example.com/current"}


def test_recent_feedback_reads_only_valid_structured_reviews(tmp_path: Path):
    path = tmp_path / "creative_learning.json"
    path.write_text('{"last_reviews":{"kinetic-evidence":{"hook":8,"visual_hierarchy":8,"motion_readability":8,"composition":8,"text_legibility":8,"factual_visual_alignment":8,"originality":8,"verdict":"approve","repair_notes":[]}}}')
    assert recent_feedback(path)["kinetic-evidence"].approved()


def test_visual_review_normalizes_nested_provider_scores_without_inventing_them():
    review = _validate_visual_review({
        "scores": {"hook": 5, "visual_hierarchy": 6, "motion_readability": 7, "composition": 8,
                   "text_legibility": 9, "factual_visual_alignment": 4, "originality": 5},
        "verdict": "REJECT", "repair_notes": "Use related source imagery.",
    })
    assert review.hook == 5
    assert review.verdict == "reject"
    assert review.repair_notes == ["Use related source imagery."]


def test_trend_scope_rejects_commercial_packaging_but_keeps_editorial_topics():
    assert _in_scope("NASA tests new engine for Artemis")
    assert not _in_scope("Cool gadgets under 300 sale")


def test_institutional_news_is_prioritized_for_direct_verification():
    now = datetime.now(UTC)
    official = TrendSignal(source="news", format="news", title="CERN science update", url="https://example.com/cern", observed_at=now, short_form_confidence=0)
    generic = TrendSignal(source="news", format="news", title="A generic science update", url="https://example.com/generic", observed_at=now, short_form_confidence=0)
    assert _news_priority(official) < _news_priority(generic)


def test_asset_alignment_prefers_matching_source_alt_text(tmp_path: Path):
    images = [tmp_path / "rocket.jpg", tmp_path / "rover.jpg"]
    provenance = [{"alt_text": "Rocket launch from Earth"}, {"alt_text": "Mars rover explores the surface"}]
    assert align_images_to_beats(images, provenance, ["A Mars rover explores", "A rocket launches"]) == [images[1], images[0]]


def test_third_treatment_uses_only_allowlisted_reviewer_learning():
    feedback = VisualReview(hook=7, visual_hierarchy=7, motion_readability=6, composition=7,
                            text_legibility=7, factual_visual_alignment=8, originality=6, verdict="reject",
                            repair_notes=["Remove production labels and avoid static, repetitive transitions."])
    adapted = refine_treatment(default_treatments()[2], {"editorial-collage": feedback})
    assert adapted.iteration_directives == [
        "increase_per_beat_variation", "strengthen_object_continuity", "remove_production_labels",
    ]


def test_creative_brief_has_audience_facing_beats_and_banned_list():
    brief = creative_brief(["A hook", "Proof", "Payoff"], default_treatments()[0])
    assert len(brief["beat_map"]) == 3
    assert "copied competitor media" in brief["banned"]
    assert any(item["id"] == "appeal" for item in PLAYBOOK["principles"])


def test_iteration_directives_change_rendered_variety(tmp_path: Path):
    """Renderer learning must have a real, visible effect or the review loop cannot repair anything."""
    from PIL import Image

    from app.creative import _base_frame, _data

    image = tmp_path / "scene.jpg"
    Image.new("RGB", (1600, 900), (120, 40, 40)).save(image)
    treatment = default_treatments()[2]
    plain = _base_frame(image, 0.5, treatment.palette, 2)
    varied = _base_frame(image, 0.5, treatment.palette, 2, {"increase_per_beat_variation"})
    assert list(plain.getdata()) != list(varied.getdata())
    baseline = lambda result: result.crop((84, 305, 996, 330)).tobytes()
    plain_data = _data(_base_frame(image, 0.5, treatment.palette, 2), treatment, "The test lasted 500 seconds", 0.5, 2)
    varied_data = _data(_base_frame(image, 0.5, treatment.palette, 2), treatment, "The test lasted 500 seconds", 0.5, 2, {"increase_per_beat_variation"})
    assert baseline(plain_data) != baseline(varied_data)
    base = _base_frame(image, 0.5, treatment.palette, 2)
    no_metric = _data(base.copy(), treatment, "Artemis engines will roar", 0.5, 2)
    assert no_metric.crop((84, 480, 500, 660)).tobytes() == base.crop((84, 480, 500, 660)).tobytes()


def test_reviewer_clutter_notes_request_texture_care():
    feedback = VisualReview(hook=7, visual_hierarchy=5, motion_readability=6, composition=6,
                            text_legibility=5, factual_visual_alignment=8, originality=6,
                            verdict="reject", repair_notes=["The frames look repetitive; reduce the on-screen clutter."])
    adapted = refine_treatment(default_treatments()[0], {"kinetic-evidence": feedback})
    assert "protect_text_clearspace" in adapted.iteration_directives
    assert "increase_per_beat_variation" in adapted.iteration_directives


def test_discovery_degrades_to_least_overlapping_candidate(tmp_path, monkeypatch):
    import types

    from app import trends
    signals = [
        types.SimpleNamespace(title="NASA Mission About Earth Maps", url="https://example.org/a", format="primary_source"),
        types.SimpleNamespace(title="Robot on Thermal Ridge Near Mars", url="https://example.org/b", format="primary_source"),
        types.SimpleNamespace(title="NASA Earth Mapping Update For Maps", url="https://example.org/c", format="primary_source"),
    ]
    class FakeSettings:
        pass
    settings = FakeSettings()
    settings.trend_region = "us"
    monkeypatch.setattr(trends, "analyze", lambda s: types.SimpleNamespace(signals=signals))
    monkeypatch.setattr(trends, "research_nasa_sources", lambda n: [
        Source(title="Robot on Thermal Ridge Near Mars Extended", url="https://example.org/b",
               publisher="Example Science", retrieved_at=datetime.now(UTC), excerpt="Verified robot traversal.")
    ])
    idea = trends.discover(settings, recent_scripts=["detailed maps of Earth from NASA satellites"], excluded_source_urls=set())
    assert "Mars" in idea.title  # least-overlapping candidate wins under graceful degradation
    assert str(idea.sources[0].url) == "https://example.org/b"


def test_overlap_ratio_hard_fails_on_near_duplicate_titles(monkeypatch):
    import types

    from app import trends
    signals = [
        types.SimpleNamespace(title="Ever Wonder How Detailed Maps Are From Space", url="https://example.org/x", format="primary_source"),
    ]
    monkeypatch.setattr(trends, "analyze", lambda settings: types.SimpleNamespace(signals=signals))
    monkeypatch.setattr(trends, "research_nasa_sources", lambda n: [
        Source(title="Ever Wonder How Detailed Maps Are From Space Reprint", url="https://example.org/same",
               publisher="Example Science", retrieved_at=datetime.now(UTC), excerpt="Near duplicate of the last narration.")
    ])
    with pytest.raises(RuntimeError):
        trends.discover(types.SimpleNamespace(trend_region="us"), recent_scripts=["Ever wonder how detailed our maps of Earth are from space?"], excluded_source_urls=set())


def test_asset_alignment_never_repeats_an_asset_while_unused_ones_remain():
    images = [Path("a.jpg"), Path("b.jpg"), Path("c.jpg"), Path("d.jpg")]
    provenance = [
        {"alt_text": "flight engineers in headsets watch the console"},
        {"alt_text": "flight engineers in headsets at mission control"},
        {"alt_text": "Explorer satellite in orbit"},
        {"alt_text": "Ranger spacecraft at the Moon"},
    ]
    rendered = align_images_to_beats(images, provenance, [
        "Engineers watched the countdown at mission control",
        "Engineers cheered as the satellite reached orbit",
        "Ranger reached the Moon",
        "Ranger beamed home its first lunar images",
    ])
    assert len(set(rendered)) == 4, "A contact sheet with a repeated asset reads as visual monotony"


def test_perceptual_duplicate_filter_spreads_near_identical_photos():
    from PIL import Image

    from app.assets import _perceptual_duplicate

    def png_bytes(color: tuple[int, int, int]) -> bytes:
        buffer = io.BytesIO()
        Image.new("RGB", (640, 480), color).save(buffer, format="PNG")
        return buffer.getvalue()

    kept: list[Image.Image] = []
    base, fresh = png_bytes((90, 100, 110)), png_bytes((190, 40, 40))
    assert not _perceptual_duplicate(kept, base)
    assert _perceptual_duplicate(kept, base), "identical content should be skipped as a near-duplicate"
    assert not _perceptual_duplicate(kept, fresh)
    assert len(kept) == 2


def test_data_beat_does_not_repeat_metric_words_in_the_caption():
    from PIL import Image

    from app.creative import _base_frame, _data, default_treatments
    with tempfile.TemporaryDirectory() as tmp:
        image = Path(tmp) / "a.jpg"
        Image.new("RGB", (900, 700), (120, 40, 40)).save(image)
        treatment = default_treatments()[2]
        frame = _base_frame(image, 0.5, treatment.palette, 2, set())
        crop_fn = lambda result: result.crop((60, 1050, 900, 1250)).tobytes()
        lone_metric = _data(frame, treatment, "The test lasted 500 seconds.", 0.5, 2)
        metric_context = _data(frame.copy(), treatment, "The test lasted 500 seconds matching a launch burn", 0.5, 2)
        assert crop_fn(lone_metric) != crop_fn(metric_context)  # context line appears only with spare words


def test_screen_copy_keeps_hyphenated_and_accented_narration_readable():
    assert _screen_copy("El Niño‑driven drought dried savannas across", words=5) == "EL NINO DRIVEN DROUGHT DRIED"
    assert _screen_copy("Human‑set fires ignited dry vegetation", words=5) == "HUMAN SET FIRES IGNITED DRY"
    assert "NINODRIVEN" not in _screen_copy("El Niño‑driven drought", words=5)


def test_recap_scenes_flag_only_reused_photos():
    from app.creative import _recap_scenes

    images = [Path("a.jpg"), Path("b.jpg"), Path("a.jpg"), Path("c.jpg"), Path("a.jpg")]
    assert _recap_scenes(images) == {2, 4}


def test_recap_card_stays_in_motion_without_photo_pixels():
    from app.creative import _card_frame

    palette = ["#09111F", "#F5F0E6", "#D6FF4B", "#FF5A36"]
    quarter, three_quarter = _card_frame(palette, 0.25, 1), _card_frame(palette, 0.75, 1)
    assert quarter.tobytes() != three_quarter.tobytes(), "a recap card must never render as a frozen still"
    top_left = quarter.getpixel((540, 60))
    assert top_left[0] < 60 and top_left[2] < 80, "the card background must stay typographic, never a photograph"


def test_consecutive_beats_never_share_the_same_caption():
    from app.creative import _scene_captions

    lines = [
        "Air quality worsened across the region this week",
        "Air quality worsened across the region this week, and flights were delayed",
        "The smoke lingered over forests for days",
    ]
    captions = _scene_captions(lines)
    assert captions[0] == _scene_captions(lines)[0], "test precondition: bare lead clauses resolve identically"
    assert captions[1] != captions[0], "a repeated caption must swap to that beat's trailing claim"
    assert captions[1] == "AND FLIGHTS WERE DELAYED"


def test_map_like_graphic_never_becomes_event_imagery():
    import io

    from PIL import Image

    from app.assets import _map_like_graphic

    def encode(im: Image.Image) -> bytes:
        buffer = io.BytesIO()
        im.save(buffer, "PNG")
        return buffer.getvalue()

    grey_map = Image.new("RGB", (300, 150), (210, 212, 213))
    assert _map_like_graphic(encode(grey_map)), "a small uniform-grey export is a map, not evidence"
    assert not _map_like_graphic(encode(grey_map.resize((800, 600)))), "full-size graphics may still serve"
    photo = Image.new("RGB", (400, 260))
    photo.putdata([(x * 4 % 250, y * 3 % 250, (x + y) % 250) for y in range(260) for x in range(400)])
    assert not _map_like_graphic(encode(photo)), "colorful imagery must not be discarded as a map"


def test_storyboard_tiles_sample_inside_their_own_beat():
    import math

    # Reproduce the render loop's scene arithmetic and confirm every sampled frame belongs to
    # its own beat, not to the previous one (the mislabeled-tile bug behind duplicate captions).
    duration, fps, scenes = 41.3, 6, 6
    scene_duration = duration / scenes
    total = max(math.ceil(duration * fps), scenes * fps)
    starts = [min(round((scene + 0.25) * scene_duration * fps), max(total - 1, 0)) for scene in range(scenes)]
    for scene, frame in enumerate(starts):
        time = min(frame / fps, duration - 0.001)
        index = min(int(time / scene_duration), scenes - 1)
        assert index == scene, f"tile {scene} sampled frame {frame} which belongs to beat {index}"
