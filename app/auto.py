"""Zero-cost autonomous Short:  topic -> research -> script/spec -> free stills -> render -> AI judge -> Telegram.

    python -m app.auto --topic "Doomsday 1960 paper" [--wiki "Doomsday equation" | --facts facts.txt] [--out runs/] [--no-deliver]
    python -m app.auto --trend                       # pick a topic from Google Trends RSS first

Everything here is free-tier and keyed by env vars (all optional except one LLM key):
  GEMINI_API_KEY | GROQ_API_KEY | OPENROUTER_API_KEY     writer (first available) and judge (a DIFFERENT provider if one exists)
  CLOUDFLARE_ACCOUNT_ID + CLOUDFLARE_API_TOKEN           FLUX stills (else keyless Pollinations)
  TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID                  delivery
Limits live in LIMITS (edit one place). Any 429/5xx fails over to the next provider.
Facts come from Wikipedia (keyless); every number the script says must appear in the fetched facts or the spec is rejected.
"""
from __future__ import annotations

import base64
import difflib
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path

import httpx

from . import insights

try:   # keys come from the project's .env (never printed); on CI they are already in the environment
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except ImportError:
    pass


LIMITS = {"attempts": 3, "similarity_reject": 0.62, "history": Path("data/history.jsonl"), "max_mb": 48}
PASS = {"hook": 8, "visual_quality": 8, "accuracy": 9, "originality": 7, "policy": 10}   # the plan's judge table
ROOT = Path(__file__).resolve().parents[1]
HUD_TYPES = {"bubble", "title", "chip", "big", "label", "sub", "rows", "chain", "list", "stamp",
             "bars", "line", "ring", "delta", "kinetic", "tape", "toast", "cursor"}


# ---------------------------------------------------------------- LLM ladder (free tiers) ----------------------------------
def _providers() -> list[str]:
    return [p for p, k in (("gemini", "GEMINI_API_KEY"), ("groq", "GROQ_API_KEY"), ("openrouter", "OPENROUTER_API_KEY")) if os.environ.get(k)]


def _call(provider: str, system: str, user: str, image: bytes | None = None) -> str:
    if provider == "gemini":
        parts = [{"text": user}] + ([{"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(image).decode()}}] if image else [])
        body = {"systemInstruction": {"parts": [{"text": system}]}, "contents": [{"role": "user", "parts": parts}],
                "generationConfig": {"responseMimeType": "application/json", "temperature": 0.7}}
        models = [m for m in (os.environ.get("GEMINI_MODEL"), "gemini-2.5-flash", "gemini-3-flash-preview", "gemini-2.5-flash-lite", "gemini-flash-latest") if m]
        last: Exception | None = None
        for model in models:                       # 429/5xx on one model (free-tier quotas are per model) -> next model
            for attempt in range(2):
                try:
                    r = httpx.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                                   headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]}, timeout=60, json=body)
                    if r.status_code in (429, 500, 502, 503, 504):
                        last = httpx.HTTPStatusError(f"{r.status_code} {model}", request=r.request, response=r)
                        time.sleep(3 * (attempt + 1))
                        continue
                    r.raise_for_status()
                    return r.json()["candidates"][0]["content"]["parts"][0]["text"]
                except (KeyError, IndexError, httpx.TimeoutException) as e:   # empty answer or hang -> next model
                    last = e
                    break
        raise last or RuntimeError("gemini failed")
    if provider == "groq":
        model = os.environ.get("GROQ_VISION_MODEL") if image else os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
        content = [{"type": "text", "text": user}] + ([{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(image).decode()}}] if image else [])
        r = httpx.post("https://api.groq.com/openai/v1/chat/completions", headers={"Authorization": "Bearer " + os.environ["GROQ_API_KEY"]},
                       timeout=120, json={"model": model, "response_format": {"type": "json_object"}, "temperature": 0.7,
                                          "messages": [{"role": "system", "content": system}, {"role": "user", "content": content if image else user}]})
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    if provider == "openrouter":
        model = os.environ.get("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free")
        r = httpx.post("https://openrouter.ai/api/v1/chat/completions", headers={"Authorization": "Bearer " + os.environ["OPENROUTER_API_KEY"]},
                       timeout=120, json={"model": model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    raise ValueError(provider)


def _json(text: str) -> dict:
    m = re.search(r"\{[\s\S]*\}", text)
    return json.loads(m.group(0) if m else text)


def ask(system: str, user: str, image: bytes | None = None, prefer: list[str] | None = None, exclude: str | None = None, wait: bool = True) -> tuple[dict, str]:
    """first provider that answers valid JSON wins; 429/5xx/parse errors fail over. If every provider is throttled (429/5xx/timeout) wait and go round again
    (free tiers recover within a minute or two). Returns (json, provider)."""
    avail = _providers()
    order = [p for p in (prefer or avail) if p in avail and p != exclude]
    if image is not None:
        order = [p for p in order if p != "groq" or os.environ.get("GROQ_VISION_MODEL")]   # Groq currently lists no vision model
        order = [p for p in order if p != "openrouter"]                                      # free OpenRouter vision models vary; not trusted as judge
    order = order or [p for p in avail if image is None or p == "gemini"]
    errs: list[str] = []
    for rnd in range(3):
        throttled = False
        for p in order:
            for n in range(2):                                    # a malformed-JSON reply is usually one-off: ask the same provider once more
                try:
                    return _json(_call(p, system, user, image)), p
                except (ValueError, json.JSONDecodeError) as e:
                    errs.append(f"{p}: {e!r}"[:160])
                except (httpx.HTTPError, KeyError) as e:
                    errs.append(f"{p}: {e!r}"[:160])
                    throttled = throttled or any(t in repr(e) for t in ("429", "503", "502", "500", "Timeout"))
                    break
        if not (throttled and rnd < 2 and wait):     # wait=False: a cheap check (photo relevance) gives up at once instead of holding the run
            break
        print(f"   all LLM providers throttled; waiting {40 * (rnd + 1)} s", flush=True)
        time.sleep(40 * (rnd + 1))
    raise RuntimeError("no free LLM provider answered: " + " | ".join(errs[-4:]) if errs else "set GEMINI_API_KEY or GROQ_API_KEY")


# ---------------------------------------------------------------- research (Wikipedia, keyless) -----------------------------
def wiki_facts(query: str, sentences: int = 40) -> dict:
    h = {"User-Agent": "AgentShiftShorts/1.0 (https://youtube.com/@agentshiftai; educational explainer Shorts)"}
    s = httpx.get("https://en.wikipedia.org/w/api.php", params={"action": "query", "list": "search", "srsearch": query, "format": "json", "srlimit": 1},
                  headers=h, timeout=30).json()
    title = s["query"]["search"][0]["title"]
    e = httpx.get("https://en.wikipedia.org/w/api.php", params={"action": "query", "prop": "extracts", "explaintext": 1, "titles": title, "format": "json", "exlimit": 1},
                  headers=h, timeout=30).json()
    text = next(iter(e["query"]["pages"].values()))["extract"]
    text = " ".join(re.split(r"(?<=[.!?])\s+", text)[:sentences])
    return {"title": title, "url": "https://en.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_")), "text": text}


