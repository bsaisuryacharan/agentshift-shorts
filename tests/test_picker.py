from app import picker

SNAP = {"channel": {"median_views_per_short_after_1_week": 26, "shorts": [
    {"title": "Space Is Too Big For Your Brain", "views": 1689, "topic": "space"},
    {"title": "5 AI Prompts 99% of People Don't Know", "views": 21, "topic": "ai prompts"}]}}


def test_off_niche_trends_and_wiki_are_dropped():
    items = [("iPhone Duo Review", "trend"), ("Taylor Swift", "wiki"), ("Black hole", "wiki"), ("Aurora", "evergreen")]
    out = picker.rank(items, snapshot=SNAP)
    assert "iPhone Duo Review" not in out and "Taylor Swift" not in out and "Black hole" in out and "Aurora" in out


def test_winning_topics_rank_first_and_flops_sink():
    items = [("Cooking prompts for chatgpt science", "evergreen"), ("How big is space really", "evergreen"), ("Mars rovers", "evergreen")]
    out = picker.rank(items, snapshot=SNAP)
    assert out[0] == "How big is space really"


def test_news_gets_a_bonus_and_limit_applies():
    items = [("IN THE NEWS: NASA telescope finds new planet", "news")] + [(f"Planet {i}", "evergreen") for i in range(40)]
    out = picker.rank(items, limit=5, snapshot=SNAP)
    assert out[0].startswith("IN THE NEWS") and len(out) == 5


def test_no_snapshot_still_works():
    assert picker.rank([("Volcano", "evergreen")], snapshot={}) == ["Volcano"]


def test_consumer_products_are_never_ranked_even_if_regex_matches():
    items = [("Samsung Galaxy Buds On", "wiki"), ("Galaxy cluster", "evergreen"), ("ChatGPT news", "news"), ("Black hole", "evergreen")]
    out = picker.rank(items, snapshot={})
    assert "Samsung Galaxy Buds On" not in out and "ChatGPT news" not in out and "Galaxy cluster" in out
