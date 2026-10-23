"""Real provider clients. All calls fail closed; no fake generations are substituted."""
from __future__ import annotations

import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
from bs4 import BeautifulSoup
from google import genai
from google.genai import types
from pydantic import ValidationError

from .models import Claim, CreativeTreatment, Review, Script, Source, VisualReview
from .playbook import writer_rules
from .settings import Settings


class ProviderError(RuntimeError):
    pass


def _readable_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    content = soup.find("article") or soup.find("main") or soup.body or soup
    return content.get_text(" ", strip=True)


class LLM:
    def __init__(self, settings: Settings, role: str):
        self.settings, self.role = settings, role

    def _prompt(self, instruction: str) -> str:
        return f"""You are the {self.role} for an original YouTube Shorts channel.
Channel niche: {self.settings.channel_niche}
Editorial voice: {self.settings.channel_voice}
Do not invent facts, sources, quotes, studies, statistics, or events.
Return only valid JSON matching the requested schema.\n\n{instruction}"""

    def json(self, instruction: str, schema: dict) -> dict:
        prompt = self._prompt(instruction)
        failures = []
        # Preserve Gemini's limited free request budget for the required image-contact-sheet
        # review. Scripts and editorial JSON can use the separately configured text provider.
        if self.settings.groq_api_key:
            try:
                response = httpx.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {self.settings.groq_api_key}"},
                    json={"model": "openai/gpt-oss-120b", "temperature": 0.35,
                          "response_format": {"type": "json_object"},
                          "messages": [{"role": "user", "content": prompt}]}, timeout=60,
                )
                response.raise_for_status()
                return json.loads(response.json()["choices"][0]["message"]["content"])
            except Exception as error:  # noqa: BLE001 - provider failover is intentional
                failures.append(f"Groq: {error}")
        if self.settings.gemini_api_key:
            try:
                client = genai.Client(api_key=self.settings.gemini_api_key)
                response = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=prompt,
                    config={"response_mime_type": "application/json", "response_json_schema": schema},
                )
                return json.loads(response.text)
            except Exception as error:  # noqa: BLE001 - SDK/provider errors must permit the configured failover
                failures.append(f"Gemini: {error}")
        raise ProviderError("All LLM providers failed: " + " | ".join(failures))


def research_sources(query: str) -> list[Source]:
    """Use Google News RSS only as discovery; citations are retained verbatim for editorial verification."""
    import xml.etree.ElementTree as ET
    from urllib.parse import quote_plus
    url = f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=en-IN&gl=IN&ceid=IN:en"
    response = httpx.get(url, timeout=20)
    response.raise_for_status()
    root = ET.fromstring(response.text)
    found = []
    # Keep discovery bounded: a blocked publisher must not hold an autonomous production cycle
    # for minutes before it can consider another verified source lane.
    for item in root.findall("./channel/item")[:4]:
        link = item.findtext("link")
        title = item.findtext("title") or "Untitled"
        publisher = (item.find("source").text if item.find("source") is not None else "Unknown")
        if link:
            # RSS is discovery only. Store the resolved publisher URL in the fact ledger,
            # never a search-engine wrapper, so every claim remains independently auditable.
            try:
                resolved = str(httpx.get(link, headers={"User-Agent": "ShortsFactory/1.0"}, follow_redirects=True, timeout=8).url)
            except httpx.HTTPError:
                continue
            # Google sometimes does not expose the publisher redirect to unattended clients.
            # Keep that discovery URL rather than fabricate a citation; editorial review must
            # then resolve it before release.
            if "news.google.com" in resolved:
                resolved = link
            try:
                article = httpx.get(resolved, headers={"User-Agent": "ShortsFactory/1.0"}, follow_redirects=True, timeout=8)
                article.raise_for_status()
                article_text = _readable_text(article.text)
                excerpt = article_text[:1800]
            except httpx.HTTPError:
                continue
            # A headline alone cannot support a factual script. The real article must contain
            # enough readable editorial evidence for a reviewer to trace the claim.
            if len(excerpt) < 300:
                continue
            found.append(Source(url=resolved, title=title, publisher=publisher,
                                retrieved_at=datetime.now(UTC), excerpt=excerpt))
    if not found:
        raise ProviderError("Research returned no sources; refusing to script an unsourced Short.")
    return found


