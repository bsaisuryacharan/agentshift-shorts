"""Researcher: Wikipedia is the base; with a free Tavily key (TAVILY_API_KEY, 1,000 searches/month) it adds the best pages from trusted sources.

    enrich(facts, topic, wiki_title) -> facts with each extra source appended as a labelled block, and facts["extra_sources"] = [url, ...]

Only allow-listed domains are used (space agencies, science bodies, research summaries, established science and tech news). The script may use a
fact only if FACTS state it; the number check (auto._number_supported) and the judge both see every source. Without a key, or if search fails,
the Short is made from Wikipedia alone, exactly as before.
"""
from __future__ import annotations

import os
import re
from urllib.parse import urlparse

import httpx

TRUSTED = ["nasa.gov", "jpl.nasa.gov", "esa.int", "noaa.gov", "usgs.gov", "si.edu", "nature.com", "science.org", "sciencenews.org", "sciencedaily.com",
           "phys.org", "livescience.com", "space.com", "quantamagazine.org", "scientificamerican.com", "newscientist.com", "nationalgeographic.com",
           "britannica.com", "arxiv.org", "nih.gov", "smithsonianmag.com", "spectrum.ieee.org", "technologyreview.com", "arstechnica.com",
           "theverge.com", "wired.com", "bbc.com", "reuters.com", "apnews.com", "history.com"]
PER_SOURCE = 2200
MAX_SOURCES = 5


def _clean(text: str) -> str:
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)|\[([^\]]*)\]\([^)]*\)", r"\1", text or "")      # drop markdown images, keep link text
    return re.sub(r"\s+", " ", text).strip()


def search(query: str, key: str, client=httpx) -> list[dict]:
    body = {"query": query, "search_depth": "basic", "max_results": 8, "include_domains": TRUSTED, "include_raw_content": True}
    r = client.post("https://api.tavily.com/search", headers={"Authorization": f"Bearer {key}"}, timeout=40, json=body)
    if r.status_code in (401, 403):                     # older keys authenticate in the body
        r = client.post("https://api.tavily.com/search", timeout=40, json={**body, "api_key": key})
    if r.status_code >= 400:
        print(f"   research: Tavily HTTP {r.status_code}: {r.text[:160]}", flush=True)
    r.raise_for_status()
    return r.json().get("results", [])


def enrich(facts: dict, topic: str, wiki_title: str | None = None, key: str | None = None, client=httpx) -> dict:
    key = key or os.environ.get("TAVILY_API_KEY")
    if not key:
        return facts
    try:
        results = search(f"{wiki_title or topic}: {topic}"[:300], key, client)
    except (httpx.HTTPError, ValueError) as e:
        print(f"   research: web search unavailable ({type(e).__name__}); Wikipedia only", flush=True)
        return facts
    blocks, urls, domains = [], [], set()
    for r in results:
        url = r.get("url", "")
        dom = urlparse(url).netloc.removeprefix("www.")
        if not url or dom in domains or "wikipedia.org" in dom or not any(dom == t or dom.endswith("." + t) for t in TRUSTED):
            continue
        text = _clean(r.get("raw_content") or r.get("content") or "")
        if len(text) < 200:
            continue
        domains.add(dom)
        urls.append(url)
        blocks.append(f"SOURCE {dom} ({url}):\n{text[:PER_SOURCE]}")
        if len(blocks) >= MAX_SOURCES:
            break
    if not blocks:
        print("   research: no trusted pages found; Wikipedia only", flush=True)
        return facts
    print(f"   research: + {len(blocks)} sources: {', '.join(sorted(domains))}", flush=True)
    return {**facts, "text": facts["text"] + "\n\n" + "\n\n".join(blocks), "extra_sources": urls}