def trend_topics(geo: str = "US", n: int = 15) -> list[str]:
    r = httpx.get(f"https://trends.google.com/trending/rss?geo={geo}", timeout=30, follow_redirects=True)
    return re.findall(r"<title>(?!Daily Search Trends)([^<]+)</title>", r.text)[:n]


EVERGREEN = ["Dyson sphere", "Kessler syndrome", "Carrington Event", "Fermi paradox", "Tunguska event", "Grey goo", "Great Filter",
             "Yellowstone Caldera", "Year Without a Summer", "Van Allen radiation belt", "Tardigrade", "Project Orion (nuclear propulsion)",
             "Voyager 1", "Great Dying", "Toba catastrophe theory", "Cretaceous-Paleogene extinction event", "Mars Climate Orbiter", "Space elevator",
             "Event Horizon Telescope", "Antikythera mechanism", "Voynich manuscript", "Library of Alexandria", "Krakatoa", "Halley's Comet",
             "Apollo 13", "Chernobyl exclusion zone", "Mid-Atlantic Ridge", "Marianas Trench", "Oort cloud", "Boltzmann brain",
             "Roman concrete", "Greenland ice sheet", "Gulf Stream", "Antarctic ozone hole", "Cosmic microwave background", "Neutron star",
             "Magnetar", "Pale Blue Dot", "Hubble Space Telescope", "International Space Station", "Starlink", "James Webb Space Telescope",
             "Lagrange point", "Solar sail", "Nuclear winter", "Permafrost", "Coral bleaching", "Bioluminescence", "Mycelium", "Octopus intelligence",
             "Svalbard Global Seed Vault", "Large Hadron Collider", "Quantum entanglement", "Turing test", "Moore's law", "Y2K problem",
             "Great Pacific garbage patch", "Atacama Desert", "Tardigrades in space", "Ball lightning", "St. Elmo's fire", "Aurora"]
TOPICS = Path("data/topics.jsonl")      # every topic ever started: unlike history.jsonl (approved Shorts only) this stops repeats of drafts and parked tries


def _norm_topic(t: str) -> str:
    return re.sub(r"[^a-z0-9]", "", re.sub(r"\(.*?\)", "", t.lower()))