def research_nasa_sources(limit: int = 6) -> list[Source]:
    """Use NASA's official feed as a reliable science discovery lane."""
    import xml.etree.ElementTree as ET

    feed = httpx.get("https://www.nasa.gov/news-release/feed/", headers={"User-Agent": "ShortsFactory/1.0"}, timeout=20)
    feed.raise_for_status()
    root = ET.fromstring(feed.content)
    found: list[Source] = []
    for item in root.findall("./channel/item")[:limit]:
        url = item.findtext("link")
        title = item.findtext("title") or "NASA update"
        if not url:
            continue
        try:
            article = httpx.get(url, headers={"User-Agent": "ShortsFactory/1.0"}, follow_redirects=True, timeout=20)
            article.raise_for_status()
            excerpt = _readable_text(article.text)[:1800]
        except httpx.HTTPError:
            continue
        if len(excerpt) >= 300:
            found.append(Source(url=url, title=title, publisher="NASA", retrieved_at=datetime.now(UTC), excerpt=excerpt))
    if not found:
        raise ProviderError("NASA feed returned no readable source articles.")
    return found


def generate_script(settings: Settings, topic: str, sources: list[Source]) -> Script:
    writer = LLM(settings, "script writer")
    schema = Script.model_json_schema()
    source_block = "\n".join(
        f"- S{index}: {source.title} | {source.publisher} | {source.url}\n  Evidence excerpt: {source.excerpt}"
        for index, source in enumerate(sources, 1)
    )
    script: Script | None = None
    repair = ""
    for attempt in range(3):
        result = writer.json(
            f"Create a 25-45 second Short about: {topic}. Use only these sources:\n{source_block}\n"
            "Schema rules: hook/body/ending are narration lines; hook must be 9 words or fewer, immediately specific, "
            "and promise the exact visual fact shown in frame one; title <= 70 chars; description contains sources. "
            "Use exactly 4 or 5 body lines, each no more than 13 words. Keep total narration below 95 words. "
            "The hook, every body item, and ending must be JSON strings only. Put citations only in the separate claims array. "
            "Each claim must use source_ids containing only the source labels supplied above (for example [\"S1\"]). "
            f"Never write URLs inside a claim.\nCreative playbook:\n{writer_rules()}\n{repair}", schema)
        try:
            candidate = Script.model_validate(result)
        except ValidationError as error:
            repair = f"Previous response violated the JSON schema ({error.error_count()} field errors). Return the exact schema only."
            continue
        # Provider output can be factual and schema-valid but verbose. Normalize only pacing
        # fields—not facts or citations—so a provider's formatting lapse cannot make a Short
        # ramble or exhaust retries. Editorial and visual gates still decide release.
        compact = candidate.model_copy(update={
            "hook": _truncate_words(candidate.hook, 9),
            "body": [_truncate_words(line, 13) for line in candidate.body[:5]],
            "ending": _truncate_words(candidate.ending, 14),
        })
        narration_words = len(compact.narration.split())
        if 4 <= len(compact.body) <= 5 and narration_words <= 95:
            script = compact
            break
        repair = (f"Previous response had hook={len(candidate.hook.split())} words, body_lines={len(candidate.body)}, "
                  f"total_words={narration_words}. Repair every limit exactly.")
    if script is None:
        script = _source_fallback_script(topic, sources)
    allowed = {f"S{index}" for index in range(1, len(sources) + 1)}
    if any(not set(claim.source_ids).issubset(allowed) for claim in script.claims):
        raise ProviderError("Writer returned an unknown source ID; script is not evidence-safe.")
    return script


def _truncate_words(text: str, limit: int) -> str:
    """Make a display/narration pacing limit deterministic without inventing a new claim."""
    words = text.split()
    if len(words) <= limit:
        return text
    return " ".join(words[:limit]).rstrip(" ,;:-") + "."


