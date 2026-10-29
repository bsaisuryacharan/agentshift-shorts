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