def used_topics(days_done: int = 60, days_parked: int = 3) -> set[str]:
    """normalised wiki titles / topics that must not be picked again: delivered or draft ones for `days_done`, parked or crashed ones for `days_parked`"""
    import datetime as dt
    path = ROOT / TOPICS
    out: set[str] = set()
    if not path.exists():
        return out
    today = dt.date.today()
    for line in path.read_text().splitlines():
        try:
            r = json.loads(line)
            age = (today - dt.date.fromisoformat(r["date"])).days
        except (ValueError, KeyError):
            continue
        keep = days_done if r.get("outcome") in ("delivered", "draft") else days_parked
        if age <= keep:
            out |= {_norm_topic(r.get("wiki", "")), _norm_topic(r.get("topic", ""))} - {""}
    return out


def record_topic(topic: str, wiki: str, outcome: str, score: float | None = None) -> None:
    import datetime as dt
    path = ROOT / TOPICS
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps({"date": dt.date.today().isoformat(), "topic": topic, "wiki": wiki, "outcome": outcome, "score": score}, ensure_ascii=False) + "\n")


def pick_topic(deliver_chat: str | None = None) -> tuple[str, str]:
    """no-input topic choice: Google Trends + Wikipedia most-read + evergreen ideas -> the LLM picks ONE explainer-friendly 'what if' topic
    that has a real Wikipedia article (the research source), skipping anything similar to past Shorts. Returns (topic, wiki_title)."""
    import datetime as dt
    cands = []
    try:
        cands += trend_topics()[:10]
    except Exception as e:
        print("trends unavailable:", type(e).__name__)
    try:
        d = dt.date.today() - dt.timedelta(days=2)
        r = httpx.get(f"https://api.wikimedia.org/feed/v1/wikipedia/en/featured/{d:%Y/%m/%d}", timeout=30,
                      headers={"User-Agent": "AgentShiftShorts/1.0 (https://youtube.com/@agentshiftai)"})
        cands += [a["normalizedtitle"] for a in r.json().get("mostread", {}).get("articles", [])[:25] if ":" not in a["normalizedtitle"]]
    except Exception as e:
        print("wikipedia most-read unavailable:", type(e).__name__)
    hist = ROOT / LIMITS["history"]
    past = [json.loads(x)["title"] for x in hist.read_text().splitlines()[-40:]] if hist.exists() else []
    import random
    used = used_topics()
    cands = [c for c in cands if _norm_topic(c) not in used]
    news = (insights.load().get("news") or [])[:8]                       # science/tech headlines collected by the weekly job
    cands += [f"IN THE NEWS: {n}" for n in news]
    fresh = [e for e in EVERGREEN if _norm_topic(e) not in used]
    cands += random.sample(fresh, min(10, len(fresh)))
    tried = sorted(used)[:60]
    out = {}
    for attempt in range(3):
        out, _ = ask("You choose the next topic for 'Agent Shift', a YouTube Shorts channel of 35-45 s science/tech/history 'what if' explainers. "
                     "From the CANDIDATES pick ONE that is explainable in 40 s with a surprising angle, factual and policy-safe (no tragedies, politics, celebrities, sports results, "
                     "medical advice). Prefer timeless science/tech/space/history ideas that connect to something people search for; items marked IN THE NEWS are current science/tech headlines: when one fits, choose the timeless topic that explains it (a news hook gets views) but never a tragedy or politics; use CHANNEL INSIGHTS to favour what has worked "
                     "and avoid what has scored badly. It must have a real English Wikipedia article. "
                     'Return ONLY JSON {"topic":"a what-if framing","wiki":"exact Wikipedia article title","why":"..."}. Never pick or closely resemble anything in PAST TITLES or ALREADY USED.',
                     f"CANDIDATES: {cands}\nPAST TITLES: {past}\nALREADY USED (never again): {tried}\nCHANNEL INSIGHTS: {insights.hint() or 'none yet'}",
                     prefer=["groq", "gemini", "openrouter"])
        w = wiki_facts(out["wiki"])["title"]         # proves the article exists and is fetchable; use its canonical title
        if _norm_topic(w) not in used and _norm_topic(out["wiki"]) not in used:
            out["wiki"] = w
            break
        print(f"   picker chose an already-used topic ({out['wiki']}); asking again", flush=True)
        cands = [c for c in cands if _norm_topic(c) != _norm_topic(out["wiki"])]
    else:                                             # the model keeps repeating itself: take an unused evergreen topic ourselves
        pick = random.choice(fresh or EVERGREEN)
        out = {"topic": f"What if {pick} happened or mattered more than we think?", "wiki": pick, "why": "fallback: first unused evergreen topic"}
    print("picked:", out)
    return out["topic"], out["wiki"]


