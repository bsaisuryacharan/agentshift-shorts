"""Rank topic candidates before the LLM chooses, so the choice is made among ideas that fit the channel instead of whatever Google Trends or Wikipedia's most-read list holds
(celebrities, sports, phone reviews).

    rank(items) -> the best candidates first, with off-niche trend/most-read items removed

Signals, all from committed files the cloud already has: the niche filter (insights.NICHE), current science news (weekly job), the owner's own per-Short results
(assets/vidiq.json channel analytics: which topics earned views) and the vidIQ search terms / breakout titles. Advisory ordering only; the LLM still decides and every fact
still comes from Wikipedia.
"""
from __future__ import annotations

import re

from . import insights, vidiq

STOP = {"the", "a", "an", "of", "to", "and", "in", "is", "are", "your", "you", "why", "how", "what", "that", "for", "on", "it", "do", "does", "can", "with"}
SOURCE_BONUS = {"news": 2.0, "evergreen": 1.0, "trend": 0.0, "wiki": 0.0}


PRODUCT = re.compile(r"\b(?:samsung|galaxy (?:buds|watch|s\d|z|tab|note|fold|flip)|iphone|ipad|airpods|macbook|pixel \d|oneplus|xiaomi|redmi|tecno|realme|huawei|playstation|xbox|nintendo|"
                     r"review|unboxing|vs\.? (?:apple|samsung|android)|price|discount|deal|sale|buds|earbuds|smartwatch|chatgpt|openai|gpt-?\d|gemini|claude|grok)\b", re.I)


def _words(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{4,}", s.lower()) if w not in STOP}


def winner_words(snapshot: dict | None = None) -> dict[str, float]:
    """word -> weight from the channel's own Shorts: views above the channel median push their topic words up, flops push them down"""
    ch = (snapshot if snapshot is not None else vidiq.load()).get("channel") or {}
    shorts = ch.get("shorts") or []
    if not shorts:
        return {}
    med = ch.get("median_views_per_short_after_1_week") or 26
    out: dict[str, float] = {}
    for s in shorts:
        ratio = max(s.get("views", 0), 1) / max(med, 1)
        w = 1.5 if ratio >= 20 else 0.8 if ratio >= 5 else -0.4 if ratio <= 1.5 else 0.0
        for word in _words(s["title"] + " " + s.get("topic", "")):
            if w > 0:
                out[word] = max(out.get(word, 0.0), w)
            elif w < 0 and out.get(word, 0.0) <= 0:
                out[word] = min(out.get(word, 0.0), w)
    return out


def score(text: str, source: str, ww: dict[str, float]) -> float:
    if PRODUCT.search(text):
        return -99.0                                   # consumer products and AI-brand news: not this channel, whatever the source
    niche = bool(insights.NICHE.search(text))
    if source in ("trend", "wiki") and not niche:
        return -99.0                                   # popular is not the same as on-niche
    s = SOURCE_BONUS.get(source, 0.0) + (3.0 if niche else 0.0)
    s += sum(ww.get(w, 0.0) for w in _words(text))
    return s


def rank(items: list[tuple[str, str]], limit: int = 24, snapshot: dict | None = None) -> list[str]:
    """items: (text, source) with source in news|evergreen|trend|wiki; returns texts, best first, at most `limit`, off-niche trend/wiki items dropped"""
    ww = winner_words(snapshot)
    scored = [(score(t, src, ww), i, t) for i, (t, src) in enumerate(items)]
    scored = [x for x in scored if x[0] > -50]
    scored.sort(key=lambda x: (-x[0], x[1]))
    seen, out = set(), []
    for _, _, t in scored:
        k = re.sub(r"[^a-z0-9]", "", t.lower())
        if k not in seen:
            seen.add(k)
            out.append(t)
    return out[:limit]


def visual_coverage(subjects: list[str]) -> float:
    """share of a topic's subjects that have real moving pictures available (NASA clip index, then Pixabay/Pexels stock), 0-1.
    Cheap: the NASA index is a local file and stock is one search per subject. AI images of real objects are what the judge rejects most."""
    from . import footage
    subjects = [s for s in subjects if isinstance(s, str) and s.strip()][:4]
    if not subjects:
        return 0.0
    hit = 0
    for s in subjects:
        try:
            words = footage._terms(s)
            nasa = any(i["hits"] >= max(1, len(words) - 1) for i in footage.search_index(s, limit=6))   # NASA media is all real science: the distinctive word is enough
            stock = any(words and all(w in c.get("tags", "") for w in words) for c in footage.stock_candidates(s)) if not nasa else False
            if nasa or stock:                        # every word of the subject must be in the clip's title or tags: "brain" alone is not a Boltzmann brain
                hit += 1
        except Exception as e:                       # a probe failure must not stop the pick
            print(f"   coverage probe {s!r}: {type(e).__name__}", flush=True)
    return hit / len(subjects)


def best_option(options: list[dict], used: set[str], norm, min_coverage: float = 0.5) -> dict | None:
    """options from the LLM, each {topic, wiki, why, subjects}: drop used ones, score by real-picture coverage (and the candidate's niche fit), keep the best"""
    scored = []
    for o in options:
        if not isinstance(o, dict) or not o.get("wiki") or not o.get("topic") or norm(o["wiki"]) in used or PRODUCT.search(o["topic"] + " " + o["wiki"]):
            continue
        cov = visual_coverage(o.get("subjects") or [])
        niche = 1.0 if insights.NICHE.search(o["topic"] + " " + o["wiki"]) else 0.0
        o["coverage"], o["score"] = round(cov, 2), round(3 * cov + niche, 2)
        print(f"   option: {o['topic']!r} coverage {cov:.2f} score {o['score']}", flush=True)
        scored.append(o)
    best = max(scored, key=lambda o: o["score"]) if scored else None
    if best and best["coverage"] < min_coverage:
        print(f"   best option has too few real pictures ({best['coverage']:.0%}); asking for more filmable topics", flush=True)
        return None
    return best
