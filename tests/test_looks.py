import json

from app import auto, looks


def test_every_look_is_vendored_with_its_rules():
    for name in looks.LOOKS:
        assert (looks.LIB / name / "STYLE.md").exists(), name
    assert (looks.LIB.parent / "LICENSE").exists()


def test_backgrounds_and_css():
    for name in looks.LOOKS:
        img = looks.background(name)
        assert img.shape == (1920, 1080, 3) and img.std() > 1          # a designed ground, not a blank frame
    c = looks.css("poster-pop")
    assert "League+Gothic" in c and ".beat.graphic" in c and "#FFD400" not in c   # ground colour lives in the background image, not the overlay
    assert looks.css("nope") == "" and looks.pick("nope", "versus") == "explainer-diagram"


def test_graphic_beats_need_no_picture_terms():
    spec = json.loads(open("examples/doomsday.json").read())
    b = spec["beats"][2]
    b.update({"graphic": True, "photo": "something", "footage": "x"})
    b.pop("prompt", None)
    errs = auto.validate_spec(spec, "In 1960 von Foerster published in Science. 24 estimates over 2,000 years. 3,015,470,894 in 1960; 8,300,678,395 in 2026. 13 November 2026. 50% half. 1993.")
    assert not any(b["key"] in e and "prompt" in e for e in errs) and "photo" not in b and "footage" not in b