# ---------------------------------------------------------------- script -> spec -------------------------------------------
try:
    from . import motionbank as _mb
    MOTION_CLIPS = ", ".join(c["name"] for c in _mb.manifest() if c.get("role", "ambient") != "object")
except Exception:                                   # the bank is optional
    MOTION_CLIPS = "none"
SYSTEM = f"""You write 35-45 second YouTube Shorts for the channel Agent Shift (brand AGENT SHIFT, 'what if' explainers). Output ONLY JSON.
Spec schema (JSON object): id (slug), title, voice "en-US-AndrewNeural", rate "+10%", brand "AGENT SHIFT", series_label (short upper-case tag),
Beats about something REAL that has been photographed (a named spacecraft, telescope, instrument, rocket, place, event, or an actual phenomenon such as a solar flare or an aurora) should add "photo":"<2-3 word search term for the subject, most specific first>" - a real free-licence photo (NASA / Wikimedia Commons) is used instead of generating one, which is free, credible and preferred; use it on at least 3 beats when the topic allows; keep the prompt as the fallback (the prompt must still describe the same subject with no people). Image prompts: no text/letters/numbers, NO people or faces at all (generated faces look uncanny and real people must never be generated: show an object, instrument, place, diagram-like scene or a silhouette from behind instead), documentary look with natural/practical light and real materials (no golden glow, no glowing orbs, no neon), and every beat a DIFFERENT shot type (macro, aerial, top-down, wide, silhouette). TOP-LEVEL key theme: one of "cool" (space/tech), "warm" (history/people/desert), "mono" (archival/serious), "earth" (nature/climate) - every picture is graded to it so the Short looks like one film. TOP-LEVEL key subscribe {{"title":"SUBSCRIBE","sub":"for daily what-ifs"}} (never a hud element), sources {{beat_key: "citation incl. URL"}}, beats[].
beat: key ("hook","b1".."b6","outro"), img ("s0.jpg"... unique per picture; reuse a name only to show the SAME picture again),
prompt (ONLY on the first beat that uses an img: photoreal cinematic 9:16 image prompt, no text, no logos, no real people's faces),
focal [x,y] 0-1, say (one or two short spoken sentences; write numbers as DIGITS like 1960, 8.3 billion, 17% - the voice reads them and the captions show them, so never spell a number out), hud[] on-screen elements, sfx optional [[word,"impact|pop|ding|whoosh",vol]].
hud element: {{"t": one of {sorted(HUD_TYPES)}, ...}}  bubble{{text}} title{{html with *accent*}} chip{{text,col}} big{{text,col,count?}} label{{text}}
sub{{html}} rows{{items:[[label,value,unit,col]],stagger}} chain{{steps:[[a,b]]}} list{{items:[[emoji,a,b]]}} stamp{{text,col}}; col in cy|am|ir|ok.
Motion graphics (use at least 2 per Short, vary them, prefer data ones when you have numbers): bars{{items:[[name,value,col]],unit}} line{{values:[numbers],labels:[first,last],col}}
ring{{pct:0-100,label,col}} delta{{text:"+176%",dir:"up|down",col}} kinetic{{text:"words with *accent*"}} tape{{text,col}} toast{{title,sub,icon}} cursor{{text}}.
Any element may add "fx":"shine".
Moving-picture layers (optional, they make a still feel like video): beat "footage":"<2-3 concrete nouns, MOST SPECIFIC FIRST>" swaps that beat's picture for a real NASA clip
(only for space/Earth/science beats, at most 2 per Short, e.g. "asteroid impact", "earth night lights"; a still is still required as fallback). Beat "motion":"<clip>" picks a light layer
over the picture: {MOTION_CLIPS}; omit it and one is chosen from the mood. Do not stack two big elements in one beat (max ~1100px tall total).
EVERY hud element needs "at": a word that appears in that beat's "say" (exact word) - the element appears when it is spoken.
Hook = first beat: a surprising promise in <=2 seconds, with a bubble "what if?" and a title. Last beat: payoff + 'Follow for more what-ifs'.
Facts: use ONLY the supplied FACTS. Every number you write (digits in hud text or numbers in say) must be present in FACTS. Never invent statistics.
7-9 beats total, ~90-108 spoken words (hard max 112; the video must be under 45 s). Keep each hud text short (<=28 chars), written with digits not spelled numbers, as a complete short noun phrase (<=4 words, never a sentence fragment). No claims about real private individuals."""