def _source_fallback_script(topic: str, sources: list[Source]) -> Script:
    """Create a deliberately plain, fully cited draft when a free provider breaks its schema.

    This is not an approval shortcut: the same visual and editorial gates still reject weak work.
    It prevents a format error from turning an otherwise well-sourced production run into a dead end.
    """
    source = sources[0]
    sentences = [" ".join(sentence.split()) for sentence in re.split(r"(?<=[.!?])\s+", source.excerpt)]
    usable = [sentence for sentence in sentences if 5 <= len(sentence.split()) <= 55 and "min read" not in sentence.lower()]
    if len(usable) < 4:
        raise ProviderError("Source evidence is too sparse for a deterministic fallback script.")
    body = [_truncate_words(sentence, 13) for sentence in usable[:5]]
    return Script(
        hook=_truncate_words(topic, 9),
        body=body,
        ending=_truncate_words(f"The source explains why this matters for {source.publisher}.", 14),
        title=_truncate_words(source.title, 11)[:70],
        description=f"Source-backed summary. Source: {source.publisher} (S1).",
        claims=[Claim(text=sentence, source_ids=["S1"], numeric=bool(re.search(r"\d", sentence))) for sentence in body],
    )


def review_video(settings: Settings, script: Script, qa_report: str) -> Review:
    # Independent role and low temperature reduce confirmation bias. Video frame review is added by renderer output.
    judge = LLM(settings, "independent editorial reviewer; never write scripts")
    result = judge.json(
        f"Review this script and machine QA report for release. Score each criterion 1-10. "
        f"Script: {script.model_dump_json()}\nQA: {qa_report}\n"
        "Policy=10 only if there are no misleading claims, IP concerns, or template-like/repetitive signals. "
        "Return precise repair notes if any score is below 8.", Review.model_json_schema())
    return Review.model_validate(result)


def review_candidate(settings: Settings, script: Script, treatment: CreativeTreatment, contact_sheet: Path) -> VisualReview:
    """Review decoded candidate frames, with an independent image-observer fallback.

    Gemini receives the contact sheet directly when it is available.  A temporary quota outage
    must not turn into text-only approval, so the bounded fallback first asks Cloudflare's
    image-to-text model to inspect the actual sheet, then has the separately configured text
    reviewer turn that observation into the same strict review schema.  Either component failing
    rejects the candidate; neither route can silently approve a video without image evidence.
    """
    instruction = f"""You are an independent motion-design reviewer. Inspect the chronological frames
in this contact sheet from a vertical YouTube Short. Every tile is one narrated beat, sampled a
quarter into its scene. Judge only what is visible.

Treatment: {treatment.model_dump_json()}
Script: {script.model_dump_json()}

Score hook, visual_hierarchy, motion_readability (does the sampled movement look intentional rather
than slideshow-like), composition, text_legibility, factual_visual_alignment, and originality 1-10.
Set verdict to approve only if every score is at least 8. repair_notes must name concrete visible fixes.
Do not reward effects for their own sake; reject generic templated, cluttered, illegible, or misleading work.
Reject accidental AI text, watermark-like marks, malformed lettering, or logos inside source imagery; intentional
overlay typography is allowed only when it is crisp, complete, and visually subordinate to the factual visual.
Return valid JSON matching the schema."""
    failures: list[str] = []
    if settings.gemini_api_key:
        # Transient quota blips are common on the free tier; one bounded retry with a backoff
        # avoids silently falling through to a weaker reviewer just from a momentary 429.
        for attempt in range(2):
            try:
                client = genai.Client(api_key=settings.gemini_api_key)
                response = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=[instruction, types.Part.from_bytes(data=contact_sheet.read_bytes(), mime_type="image/jpeg")],
                    config={"response_mime_type": "application/json", "response_json_schema": VisualReview.model_json_schema(), "temperature": 0.1},
                )
                print("[review] route=gemini-2.5-flash", flush=True)
                return _validate_visual_review(json.loads(response.text))
            except Exception as error:  # noqa: BLE001 - a second configured image reviewer may still be available
                failures.append(f"Gemini: {error}")
                if attempt == 0:
                    time.sleep(25)
        print("[review] route=gemini-failed -> observational fallback", flush=True)
    try:
        observation = _cloudflare_visual_observation(settings, contact_sheet)
        synthesizer = LLM(settings, "independent visual QA synthesizer; never write scripts")
        result = synthesizer.json(
            f"Turn the following image-model observation of an actual contact-sheet filmstrip into a strict visual review. "
            f"It is evidence, not a request to invent details.\n\nObservation:\n{observation}\n\n"
            f"Treatment: {treatment.model_dump_json()}\nScript: {script.model_dump_json()}\n\n"
            "Score hook, visual_hierarchy, motion_readability, composition, text_legibility, "
            "factual_visual_alignment, and originality 1-10. Verdict may be approve only when the observation "
            "directly supports all seven scores at 8 or above and names no generic, repetitive, unreadable, or "
            "misleading element. Otherwise set verdict=reject and give concrete repair_notes. Do not infer visual "
            "quality from the script alone.",
            VisualReview.model_json_schema(),
        )
        print("[review] route=cloudflare-llava+synthesizer", flush=True)
        return _validate_visual_review(result)
    except Exception as error:  # noqa: BLE001 - fail closed when either fallback component is unavailable
        failures.append(f"Cloudflare image review: {error}")
    raise ProviderError("Visual candidate review failed: " + " | ".join(failures))


