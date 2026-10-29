"""Live, provenance-preserving trend analysis for short-form editorial selection."""
from __future__ import annotations

import logging
import html
import re
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta
from urllib.parse import quote_plus

import httpx

from .analytics import channel_analytics
from .models import Idea, TrendReport, TrendSignal
from .providers import research_nasa_sources, research_sources
from .settings import Settings

logger = logging.getLogger(__name__)

COMMERCIAL_TERMS = {"fund", "funding", "crore", "venture", "vc", "ipo", "startup", "gadget", "sale", "deal", "price", "buy", "smartphone", "investment", "market", "revenue", "stock"}
OUTREACH_TERMS = {"ncaa", "fans", "university", "flyover", "astronaut", "event", "contest", "engage"}
def _in_scope(title: str) -> bool:
    words = set(re.findall(r"[a-z]+", title.lower()))
    # Direct-source verification and evidence from the channel determine relevance. Do not bake
    # an old science assumption into discovery just because it was used for an earlier test.
    return not bool(words & (COMMERCIAL_TERMS | OUTREACH_TERMS))


def _youtube_short_signals(settings: Settings) -> list[TrendSignal]:
    if not settings.youtube_api_key:
        return []
    response = httpx.get("https://www.googleapis.com/youtube/v3/videos", params={
        "part": "snippet,statistics,contentDetails", "chart": "mostPopular", "regionCode": settings.trend_region,
        "videoCategoryId": "28", "maxResults": 25, "key": settings.youtube_api_key,
    }, timeout=25)
    response.raise_for_status()
    observed = datetime.now(UTC); found = []
    for video in response.json().get("items", []):
        snippet = video["snippet"]; title = snippet["title"]
        if not _in_scope(title):
            continue
        # The API exposes popular videos, not a canonical global Shorts feed. Duration and vertical
        # metadata are not reliable Shorts labels, so the report calls this a short-form candidate.
        found.append(TrendSignal(source="youtube", format="short_form_candidate", title=title,
                                 url=f"https://www.youtube.com/watch?v={video['id']}", observed_at=observed,
                                 published_at=datetime.fromisoformat(snippet["publishedAt"]),
                                 metric=int(video.get("statistics", {}).get("viewCount", 0)), short_form_confidence=0.45,
                                 notes="Popular Science & Technology video; verify Short format before using as format inspiration."))
    return found


NICHE_SEARCHES = ["space facts", "science explained", "history mystery", "how it works engineering", "nature facts animals", "physics explained",
                  "tech explained", "tech news explained"]
SCIENCE_FEEDS = {"ScienceDaily": "https://www.sciencedaily.com/rss/top/science.xml", "NASA": "https://www.nasa.gov/news-release/feed/",
                 "ESA": "https://www.esa.int/rssfeed/Our_Activities/Space_Science", "Quanta": "https://www.quantamagazine.org/feed/",
                 "IEEE Spectrum": "https://spectrum.ieee.org/feeds/feed.rss", "MIT Technology Review": "https://www.technologyreview.com/feed/"}


def _youtube_niche_signals(settings: Settings, client=httpx, days: int = 14) -> list[TrendSignal]:
    """what is working RIGHT NOW in this channel's niche: short science/space/history/nature videos from the last two weeks, ranked by views per hour.
    (The old signal was the generic 'most popular in Science & Technology' chart, which is mostly phone reviews.) Costs ~600 of the free 10,000 daily API units."""
    if not settings.youtube_api_key:
        return []
    since = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    ids: dict[str, str] = {}
    for q in NICHE_SEARCHES:
        r = client.get("https://www.googleapis.com/youtube/v3/search", params={"part": "snippet", "q": q, "type": "video", "videoDuration": "short", "order": "viewCount",
                       "publishedAfter": since, "relevanceLanguage": "en", "regionCode": "US", "maxResults": 8, "key": settings.youtube_api_key}, timeout=25)
        r.raise_for_status()
        for it in r.json().get("items", []):
            ids.setdefault(it["id"]["videoId"], q)
    if not ids:
        return []
    r = client.get("https://www.googleapis.com/youtube/v3/videos", params={"part": "snippet,statistics,contentDetails", "id": ",".join(list(ids)[:50]), "key": settings.youtube_api_key}, timeout=25)
    r.raise_for_status()
    now = datetime.now(UTC)
    found = []
    for v in r.json().get("items", []):
        sn, st = v["snippet"], v.get("statistics", {})
        published = datetime.fromisoformat(sn["publishedAt"].replace("Z", "+00:00"))
        age_h = max(1.0, (now - published).total_seconds() / 3600)
        views = int(st.get("viewCount", 0))
        if views < 20000 or not _in_scope(sn["title"]):
            continue
        found.append(TrendSignal(source="youtube", format="niche_short", title=html.unescape(sn["title"]), url=f"https://www.youtube.com/watch?v={v['id']}", observed_at=now,
                                 published_at=published, metric=views, short_form_confidence=0.8,
                                 notes=f"niche search '{ids[v['id']]}': {views:,} views in {age_h / 24:.1f} days = {views / age_h:,.0f} views/hour; study the hook and format, never copy."))
    found.sort(key=lambda s: -(s.metric or 0) / max(1.0, (now - s.published_at).total_seconds() / 3600))
    return found[:15]