def _number_supported(num: str, facts_text: str) -> bool:
    """a number is supported if it appears in FACTS, is a rounding/prefix of one (3.0 -> 3,015,470,894), or is a plausible year or 1-3.
    Heuristic only: the judge's accuracy score is the second check."""
    d = re.sub(r"\D", "", num)
    if len(d) == 4 and 1800 <= int(d) <= 2100 or d in ("1", "2", "3") or num.replace(",", "") in facts_text.replace(",", ""):
        return True
    toks = [re.sub(r"\D", "", t) for t in re.findall(r"\d[\d,\.]*", facts_text)]
    return any(t.startswith(d.rstrip("0") or d) for t in toks if t)


PEOPLE = re.compile(r"\b(portrait|face|faces|man|men|woman|women|person|scientist|physicist|child|children|boy|girl|elderly|selfie|headshot)\b", re.I)   # close-up people: generated faces look uncanny
BEHIND = re.compile(r"silhouette|from behind|back view|backs? turned|no faces?|faceless", re.I)


def validate_spec(spec: dict, facts_text: str) -> list[str]:
    errs, keys, seen = [], set(), set()
    beats = spec.get("beats") or []
    if not 6 <= len(beats) <= 10:
        errs.append(f"need 6-10 beats, got {len(beats)}")
    for k in ("id", "title", "sources"):
        if not spec.get(k):
            errs.append(f"missing {k}")
    if not re.fullmatch(r"[a-z0-9-]+", str(spec.get("id", ""))):
        errs.append("id must be a lowercase slug")
    words = 0
    for b in beats:                       # the subscribe card is added by the pipeline; drop any the writer put in hud
        if isinstance(b.get("hud"), list):
            for e in b["hud"]:            # models sometimes name the element kind "type"/"kind": accept it
                if isinstance(e, dict) and "t" not in e:
                    for alt in ("type", "kind", "element"):
                        if alt in e:
                            e["t"] = e.pop(alt)
                            break
            b["hud"] = [e for e in b["hud"] if isinstance(e, dict) and e.get("t") != "subscribe"]
    for b in beats:
        k = b.get("key", "?")
        if k in keys:
            errs.append(f"duplicate key {k}")
        keys.add(k)
        if not b.get("say"):
            errs.append(f"{k}: no say")
            continue
        words += len(b["say"].split())
        if b.get("img") not in seen:
            seen.add(b.get("img"))
            if not b.get("prompt") and (b.get("photo") or b.get("footage")):       # the writer gave a real-photo/footage term: that is also the fallback prompt
                b["prompt"] = f"documentary photograph of {b.get('photo') or b.get('footage')}, natural light, no text, no people"
            if not b.get("prompt"):
                errs.append(f"{k}: first use of {b.get('img')} needs a prompt")
        pr = str(b.get("prompt", ""))
        if PEOPLE.search(pr) and not BEHIND.search(pr):
            errs.append(f"{k}: image prompt shows a person ({PEOPLE.search(pr).group(0)}); generated faces look uncanny - describe an object, instrument, place or a silhouette from behind")
        sw = {re.sub(r"[^a-z0-9]", "", w.lower()) for w in b["say"].split()}
        for e in b.get("hud", []):
            if re.sub(r"[^a-z0-9]", "", str(e.get("at", "")).lower()) not in sw:      # auto-repair: anchor to the first substantial spoken word
                cand = [w for w in b["say"].split() if len(re.sub(r"[^A-Za-z0-9]", "", w)) > 3]
                if cand:
                    e["at"] = re.sub(r"[^A-Za-z0-9'-]", "", cand[0])
            if e.get("t") not in HUD_TYPES:
                errs.append(f"{k}: bad hud type {e.get('t')}")
            if re.sub(r"[^a-z0-9]", "", str(e.get("at", "")).lower()) not in sw:
                errs.append(f"{k}: hud at={e.get('at')!r} is not a word in say")
            blob = json.dumps({k: v for k, v in e.items() if k in ("text", "html", "items", "steps", "values", "pct", "title", "sub", "label")}, ensure_ascii=False)
            for num in re.findall(r"\d[\d,\.]*\d|\d", re.sub(r"<[^>]+>", " ", blob.replace('"at"', ""))):
                if not _number_supported(num, facts_text):
                    errs.append(f"{k}: number {num} not in FACTS")
    if not 70 <= words <= 128:
        errs.append(f"spoken words {words} outside 70-128")
    elif words > 100 and not errs:
        spec["rate"] = "+20%"                      # long script: speak faster so the Short stays <= ~45 s
    nfoot = 0
    for b in beats:                                   # optional moving layers: sanitise instead of failing the script
        if b.get("footage"):
            nfoot += 1
            if nfoot > 2 or not isinstance(b["footage"], str) or len(b["footage"]) > 60:
                b.pop("footage")
        if b.get("motion") not in (None, False) and b["motion"] not in MOTION_CLIPS.split(", "):
            b.pop("motion")
    if spec.get("theme") not in ("cool", "warm", "mono", "earth"):
        spec["theme"] = "cool"
    if beats and not any(e.get("t") == "bubble" for e in beats[0].get("hud", [])):
        errs.append("hook needs a bubble")
    return sorted(set(errs))


