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
    items = [("Samsung Galaxy Buds On", "wiki"), ("Galaxy cluster", "evergreen"), ("5 ChatGPT prompts tutorial", "news"), ("Black hole", "evergreen"),
             ("IN THE NEWS: OpenAI's new chip explained", "news"), ("iPhone 18 review and price", "trend")]
    out = picker.rank(items, snapshot={})
    assert "Samsung Galaxy Buds On" not in out and "5 ChatGPT prompts tutorial" not in out and "iPhone 18 review and price" not in out
    assert "Galaxy cluster" in out and "IN THE NEWS: OpenAI's new chip explained" in out          # tech news explained is in scope


def test_winner_and_news_filters():
    from app import insights
    assert insights.good_winner("How Submarines Make Their Own Air and Fresh Water")
    assert not insights.good_winner("IKAN LELE SAMA BELUT #facts #animals")
    assert not insights.good_winner("Most Incredible Animal Moments | Ep 15 #hindi")
    assert insights.OFF_NEWS.search("Low-dose aspirin linked to 70% lower dementia risk")
    assert not insights.OFF_NEWS.search("Three giant black holes discovered in a galaxy from the dawn of time")


def test_filters_catch_foreign_medical_and_admin_items():
    from app import insights
    for t in ("Animales Que Fueron Encontrados Dentro de la Comida", "Is Machhli Ne Apne Hi Bachhon Ke Qatil Ko Paala!", "Hannah Fry on The Nun Study #dementia"):
        assert not insights.good_winner(t), t
    for n in ("Six popular sugar substitutes linked to faster brain aging", "NASA Names Troy Asher Armstrong Flight Research Center Director",
              "Envía tu nombre a Titán a bordo de la misión Dragonfly", "The autistic brain processes faces differently"):
        assert insights.OFF_NEWS.search(n), n
    for keep in ("NASA discovers Jupiter's invisible shield is more complex than thought", "128,000-year-old ice in Tibet could rewrite climate history"):
        assert not insights.OFF_NEWS.search(keep), keep
    assert insights.good_winner("Why Must You Take Steps on a Spinning Ride? Physics Explained")