def _science_feed_signals(settings: Settings, client=httpx) -> list[TrendSignal]:
    """current science/space stories straight from primary publishers (ScienceDaily, NASA, ESA, Quanta), not keyword-matched Google News"""
    observed, found, seen = datetime.now(UTC), [], set()
    for name, url in SCIENCE_FEEDS.items():
        try:
            r = client.get(url, timeout=25, follow_redirects=True)
            r.raise_for_status()
            root = ET.fromstring(r.content)
        except (httpx.HTTPError, ET.ParseError) as e:
            logger.warning("feed %s unavailable: %s", name, e)
            continue
        for item in root.findall("./channel/item")[:8]:
            title, link = (item.findtext("title") or "").strip(), (item.findtext("link") or "").strip()
            if title and link and title.lower() not in seen and _in_scope(title):
                seen.add(title.lower())
                found.append(TrendSignal(source="science_feed", format="news", title=title, url=link, observed_at=observed, short_form_confidence=0.2,
                                         notes=f"{name}: primary-source story; verify facts on the page before scripting."))
    return found


def _news_signals(settings: Settings) -> list[TrendSignal]:
    # A single many-word Google News query can collapse into irrelevant local aggregation. Search
    # each configured interest lane independently, retain the lane in the evidence packet, and
    # require title-level relevance before a source can reach editorial discovery.
    lanes = list(dict.fromkeys(re.findall(r"[a-zA-Z]{3,}", settings.trend_query.lower())))
    observed = datetime.now(UTC); found: list[TrendSignal] = []; seen: set[tuple[str, str]] = set()
    for lane in lanes[:8]:
        query = f"{lane} when:7d"
        response = httpx.get(f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=en-IN&gl=IN&ceid=IN:en", timeout=25)
        response.raise_for_status(); root = ET.fromstring(response.content)
        for item in root.findall("./channel/item")[:8]:
            title, link = item.findtext("title") or "", item.findtext("link") or ""
            key = (title.lower(), link)
            title_words = set(re.findall(r"[a-z]+", title.lower()))
            if title and link and key not in seen and lane in title_words and _in_scope(title):
                seen.add(key)
                found.append(TrendSignal(source="google_news_rss", format="news", title=title, url=link,
                                         observed_at=observed, short_form_confidence=0.20,
                                         notes=f"{lane.title()} discovery lane; direct source required before scripting."))
    return found


def _reels_signals(settings: Settings) -> list[TrendSignal]:
    """Read only the connected account's Reels; Meta offers no public global-Reels trend feed."""
    if not (settings.instagram_access_token and settings.instagram_business_account_id):
        return []
    response = httpx.get(f"https://graph.facebook.com/v22.0/{settings.instagram_business_account_id}/media", params={
        "fields": "caption,permalink,timestamp,media_product_type,like_count,comments_count", "limit": 25,
        "access_token": settings.instagram_access_token,
    }, timeout=25)
    response.raise_for_status(); observed = datetime.now(UTC); found = []
    for item in response.json().get("data", []):
        if item.get("media_product_type") != "REELS":
            continue
        caption = item.get("caption", "").splitlines()[0][:160]
        if caption and _in_scope(caption):
            found.append(TrendSignal(source="instagram_connected_account", format="reels", title=caption,
                                     url=item.get("permalink", ""), observed_at=observed,
                                     published_at=datetime.fromisoformat(item["timestamp"]),
                                     metric=int(item.get("like_count", 0)) + int(item.get("comments_count", 0)),
                                     short_form_confidence=1.0, notes="Performance signal from the connected account only."))
    return found


def analyze(settings: Settings) -> TrendReport:
    signals: list[TrendSignal] = []; status: dict[str, str] = {}
    try:
        performance = channel_analytics(settings)
        status["channel_analytics"] = performance["status"]
    except Exception as error:  # noqa: BLE001 - no analytics must never masquerade as zero performance
        logger.warning("Channel analytics unavailable: %s", error)
        status["channel_analytics"] = f"unavailable: {type(error).__name__}"
    for name, loader in (("youtube", _youtube_niche_signals), ("news", _science_feed_signals), ("reels", _reels_signals)):
        try:
            loaded = loader(settings)
            signals.extend(loaded)
            if loaded:
                status[name] = "ok"
            elif name == "reels" and not (settings.instagram_access_token and settings.instagram_business_account_id):
                status[name] = "not configured (optional connected-account Reels feed)"
            else:
                status[name] = "configured but no in-scope signals"
        except Exception as error:  # noqa: BLE001 - a weak signal must not block primary-source discovery
            logger.warning("Trend source %s failed: %s", name, error); status[name] = f"unavailable: {type(error).__name__}"
    try:
        for source in research_nasa_sources(12):
            if _in_scope(source.title):
                signals.append(TrendSignal(source="nasa", format="primary_source", title=source.title, url=str(source.url),
                                           observed_at=datetime.now(UTC), published_at=source.retrieved_at,
                                           short_form_confidence=0.0, notes="Primary-source editorial candidate."))
        status["primary_sources"] = "ok"
    except Exception as error:  # noqa: BLE001
        status["primary_sources"] = f"unavailable: {type(error).__name__}"
    report = TrendReport(generated_at=datetime.now(UTC), region=settings.trend_region, signals=signals, source_status=status)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    (settings.data_dir / "latest_trend_report.json").write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return report


def _overlap_ratio(title: str, recent_scripts: list[str]) -> float:
    """Worst shared-word ratio between a candidate title and any recent narration."""
    title_words = set(re.findall(r"[a-z]{4,}", title.lower()))
    shared = 0.0
    for script in recent_scripts:
        old_words = set(re.findall(r"[a-z]{4,}", script.lower()))
        shared = max(shared, len(title_words & old_words) / max(len(title_words), 1))
    return shared


def _topic_is_fresh(title: str, recent_scripts: list[str]) -> bool:
    return _overlap_ratio(title, recent_scripts) < 0.25


def _news_priority(signal: TrendSignal) -> tuple[int, str]:
    """Try primary/institutional reporting before low-accountability aggregation."""
    title = signal.title.lower()
    authoritative = ("nasa", "cern", "department", "energy", "unesco", "un", "nature", "microsoft", "cloudflare", "university")
    return (0 if any(term in title for term in authoritative) else 1, title)


def discover(
    settings: Settings,
    recent_scripts: list[str] | None = None,
    excluded_source_urls: set[str] | None = None,
) -> Idea:
    report = analyze(settings)
    recent_scripts = recent_scripts or []
    excluded_source_urls = excluded_source_urls or set()
    # Test directly verifiable current-news candidates before returning to the NASA fallback lane.
    # This keeps the editorial pool broad while preserving the same factual-source requirement.
    news = sorted((signal for signal in report.signals if signal.format == "news"), key=_news_priority)
    for signal in news[:4]:
        if signal.url in excluded_source_urls or not _topic_is_fresh(signal.title, recent_scripts):
            continue
        try:
            sources = research_sources(signal.title)
            if sources:
                return Idea(
                    title=signal.title[:95],
                    angle="Start with a specific everyday consequence, then explain the verified mechanism. "
                    "Use the channel monitor's current guidance for pacing and payoff—not as a claim source.",
                    score=74,
                    sources=sources,
                )
        except Exception as error:  # noqa: BLE001
            logger.warning("News candidate could not be directly verified: %s", error)
            continue
    # NASA is a dependable verified fallback, not the channel's permanent topic restriction.
    primary = [
        signal for signal in report.signals
        if signal.format == "primary_source" and signal.url not in excluded_source_urls
    ]
    if primary:
        fresh = [signal for signal in primary if _topic_is_fresh(signal.title, recent_scripts)]
        if fresh:
            selected = fresh[0]
        else:
            # Every brand-owned feed shares house words (e.g. "NASA") with *any* prior narration,
            # so a hard reject would deadlock the primary lane. Degrade to the least-overlapping
            # candidate instead of repeating the run; only a near-identical title still hard-fails.
            selected = min(primary, key=lambda signal: _overlap_ratio(signal.title, recent_scripts))
            if _overlap_ratio(selected.title, recent_scripts) >= 0.9:
                raise RuntimeError("All current primary-source candidates overlap recently approved topics.")
        sources = research_nasa_sources(12)
        source = next(source for source in sources if str(source.url) == selected.url)
        corroboration = sum(1 for signal in report.signals if signal.title.lower().split()[0] in selected.title.lower())
        return Idea(title=source.title[:95], angle="Explain the mechanism, using current short-form signals only for packaging—not claims.",
                    score=min(100, 82 + corroboration * 3), sources=[source])
    raise RuntimeError("No primary or directly verifiable trend candidate survived discovery.")