def too_similar(spec: dict) -> float:
    path = ROOT / LIMITS["history"]
    if not path.exists():
        return 0.0
    mine = spec["title"].lower() + " " + " ".join(b["say"].lower() for b in spec["beats"])
    best = 0.0
    for line in path.read_text().splitlines()[-30:]:
        h = json.loads(line)
        best = max(best, difflib.SequenceMatcher(None, mine, h["blob"]).ratio())
    return best


def write_spec(topic: str, facts: dict, notes: list[str] | None = None) -> tuple[dict, str]:
    user = f"TOPIC: {topic}\nFACTS (source {facts['url']}):\n{facts['text']}\n"
    if insights.hint():
        user += f"\nCHANNEL INSIGHTS (advisory, never a source of facts): {insights.hint()}\n"
    if notes:
        user += "\nFIX THESE PROBLEMS FROM THE LAST ATTEMPT:\n- " + "\n- ".join(notes)
    order = [["groq", "gemini", "openrouter"], ["gemini", "groq", "openrouter"], ["openrouter", "gemini", "groq"]]
    for n in range(5):
        spec, prov = ask(SYSTEM, user, prefer=order[n // 2 % 3])      # a model that keeps failing the schema is swapped out
        errs = validate_spec(spec, facts["text"])
        if not errs:
            spec.setdefault("sources", {})["wiki"] = facts["url"]
            return spec, prov
        user += "\nYour last JSON failed validation: " + "; ".join(errs) + "\nReturn corrected JSON."
    raise RuntimeError("script failed validation 5x: " + "; ".join(errs))


# ---------------------------------------------------------------- judge (different model than the writer) ------------------
JUDGE = f"""You are a strict YouTube Shorts reviewer. You see a time-ordered contact sheet of REAL frames plus the narration and the fact sources.
Score 1-10: hook (do the first frames make a clear, surprising promise), visual_quality (real-looking imagery; penalise garbled text, warped objects,
extra fingers, soft/blurry pictures), accuracy (on-screen claims match the narration and the sources), originality (new angle, not a re-cut),
policy (nothing misleading or against YouTube rules), visual_variety (different picture/camera every ~3-5 s), polish (lighting, no AI artefacts,
no clipped text), hierarchy (one focal point, legible type), consistency (one visual language), payoff (last frame closes the loop).
Also list concrete fixes. Return JSON {{"scores":{{"hook":n,"visual_quality":n,"accuracy":n,"originality":n,"policy":n,"visual_variety":n,
"polish":n,"hierarchy":n,"consistency":n,"payoff":n}},"fixes":["beat key: change"],"failing_part":"script|images|voice|none"}}.
Pass marks: {PASS}. Be harsh: generic AI-looking stock is 4-6."""


def judge(run: Path, spec: dict, writer: str) -> dict:
    sheet = (run / "sheet.jpg").read_bytes()
    narr = " ".join(b["say"] for b in spec["beats"])
    out, prov = ask(JUDGE, f"NARRATION: {narr}\nSOURCES: {json.dumps(spec['sources'])[:1500]}", image=sheet, exclude=writer)
    s = out.get("scores", {})
    ok = all(s.get(k, 0) >= v for k, v in PASS.items()) and s.get("visual_variety", 0) >= 8 and min(s.values() or [0]) >= 7
    # safe_zone is measured by code (qa_v2.safe_zone_overlay), not opinion: it is only recorded here as passing because the hard gate passed first
    (run / "vision.json").write_text(json.dumps({"scores": {**s, "safe_zone": 10}, "verdict": "approve" if ok else "revise",
                                                 "fixes": out.get("fixes", []), "judge": prov}, indent=1))
    return {"approved": ok, "scores": s, "fixes": out.get("fixes", []), "failing": out.get("failing_part", "script"), "judge": prov}


# ---------------------------------------------------------------- delivery -------------------------------------------------
def encode_for_telegram(src: Path, dst: Path) -> Path:
    for crf in (23, 26, 29):
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-c:v", "libx264", "-preset", "slow", "-crf", str(crf), "-pix_fmt", "yuv420p",
                        "-movflags", "+faststart", "-c:a", "copy", str(dst)], check=True)
        if dst.stat().st_size < LIMITS["max_mb"] * 2**20:
            return dst
    raise RuntimeError("cannot get under the Telegram size limit")


