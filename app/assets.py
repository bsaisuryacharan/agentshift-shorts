"""Adopt first-party editorial assets before resorting to generated illustration."""
from __future__ import annotations

import hashlib
import io
import re
from pathlib import Path
from urllib.parse import quote_plus, urljoin, urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup
from PIL import Image

from .models import Source
from .providers import ProviderError


def _perceptual_duplicate(kept: list[Image.Image], content: bytes, threshold: int = 26) -> bool:
    """Two res of the same photo cost a beat; drop images that look identical at thumbnail size.

    Same-scene photos at different resolutions pass a byte hash check but still read as
    "the same subject everywhere" on a contact sheet — an independent review repeatedly
    flagged exactly that. First-party variety is measured, not assumed.
    """
    try:
        candidate = Image.open(io.BytesIO(content)).convert("RGB").resize((32, 32))
    except Exception:  # noqa: BLE001 - an unreadable image is useless regardless
        return False
    for existing in kept:
        diff = existing.resize((32, 32))
        total = sum(abs(a - b) for pa, pb in zip(candidate.getdata(), diff.getdata()) for a, b in zip(pa, pb))
        if total / (32 * 32 * 3) < threshold:
            return True
    kept.append(candidate)
    return False


def adopt_primary_image(source: Source, destination: Path) -> tuple[Path, dict[str, str]]:
    """Download one publicly served official article image with provenance for editorial use.

    If no usable first-party image is exposed, callers should degrade to generated illustration and
    let the visual gate decide—not fabricate a claim-specific visual.
    """
    page = httpx.get(str(source.url), headers={"User-Agent": "ShortsFactory/1.0"}, timeout=25)
    page.raise_for_status()
    soup = BeautifulSoup(page.text, "html.parser")
    image_url = None
    for selector, attribute in (("meta[property='og:image']", "content"), ("meta[name='twitter:image']", "content")):
        tag = soup.select_one(selector)
        if tag and tag.get(attribute):
            image_url = str(tag[attribute]); break
    if not image_url:
        raise ProviderError("Primary source page exposes no usable social image.")
    image = httpx.get(image_url, headers={"User-Agent": "ShortsFactory/1.0"}, timeout=45)
    image.raise_for_status()
    if not image.headers.get("content-type", "").startswith("image/"):
        raise ProviderError("Primary-source social image did not return an image.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(image.content)
    return destination, {"asset_url": image_url, "article_url": str(source.url), "publisher": source.publisher,
                         "usage": "First-party editorial source asset; retain provenance in the run packet."}


def adopt_source_images(
    source: Source, destination: Path, limit: int = 7, visual_queries: list[str] | None = None,
) -> tuple[list[Path], list[dict[str, str]]]:
    """Download distinct article images with provenance; a Short cannot rely on one static photo.

    This deliberately selects only images directly referenced by the source article. It never
    searches competitor media, stock libraries, or generated illustrations to pad visual variety.
    """
    page = httpx.get(str(source.url), headers={"User-Agent": "ShortsFactory/1.0"}, timeout=25)
    page.raise_for_status()
    soup = BeautifulSoup(page.text, "html.parser")
    article = soup.find("article") or soup.find("main")
    if article is None:
        raise ProviderError("Source page has no identifiable article body for asset extraction.")
    candidates: list[tuple[str, str, str]] = []
    # Social cards describe the article. Additional images must come from the article body,
    # never navigation, recommendations, or another NASA story elsewhere on the page.
    for selector, attribute, root in (
        ("meta[property='og:image']", "content", soup),
        ("meta[name='twitter:image']", "content", soup),
        ("img", "src", article),
        ("img", "data-src", article),
    ):
        for tag in root.select(selector):
            # A page's related-article carousel is not evidence for the article we are adapting.
            # It previously made an unrelated El Nino card look like a visual asset for a JPL
            # history story.  Keep only the article's own editorial media; a source with too few
            # images is deliberately rejected by the source-asset gate upstream.
            if selector == "img" and _non_editorial_image_context(tag, article):
                continue
            value = tag.get(attribute)
            if value:
                candidate = urljoin(str(source.url), str(value))
                alt_text = str(tag.get("alt") or "").strip()[:400]
                if candidate not in {item[0] for item in candidates}:
                    candidates.append((candidate, alt_text, "First-party article image; retained with run provenance."))
    # NASA's news pages sometimes deliberately expose one hero visual and keep the rest of their
    # mission imagery in NASA Images.  That is still first-party media from the same agency, unlike
    # related-article cards; enrich it with labeled official catalog media so the renderer has
    # genuinely distinct, claim-adjacent scenes to choose from.
    if "nasa.gov" in str(source.url).lower() and len(candidates) < limit:
        candidates.extend(_nasa_catalog_candidates(source, {item[0] for item in candidates}, limit * 2, visual_queries))
    paths: list[Path] = []
    provenance: list[dict[str, str]] = []
    seen_content: set[str] = set()
    seen_canonical_urls: set[str] = set()
    kept_signatures: list[Image.Image] = []
    for index, (image_url, alt_text, usage) in enumerate(candidates):
        if len(paths) >= limit:
            break
        parsed = urlsplit(image_url)
        canonical_url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
        if canonical_url in seen_canonical_urls:
            continue
        try:
            image = httpx.get(image_url, headers={"User-Agent": "ShortsFactory/1.0"}, timeout=45)
            image.raise_for_status()
        except httpx.HTTPError:
            continue
        if not image.headers.get("content-type", "").startswith("image/") or len(image.content) < 15_000:
            continue
        content_hash = hashlib.sha256(image.content).hexdigest()
        if content_hash in seen_content:
            continue
        seen_content.add(content_hash)
        if _perceptual_duplicate(kept_signatures, image.content):
            continue
        if _map_like_graphic(image.content):
            continue
        seen_canonical_urls.add(canonical_url)
        target = destination / f"source-{len(paths) + 1:02}.jpg"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(image.content)
        paths.append(target)
        provenance.append({"asset_url": image_url, "alt_text": alt_text, "article_url": str(source.url), "publisher": source.publisher,
                           "usage": usage})
    if not paths:
        raise ProviderError("Source page exposes no usable article images.")
    return paths, provenance


def _map_like_graphic(content: bytes) -> bool:
    """Reject small, near-monochrome exports such as region maps and table thumbs.

    The previous run aligned a 300x150 uniform-grey world-map thumbnail with a beat about smoke;
    independent review scored that beat factual_visual_alignment 4-5 ("generic map for New Guinea")
    — a vector map is not event imagery for a wildfire claim.
    """
    try:
        candidate = Image.open(io.BytesIO(content)).convert("HSV")
    except Exception:  # noqa: BLE001 - an unreadable image would fail downstream anyway
        return False
    width, height = candidate.size
    if width > 640 and height > 400:
        return False  # full-size graphics can legitimately serve as editorial stills
    pixels = list(candidate.resize((48, 48)).getdata())
    saturation = sum(1 for _, s, _ in pixels if s < 40) / len(pixels)
    return saturation > 0.85


def _non_editorial_image_context(tag, article) -> bool:
    """Return whether an article image sits in metadata or a related-content module."""
    excluded = ("related", "topic-card", "article-meta", "avatar", "recommend", "newsletter")
    node = tag
    while node is not None and node is not article:
        classes = " ".join(node.get("class", [])) if getattr(node, "get", None) else ""
        if any(marker in classes.lower() for marker in excluded):
            return True
        node = node.parent
    return False


def _nasa_catalog_candidates(
    source: Source, seen_urls: set[str], maximum: int, visual_queries: list[str] | None = None,
) -> list[tuple[str, str, str]]:
    """Find labeled first-party NASA Images media when an official story has only a hero image."""
    lower_title = source.title.lower()
    queries = list(visual_queries or [])
    queries.append(source.title)
    # These are topic refinements, not claim sources.  Their labels are preserved for beat-to-asset
    # alignment and every resulting image remains in NASA's official media catalog.
    if "jpl" in lower_title:
        queries.extend(["JPL space missions", "Jet Propulsion Laboratory spacecraft"])
    if "artemis" in lower_title:
        queries.append("NASA Artemis mission")
    if "mars" in lower_title:
        queries.append("NASA Mars mission")
    found: list[tuple[str, str, str]] = []
    deferred: list[tuple[str, str, str]] = []
    blocked_titles = ("vice president", "tour", "conference", "portrait")
    per_query = 2
    for query in dict.fromkeys(queries):
        if len(found) >= maximum:
            break
        try:
            response = httpx.get(
                f"https://images-api.nasa.gov/search?q={quote_plus(query)}&media_type=image&page_size=20",
                headers={"User-Agent": "ShortsFactory/1.0"}, timeout=15,
            )
            response.raise_for_status()
        except httpx.HTTPError:
            continue
        data = response.json().get("collection", {}).get("items", [])
        # Strict pass: accept only catalog hits whose own text echoes the query's distinctive
        # terms. On-topic hits that miss one abstract word (for example "innovation") are
        # deferred, so a title query can still supply imagery when the strict hits fall short.
        accepted_strict = 0
        for item in data:
            if len(found) >= maximum or accepted_strict >= per_query:
                break
            hit = item.get("data", [{}])[0]
            title = str(hit.get("title") or "").strip()
            description = str(hit.get("description") or "").strip()
            links = item.get("links", [])
            href = next((str(link.get("href")) for link in links if link.get("href")), "")
            if not href or href in seen_urls or any(term in title.lower() for term in blocked_titles):
                continue
            # Preserve enough human-readable content for semantic beat matching without passing
            # arbitrary catalog markup into downstream prompts.
            hint = re.sub(r"\s+", " ", f"{title}. {description}").strip()[:700]
            if len(hint) < 12:
                continue
            terms = _specific_search_terms(query)
            hint_words = set(re.findall(r"[a-z0-9]{4,}", hint.lower()))
            # Model/mission names carry more meaning than generic words such as spacecraft.
            # A search including one must always be visible in the catalog metadata itself;
            # this hard filter never falls back.
            entity_terms = terms & {"explorer", "ranger", "ingenuity", "perseverance", "artemis"}
            if entity_terms and not (entity_terms & hint_words):
                continue
            if terms and not (terms & hint_words):
                if href not in {str(item_href) for item_href, _ in deferred}:
                    deferred.append((href, hint))
                seen_urls.add(href)
                continue
            seen_urls.add(href)
            found.append((href, hint, "NASA official media catalog image, selected by source-topic query; retained with run provenance."))
            accepted_strict += 1
    if len(found) < maximum:
        for href, hint in deferred:
            if len(found) >= maximum:
                break
            seen_urls.add(href)
            found.append((href, hint, "NASA official media catalog image, retained with run provenance."))
    return found
    if len(found) < maximum:
        for href, hint in deferred:
            if len(found) >= maximum:
                break
            if href in seen_urls or any(href == item[0] for item in found):
                continue
            seen_urls.add(href)
            found.append((href, hint, "NASA official media catalog image, retained with run provenance."))
    return found


def nasa_beat_queries(lines: list[str]) -> list[str]:
    """Convert a factual narration beat into a small set of precise NASA media searches."""
    queries: list[str] = []
    for line in lines:
        lowered = line.lower()
        if match := re.search(r"\bexplorer\s*(\d+)\b", lowered):
            queries.append(f"Explorer {match.group(1)} satellite")
        if match := re.search(r"\branger\s*(\d+)\b", lowered):
            queries.append(f"Ranger {match.group(1)} spacecraft")
        if "mars" in lowered and "helicopter" in lowered:
            queries.append("Ingenuity helicopter Mars")
        elif "mars" in lowered and "rover" in lowered:
            queries.append("NASA Mars rover")
        if "rocket" in lowered or "caltech" in lowered or "arroyo" in lowered:
            queries.append("NASA early rockets")
        if "moon" in lowered and not any("ranger" in query.lower() for query in queries[-2:]):
            queries.append("NASA Moon mission")
    return list(dict.fromkeys(queries))


def _specific_search_terms(query: str) -> set[str]:
    """Keep only meaningful terms for catalog-result relevance; omit agency boilerplate."""
    ignored = {"nasa", "jpl", "mission", "missions", "space", "looks", "next", "years", "firsts", "first", "future", "launch", "launched"}
    return {word for word in re.findall(r"[a-z0-9]{4,}", query.lower()) if word not in ignored}