def _cloudflare_visual_observation(settings: Settings, contact_sheet: Path) -> str:
    """Ask the configured Workers AI account for a literal, bounded contact-sheet observation.

    LLaVA is intentionally not asked to fabricate a JSON scorecard—the smaller model can echo
    score examples instead of judging the image.  It produces plain-language image evidence and
    the existing structured reviewer applies the scoring policy afterwards.
    """
    if not (settings.cloudflare_account_id and settings.cloudflare_api_token):
        raise ProviderError("No Cloudflare Workers AI credentials are configured for image review.")
    endpoint = (f"https://api.cloudflare.com/client/v4/accounts/{settings.cloudflare_account_id}/"
                "ai/run/@cf/llava-hf/llava-1.5-7b-hf")
    prompt = """You are reviewing a vertical social-video contact sheet of chronological frames.
Describe only visible evidence in three short sentences: (1) what changes through the sequence,
(2) whether the large on-screen text seems readable, and (3) one visible reason it could look
repetitive, generic, misleading, cluttered, or unpolished. If you cannot see a problem, say NONE.
Do not use scores, JSON, a template, or generic advice."""
    response = httpx.post(
        endpoint,
        headers={"Authorization": f"Bearer {settings.cloudflare_api_token}"},
        # Workers AI accepts image bytes as an integer array through its REST API.  This retains
        # the local contact sheet in the request rather than using an unverified remote image URL.
        json={"image": list(contact_sheet.read_bytes()), "prompt": prompt, "max_tokens": 180},
        timeout=60,
    )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("success"):
        raise ProviderError(f"Workers AI returned {payload.get('errors', 'an unknown error')}")
    observation = str(payload.get("result", {}).get("description", "")).strip()
    if len(observation) < 40:
        raise ProviderError("Workers AI returned too little visual evidence to review safely.")
    return observation


def _validate_visual_review(result: dict) -> VisualReview:
    """Normalize a harmless provider formatting lapse without manufacturing a visual judgment."""
    normalized = dict(result)
    # Groq occasionally nests the requested numeric fields under ``scores`` even when given a
    # flat JSON schema.  Flatten only recognized score names; no value is added or inferred.
    nested_scores = normalized.get("scores")
    if isinstance(nested_scores, dict):
        for key in (
            "hook", "visual_hierarchy", "motion_readability", "composition", "text_legibility",
            "factual_visual_alignment", "originality",
        ):
            if key not in normalized and key in nested_scores:
                normalized[key] = nested_scores[key]
    notes = normalized.get("repair_notes")
    if isinstance(notes, str):
        normalized["repair_notes"] = [notes] if notes.strip() else []
    verdict = normalized.get("verdict")
    if isinstance(verdict, str):
        normalized["verdict"] = verdict.strip().lower()
    return VisualReview.model_validate(normalized)


def generate_image(settings: Settings, prompt: str, destination: Path) -> Path:
    if not (settings.cloudflare_account_id and settings.cloudflare_api_token):
        raise ProviderError("Cloudflare Workers AI credentials are required for image generation.")
    endpoint = (f"https://api.cloudflare.com/client/v4/accounts/{settings.cloudflare_account_id}/"
                "ai/run/@cf/black-forest-labs/flux-1-schnell")
    # FLUX.1 schnell accepts only prompt and steps; the video renderer turns its
    # returned frame into a 1080x1920 scene without requesting unsupported dimensions.
    response = httpx.post(endpoint, headers={"Authorization": f"Bearer {settings.cloudflare_api_token}"},
                          json={"prompt": prompt, "steps": 4}, timeout=90)
    response.raise_for_status()
    payload = response.json()
    image = payload.get("result", {}).get("image")
    if not image:
        raise ProviderError("Cloudflare image response did not include image data.")
    import base64
    destination.write_bytes(base64.b64decode(image))
    return destination