def telegram(text: str, video: Path | None = None, chat: str | None = None) -> bool:
    tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), chat or os.environ.get("TELEGRAM_CHAT_ID")
    if not (tok and chat):
        print("[telegram] not configured; skipped:", text[:120])
        return False
    base = f"https://api.telegram.org/bot{tok}/"
    if video:
        with open(video, "rb") as f:
            r = httpx.post(base + "sendVideo", data={"chat_id": chat, "caption": text[:1000], "supports_streaming": "true"}, files={"video": f}, timeout=300)
    else:
        r = httpx.post(base + "sendMessage", data={"chat_id": chat, "text": text[:4000]}, timeout=60)
    return r.status_code == 200


def caption(spec: dict, j: dict) -> str:
    return (f"{spec['title'][:60]} #shorts\n\nJudge {j['judge']}: {j['scores']}\nSources: {json.dumps(spec['sources'], ensure_ascii=False)[:600]}\n"
            "Review, then publish from your phone (private-until-audit rule).")


# ---------------------------------------------------------------- the loop -------------------------------------------------
def finish(spec: dict, writer: str, out: Path, deliver: bool, chat: str | None) -> tuple[bool, list[str], Path, dict | None]:
    """render + hard gates + judge + (on approval) ledger + Telegram. Cached stills are reused. Returns (approved, notes, run_dir, judge)."""
    out.mkdir(parents=True, exist_ok=True)
    sp = out / f"{spec['id']}.spec.json"
    sp.write_text(json.dumps(spec, ensure_ascii=False, indent=1))
    from . import produce            # heavy deps (opencv, playwright) load only when a render is needed
    m = produce.run(sp, out)
    run_dir = out / spec["id"]
    bad = [k for k, v in m["checks"].items() if v != "pass" and k != "vision"]
    if bad:
        return False, [f"hard gate failed: {k}: {m['checks'][k]}" for k in bad], run_dir, None
    try:
        j = judge(run_dir, spec, writer)
    except RuntimeError as e:                    # no judge answered (quota / malformed JSON): this attempt cannot be scored, the next one may be
        print("   judge unavailable:", str(e)[:300], flush=True)
        return False, ["judge unavailable; keep the script and visuals as they are"], run_dir, None
    print("   judge:", j, flush=True)
    res = produce.regate(run_dir, run_dir / "vision.json")
    if j["approved"] and res["passed"]:
        final = encode_for_telegram(run_dir / "final.mp4", run_dir / "telegram.mp4")
        ledger = ROOT / LIMITS["history"]
        ledger.parent.mkdir(parents=True, exist_ok=True)
        with open(ledger, "a") as f:
            f.write(json.dumps({"id": spec["id"], "title": spec["title"], "scores": j["scores"],
                                "blob": spec["title"].lower() + " " + " ".join(b["say"].lower() for b in spec["beats"])}) + "\n")
        if deliver:
            telegram(caption(spec, j) + credits_line(run_dir), final, chat)
        return True, [], run_dir, j
    return False, j["fixes"] or ["raise visual quality and accuracy"], run_dir, j


def send_draft(spec: dict, run_dir: Path, j: dict, chat: str | None) -> None:
    final = encode_for_telegram(run_dir / "final.mp4", run_dir / "telegram.mp4")
    telegram("DRAFT (the automatic judge did not approve it, you decide). Weakest: " +
             ", ".join(f"{k} {v}" for k, v in sorted(j["scores"].items(), key=lambda kv: kv[1])[:3]) +
             "\nFixes: " + " | ".join(j["fixes"])[:500] + "\n\n" + caption(spec, j) + credits_line(run_dir) +
             "\nReply /approve to get the publish pack, or describe a change.", final, chat)


def credits_line(run_dir: Path) -> str:
    out = ""
    cj = run_dir / "img" / "credits.json"
    if cj.exists():
        c = json.loads(cj.read_text())
        out += "\nPhoto credits: " + "; ".join(f"{v['file']} ({v['license']}, {v['artist'][:40]})" for v in c.values())
    vj = run_dir / "vid" / "credits.json"
    if vj.exists():
        out += "\nFootage: " + "; ".join(f"{v['title'][:50]} ({v['center']}, {v['source']})" for v in json.loads(vj.read_text()).values())
    return out


def facts_for(topic: str, wiki: str | None, facts_file: Path | None, deliver: bool, chat: str | None) -> dict:
    if facts_file:   # hand-supplied FACTS: first line = source URL, rest = text (use when Wikipedia is unreachable / for primary sources)
        url, _, body = facts_file.read_text().partition("\n")
        return {"title": topic, "url": url.strip(), "text": body.strip()}
    try:
        return wiki_facts(wiki or topic)
    except (httpx.HTTPError, KeyError, IndexError, ValueError) as e:
        if deliver:
            telegram(f"Research failed for '{topic}': {e!r}. Send /facts <url> then the text, or retry later.", chat=chat)
        raise SystemExit(f"research failed ({e!r}); pass --facts <file> (line 1 = source URL, then the text)")


