"""Video formats the channel rotates through, so it is not 'what if...?' every time.

The code (not the model) chooses the next format: the one used least recently, never one of the last two. A format sets the opening bubble word, how the
hook is phrased, the shape of the beats and a title framing. app.insights/playbook can later add a boost for formats that perform better.
"""
from __future__ import annotations

import random

FORMATS: dict[str, dict] = {
    "what_if": {"label": "WHAT IF", "bubble": "what if?", "tag": "whatif", "frame": "What if {s} changed everything?",
                "hook": "a surprising hypothetical stated as a question", "shape": "set the scenario, escalate with real numbers, reveal the twist or the limit, honest verdict"},
    "how_it_works": {"label": "HOW IT WORKS", "bubble": "how?", "tag": "howitworks", "frame": "How it works: {s}",
                     "hook": "something everyone uses or sees but few can explain, as a puzzle", "shape": "the puzzle, the hidden mechanism step by step (use chain or rows), the surprising consequence"},
    "myth_vs_fact": {"label": "MYTH VS FACT", "bubble": "true?", "tag": "mythbusting", "frame": "The truth about {s}",
                     "hook": "state a common belief confidently, then say it is wrong or only half right", "shape": "the belief, why people believe it, the evidence, the real answer with a number"},
    "unsolved": {"label": "UNSOLVED", "bubble": "why?", "tag": "mystery", "frame": "Nobody can fully explain {s}",
                 "hook": "a real, documented oddity that science has not settled", "shape": "the oddity, what we do know, the leading explanations, what is still open"},
    "ranked": {"label": "TOP 5", "bubble": "top 5", "tag": "top5", "frame": "5 extreme facts about {s}",
               "hook": "announce a countdown of 3-5 real extreme facts, biggest last", "shape": "one beat per item with its own number on screen, a bigger one each time, a payoff item last"},
    "versus": {"label": "VERSUS", "bubble": "vs", "tag": "versus", "frame": "{s} versus its closest rival",
               "hook": "two real things pitted against each other with one surprising number", "shape": "side one, side two (use bars or rows with real values), the verdict and the catch"},
    "timeline": {"label": "TIMELINE", "bubble": "when?", "tag": "history", "frame": "How {s} happened, date by date",
                 "hook": "the shortest honest version of how something went from A to B", "shape": "3-5 dated milestones (use chain or list), the turning point, where it stands now"},
    "scale": {"label": "SCALE", "bubble": "how big?", "tag": "scale", "frame": "How big is {s}, really?",
              "hook": "a number too big or small to feel, then a human-sized comparison", "shape": "the raw number, three comparisons that climb, the one that makes it land"},
    "story": {"label": "THE STORY", "bubble": "story", "tag": "story", "frame": "The story behind {s}",
              "hook": "one real photo or event and the detail nobody mentions", "shape": "the scene, who/what was involved, what happened next, why it still matters"},
}
ORDER = list(FORMATS)


def choose(recent: list[str], rng: random.Random | None = None, boost: dict[str, float] | None = None) -> str:
    """least recently used format; never one of the last two used; ties broken at random (or by boost)"""
    rng = rng or random.Random()
    banned = set(recent[-2:])
    pool = [f for f in ORDER if f not in banned] or ORDER
    last_seen = {f: (len(recent) - max((i for i, r in enumerate(recent) if r == f), default=-1 - len(recent))) for f in pool}
    best = max(last_seen.values())
    oldest = [f for f, v in last_seen.items() if v == best]
    if boost:
        oldest.sort(key=lambda f: -boost.get(f, 0))
        oldest = [f for f in oldest if boost.get(f, 0) == boost.get(oldest[0], 0)]
    return rng.choice(oldest)


def frame(name: str, subject: str) -> str:
    return FORMATS[name]["frame"].format(s=subject)


def prompt_block(name: str) -> str:
    f = FORMATS[name]
    return (f"FORMAT for this Short: {name} ({f['label']}). Opening bubble text: \"{f['bubble']}\" (hud bubble in the hook beat). Hook: {f['hook']}. "
            f"Shape of the beats: {f['shape']}. Set top-level \"format\": \"{name}\" and \"series_label\": \"{f['label']}\". "
            "Do NOT frame the title or the narration as 'what if' unless this format is what_if.")