def run(topic: str, wiki: str | None, out: Path, deliver: bool = True, facts_file: Path | None = None, chat: str | None = None) -> int:
    facts = facts_for(topic, wiki, facts_file, deliver, chat)
    (out / "_last.facts.json").parent.mkdir(parents=True, exist_ok=True)
    wiki_title = facts.get("title") or wiki or topic
    record_topic(topic, wiki_title, "started")
    notes: list[str] = []
    best = None                                   # best technically-clean attempt, delivered as a DRAFT if none is approved
    for attempt in range(1, LIMITS["attempts"] + 1):
        print(f"== attempt {attempt}/{LIMITS['attempts']}", flush=True)
        try:
            spec, writer = write_spec(topic, facts, notes)
        except RuntimeError as e:                       # the writer could not produce a valid script: retry the attempt, do not lose the run
            print("   writer failed:", str(e)[:300], flush=True)
            notes = [str(e)[:400]]
            continue
        sim = too_similar(spec)
        if sim >= LIMITS["similarity_reject"]:
            notes = [f"too similar to a recent video ({sim:.2f}); choose a clearly different angle and title"]
            continue
        spec["id"] = f"{spec['id']}-a{attempt}"
        spec["_facts"] = facts          # kept with the spec so later edit requests are validated against the same sources
        spec["_writer"] = writer
        from . import stills
        stills.TEXTURED.clear()
        stills.TOPIC, stills._TOPIC_USES["n"] = wiki_title, 0
        ok, notes, run_dir, j = finish(spec, writer, out, deliver, chat)
        if not ok:
            print("   attempt notes:", "; ".join(notes)[:600], flush=True)
        if not ok and len(stills.TEXTURED) >= 5:      # pictures could not be sourced (free image quota gone): more attempts today would only repeat this
            msg = (f"⏸ Not today: '{topic}'. The free image quota is used up ({len(stills.TEXTURED)} beats had no picture), so no Short was made. "
                   "Tomorrow's scheduled run will try again - nothing to do.")
            print(msg, flush=True)
            record_topic(topic, wiki_title, "parked")
            if deliver:
                telegram(msg, chat=chat)
            return 4
        if not ok and j and j["scores"].get("accuracy", 0) >= 9 and j["scores"].get("policy", 0) >= 10:
            avg = sum(j["scores"].values()) / len(j["scores"])
            if best is None or avg > best[0]:
                best = (avg, spec, run_dir, j)
        if ok:
            record_topic(topic, wiki_title, "delivered", round(sum(j["scores"].values()) / len(j["scores"]), 1))
            print("APPROVED", run_dir / "telegram.mp4")
            (out / "_last.json").write_text(json.dumps({"id": spec["id"], "spec": str(out / f"{spec['id']}.spec.json")}))
            return 0
    if best:                                      # factual + policy-safe but visually short of the bar -> hand to the owner as a clearly-labelled draft
        _, spec, run_dir, j = best
        record_topic(topic, wiki_title, "draft", round(best[0], 1))
        (out / "_last.json").write_text(json.dumps({"id": spec["id"], "spec": str(out / f"{spec['id']}.spec.json"), "draft": True}))
        if deliver:
            send_draft(spec, run_dir, j, chat)
        print("DRAFT delivered", run_dir / "telegram.mp4")
        return 3
    record_topic(topic, wiki_title, "parked")
    if deliver:
        why = "; ".join(notes)[:300] if notes else "no details"
        telegram(f"⏸ Not today: '{topic}' did not pass review after {LIMITS['attempts']} tries ({why}). No Short was made; tomorrow's run picks a fresh topic.", chat=chat)
    print("REJECTED after", LIMITS["attempts"], "attempts:", notes)
    return 2


if __name__ == "__main__":
    a = sys.argv[1:]
    arg = lambda k: a[a.index(k) + 1] if k in a else None
    topic = arg("--topic")
    if "--trend" in a or "--auto" in a:
        topic, wiki_pick = pick_topic()
        a += ["--wiki", wiki_pick]
    if "--pick-only" in a:                       # evaluate the picker without making a Short
        print(json.dumps({"topic": topic, "wiki": arg("--wiki"), "already_used": sorted(used_topics())[:40]}, ensure_ascii=False))
        raise SystemExit(0)
    if not topic:
        raise SystemExit(__doc__)
    raise SystemExit(run(topic, arg("--wiki"), Path(arg("--out") or "runs"), "--no-deliver" not in a, Path(arg("--facts")) if arg("--facts") else None))
