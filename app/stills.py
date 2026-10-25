"""Still-image providers for the shot list.

  folder    images already in <run>/img (e.g. generated with Higgsfield `gpt_image_2_5`, 0.25 credit each)
  free      (default) Cloudflare FLUX if CLOUDFLARE_* keys are set, else Pollinations (keyless). STILLS=folder disables generation.
              Smoke test:  python -m app.stills gen "test prompt" out.jpg

Quality contract: every image must be looked at before use (skills/shorts-visual-direction). Missing images raise with the
exact prompts to generate, so a run can never silently fall back to flat graphics.
"""
from __future__ import annotations

import base64
import json
import os
import re
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except ImportError:
    pass


def _fit(raw: bytes, dest: Path, crop_bottom: float = 0.0) -> Path:
    """decode -> crop (watermark strip) -> cover-fit to 1080x1920 (Lanczos) -> mild unsharp -> JPEG q92."""
    import io

    from PIL import Image, ImageFilter
    im = Image.open(io.BytesIO(raw)).convert("RGB")
    if crop_bottom:
        im = im.crop((0, 0, im.width, int(im.height * (1 - crop_bottom))))
    k = max(1080 / im.width, 1920 / im.height)
    im = im.resize((round(im.width * k), round(im.height * k)), Image.LANCZOS)
    l, t = (im.width - 1080) // 2, (im.height - 1920) // 2
    im = im.crop((l, t, l + 1080, t + 1920)).filter(ImageFilter.UnsharpMask(radius=1.4, percent=60, threshold=3))
    im.save(dest.with_suffix(".jpg"), quality=92)
    return dest.with_suffix(".jpg")


def flux(prompt: str, dest: Path, width: int = 576, height: int = 1024) -> Path:
    """Cloudflare Workers AI. FLUX.2 klein supports true 9:16 (verified 768x1344); FLUX.1 schnell only returns 1024x1024, so it is the
    fallback and gets cover-cropped. Needs CLOUDFLARE_ACCOUNT_ID + CLOUDFLARE_API_TOKEN."""
    import httpx
    acct, tok = os.environ["CLOUDFLARE_ACCOUNT_ID"], os.environ["CLOUDFLARE_API_TOKEN"]
    base = f"https://api.cloudflare.com/client/v4/accounts/{acct}/ai/run/@cf/black-forest-labs/"
    h = {"Authorization": f"Bearer {tok}"}
    last = None
    for model in ("flux-2-klein-4b", "flux-2-klein-9b"):
        r = httpx.post(base + model, headers=h, timeout=120,
                       files={"prompt": (None, prompt), "width": (None, str(width)), "height": (None, str(height))})
        if r.status_code == 200:
            return _fit(base64.b64decode(r.json()["result"]["image"]), dest)
        last = f"{r.status_code} {r.text[:160]}"
    r = httpx.post(base + "flux-1-schnell", headers=h, json={"prompt": prompt, "steps": 8}, timeout=120)   # square -> cropped
    if r.status_code == 200:
        return _fit(base64.b64decode(r.json()["result"]["image"]), dest)
    raise RuntimeError(f"cloudflare image models failed (klein {last}, schnell {r.status_code} {r.text[:160]})")


def pollinations(prompt: str, dest: Path, seed: int = 7, tries: int = 4) -> Path:
    """Keyless free fallback. Output is ~580x1015 with a watermark strip on the bottom ~3%: cropped, then upscaled. Softer than FLUX."""
    import time
    import urllib.parse

    import httpx
    url = f"https://image.pollinations.ai/prompt/{urllib.parse.quote(prompt)}?width=768&height=1344&model=flux&nologo=true&seed={seed}"
    last = None
    for a in range(tries):
        try:
            r = httpx.get(url, timeout=120, follow_redirects=True)
            if r.status_code == 200 and r.headers.get("content-type", "").startswith("image"):
                return _fit(r.content, dest, crop_bottom=0.045)
            last = f"HTTP {r.status_code}"
            if r.status_code in (401, 402, 403):      # payment / auth wall: retrying only wastes a minute per picture
                break
        except httpx.HTTPError as e:  # network / timeout -> retry
            last = repr(e)
        time.sleep(4 * (a + 1))
    raise RuntimeError(f"pollinations failed: {last}")


STYLE = {"prompt", "photoreal", "photorealistic", "cinematic", "image", "shot", "view", "dramatic", "lighting", "light", "ultra", "detailed", "highly", "background",
         "style", "realistic", "closeup", "close-up", "wide", "angle", "aerial", "macro", "top-down", "silhouette", "soft", "natural", "documentary", "with", "from",
         "against", "above", "over", "into", "that", "this", "their", "while", "scene", "composition", "depth", "field", "bokeh", "sharp", "focus"}


def _layout(im):
    """9:16 picture from any photo: a full-bleed crop whose window is centred on the picture's bright mass (galaxies, rockets, lit subjects stay in frame).
    Strips over a blurred copy looked amateur, so even wide panoramas are cropped rather than letterboxed."""
    import numpy as np
    from PIL import Image, ImageEnhance, ImageFilter
    W, H = 1080, 1920
    if True:
        sc = max(W / im.width, H / im.height)
        big = im.resize((int(im.width * sc) + 1, int(im.height * sc) + 1), Image.LANCZOS)
        lum = np.asarray(big.convert("L").resize((big.width // 8 or 1, 1), Image.BOX), np.float32)[0]   # column brightness profile
        lum = np.convolve(lum, np.ones(15) / 15, mode="same") ** 2
        cx = float((lum * np.arange(len(lum))).sum() / max(lum.sum(), 1e-6)) * 8 if lum.sum() > 0 else big.width / 2
        left = int(min(max(cx - W / 2, 0), big.width - W))
        top = (big.height - H) // 2
        return big.crop((left, top, left + W, top + H))
    sc = max(W / im.width, H / im.height)
    bg = im.resize((int(im.width * sc) + 1, int(im.height * sc) + 1), Image.LANCZOS).filter(ImageFilter.GaussianBlur(40))
    bg = ImageEnhance.Brightness(bg.crop(((bg.width - W) // 2, (bg.height - H) // 2, (bg.width - W) // 2 + W, (bg.height - H) // 2 + H))).enhance(0.7)
    fg = im.resize((W, int(im.height * W / im.width)), Image.LANCZOS)
    bg.paste(fg, (0, 760 - fg.height // 2))
    return bg


def _blur_fit(raw: bytes, dest: Path) -> Path:
    """downloaded photo -> 1080x1920 JPEG via _layout"""
    import io

    from PIL import Image
    out = _layout(Image.open(io.BytesIO(raw)).convert("RGB"))
    out.save(dest.with_suffix(".jpg"), quality=92)
    return dest.with_suffix(".jpg")


def texture_still(prompt: str, dest: Path, seed: int = 7) -> Path:
    """last resort when every picture source is out of quota: a darkened, blurred frame of a motion-bank clip, so the run still completes.
    It is deliberately plain; the judge will mark the Short down for it and the owner sees that in the DRAFT notes."""
    import cv2

    from . import motionbank
    bank = [c for c in motionbank.manifest() if c.get("role") != "object"]
    c = bank[(sum(map(ord, prompt)) + seed) % len(bank)]
    cap = cv2.VideoCapture(str(motionbank.BANK / c["file"]))
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(cap.get(cv2.CAP_PROP_FRAME_COUNT) * 0.5))
    ok, f = cap.read()
    cap.release()
    if not ok:
        raise RuntimeError("motion bank unreadable")
    f = cv2.resize(f, (1080, 1920), interpolation=cv2.INTER_CUBIC)
    f = cv2.GaussianBlur(f, (0, 0), 5)
    out = dest.with_suffix(".jpg")
    cv2.imwrite(str(out), cv2.convertScaleAbs(f, alpha=0.8, beta=-10), [cv2.IMWRITE_JPEG_QUALITY, 90])
    return out


def has_face(img) -> bool:
    """offline (no quota): a frontal face covering >= 1.2% of the picture means an identifiable person - never used (real likenesses are off limits)"""
    import cv2
    try:
        casc = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        scale = 480 / max(g.shape)
        g = cv2.resize(g, None, fx=scale, fy=scale) if scale < 1 else g
        faces = casc.detectMultiScale(g, scaleFactor=1.1, minNeighbors=6, minSize=(max(24, g.shape[1] // 14),) * 2)
        return any(w * h >= 0.012 * g.shape[0] * g.shape[1] for (_, _, w, h) in faces)
    except Exception:
        return False


BAD_TITLE = re.compile(r"diagram|illustration|chart|schematic|infographic|poster|slide|screenshot|cartoon|drawing|logo|flag|svg|map of|graph\b|table\b", re.I)


def has_text(img) -> bool:
    """offline (no quota): text-like regions (rows of small high-contrast strokes) covering >= 2% of the picture, or 3+ of them, means a labelled
    diagram / sign / caption. Calibrated: labelled diagrams 0.08, clean NASA photos 0-0.008."""
    import cv2
    try:
        g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        k = 640 / max(g.shape)
        g = cv2.resize(g, None, fx=k, fy=k) if k < 1 else g
        grad = cv2.morphologyEx(g, cv2.MORPH_GRADIENT, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))
        _, bw = cv2.threshold(grad, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
        conn = cv2.morphologyEx(bw, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (17, 3)))
        cnts, _ = cv2.findContours(conn, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cover = n = 0
        for c in cnts:
            x, y, w, h = cv2.boundingRect(c)
            if 6 <= h <= 40 and w >= 2.2 * h and w >= 24 and 0.25 <= bw[y:y + h, x:x + w].mean() / 255 <= 0.8:
                cover += w * h
                n += 1
        return cover / (g.shape[0] * g.shape[1]) >= 0.02 or n >= 3
    except Exception:
        return False


def photo_matches(path: Path, subject: str) -> bool | None:
    """a vision model must confirm a real photo shows the subject (keyword matching alone picked a White House event for 'Carrington Event');
    any doubt or failure = reject, so the ladder moves on rather than putting a wrong picture on screen."""
    try:
        import cv2

        from . import auto
        im = cv2.imread(str(path))
        if has_face(im):
            print(f"  photo check {subject!r}: rejected (identifiable person)", flush=True)
            return False
        if has_text(im):
            print(f"  photo check {subject!r}: rejected (labels / text in the picture)", flush=True)
            return False
        jpg = cv2.imencode(".jpg", cv2.resize(im, (270, 480)), [cv2.IMWRITE_JPEG_QUALITY, 80])[1].tobytes()
        if _VISION["dead"] or _VISION["calls"] >= 14:      # free vision quota is ~10/min: cap the calls per run, then rely on strict title matching
            raise RuntimeError("vision unavailable")
        _VISION["calls"] += 1
        out, _ = auto.ask('You check a stock photo for a science explainer. Reply ONLY JSON {"relevant": true|false, "person": true|false, "text": true|false, "shows": "<=8 words"}. '
                          "relevant=true only if the picture clearly shows or illustrates the requested subject; unrelated people, events, rooms and objects are NOT relevant. "
                          "person=true if a real person's face or body is a prominent part. text=true if readable words, labels, captions, credits or signs are prominent.",
                          f"REQUESTED SUBJECT: {subject}", image=jpg, wait=False)
        print(f"  photo check {subject!r}: {out}", flush=True)
        return bool(out.get("relevant")) and not out.get("person") and not out.get("text")
    except Exception as e:
        if "429" in repr(e) or "Timeout" in repr(e) or "vision unavailable" in repr(e):
            _VISION["dead"] = True                     # free vision quota gone for this run: no more checks, strict title match decides instead
        print(f"  photo check unavailable ({str(e)[:80]}); strict title match instead", flush=True)
        return None


_VISION = {"dead": False, "calls": 0}


def _title_matches(path: Path, subject: str) -> bool:
    """fallback when no vision model answers: every subject word must be in the photo's recorded title"""
    cj = Path(path).parent / "credits.json"
    try:
        title = json.loads(cj.read_text()).get(Path(path).name, {}).get("file", "").lower()
    except (OSError, ValueError):
        return False
    words = [w for w in re.findall(r"[a-z]{3,}", subject.lower())]
    return bool(words) and all(w in title for w in words)


def _used_titles(dest: Path) -> set[str]:
    """titles of real photos already placed in this run's img/ folder, so each beat gets a different picture"""
    cj = Path(dest).parent / "credits.json"
    try:
        return {v.get("file", "") for v in json.loads(cj.read_text()).values()}
    except (OSError, ValueError):
        return set()


def openverse(query: str, dest: Path, min_w: int = 900) -> tuple[Path, dict]:
    """real CC-licensed photo from Openverse (keyless; commercial-use licences only; Flickr/Wikimedia/museum sources). Returns (file, credit)."""
    import httpx
    r = httpx.get("https://api.openverse.org/v1/images/", params={"q": query, "license_type": "commercial", "page_size": 12, "mature": "false"},
                  headers={"User-Agent": "AgentShiftShorts/1.0 (educational explainer Shorts)"}, timeout=30)
    r.raise_for_status()
    used = _used_titles(dest)
    for it in r.json().get("results", []):
        if (it.get("title") or query)[:80] in used or BAD_TITLE.search(it.get("title") or ""):
            continue
        if (it.get("width") or 0) < min_w or (it.get("license") or "").lower() not in ("cc0", "pdm", "by", "by-sa"):
            continue
        try:
            img = httpx.get(it["url"], timeout=60, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"})
        except httpx.HTTPError:
            continue
        if img.status_code != 200 or not img.headers.get("content-type", "").startswith("image"):
            continue
        out = _blur_fit(img.content, dest)
        credit = {"file": (it.get("title") or query)[:80], "license": f"CC {it.get('license', '').upper()} {it.get('license_version', '')}".strip(),
                  "artist": (it.get("creator") or it.get("source") or "")[:60], "url": it.get("foreign_landing_url") or it.get("url")}
        cj = Path(dest).parent / "credits.json"
        allc = json.loads(cj.read_text()) if cj.exists() else {}
        allc[out.name] = credit
        cj.write_text(json.dumps(allc, indent=1))
        return out, credit
    raise RuntimeError(f"no Openverse photo for {query!r}")


def _verified(fn, subject: str, dest: Path):
    """run a photo fetcher, keep the result only if it passes the vision check (and drop its credit entry otherwise)"""
    got = fn()
    out = got[0] if isinstance(got, tuple) else got
    ok = photo_matches(Path(out), subject)
    if ok is None:
        ok = _title_matches(Path(out), subject)
    if ok:
        return got
    Path(out).unlink(missing_ok=True)
    raise RuntimeError(f"photo for {subject!r} did not match")


def keywords(prompt: str, n: int = 3) -> str:
    """the subject nouns of an image prompt, in order (style words dropped) -> a short search query"""
    import re
    words = [w for w in re.findall(r"[a-z][a-z-]{3,}", prompt.lower()) if w not in STYLE and not w.endswith(("ing", "ed", "ly"))]   # verbs/adverbs rarely appear in a title
    out: list[str] = []
    for w in words:
        if w not in out:
            out.append(w)
    return " ".join(out[:n])


def nasa_still(prompt: str, dest: Path) -> tuple[Path, dict]:
    """real NASA photo for the prompt's subject (no key; used when image generation is out of free quota). Cover-fit to 9:16."""
    import httpx
    q = keywords(prompt)
    generic = {"event", "events", "test", "tests", "space", "view", "views", "image", "images", "new", "scene"}
    core = [w for w in q.split() if w not in generic] or q.split()
    head = core[0] if core else ""
    r = httpx.get("https://images-api.nasa.gov/search", params={"q": q, "media_type": "image"}, timeout=30)
    r.raise_for_status()
    items = r.json()["collection"]["items"]
    if not items and len(q.split()) > 1:                       # the API ANDs words: retry with the subject alone
        items = httpx.get("https://images-api.nasa.gov/search", params={"q": head, "media_type": "image"}, timeout=30).json()["collection"]["items"]
    words = core
    for it in items[:10]:
        d = it["data"][0]
        text = (d.get("title", "") + " " + " ".join(d.get("keywords", []) or [])).lower()
        if BAD_TITLE.search(d.get("title", "")) or head not in text or sum(1 for w in words if w in text) < min(2, len(words)):      # relevance floor: a wrong real photo is worse than none
            continue
        links = [l["href"] for l in it.get("links", []) if l.get("render") == "image"]
        if not links:
            continue
        img = httpx.get(links[0].replace("~thumb", "~large").replace("~small", "~large"), timeout=60, follow_redirects=True)
        if img.status_code != 200:
            continue
        out = _blur_fit(img.content, dest)
        credit = {"file": d.get("title", "")[:80], "license": "NASA media (public domain)", "artist": d.get("center", "NASA"),
                  "url": f"https://images.nasa.gov/details/{d['nasa_id']}"}
        cj = Path(dest).parent / "credits.json"
        allc = json.loads(cj.read_text()) if cj.exists() else {}
        allc[out.name] = credit
        cj.write_text(json.dumps(allc, indent=1))
        return out, credit
    raise RuntimeError(f"no NASA photo for {q!r}")


TOPIC = ""                       # wiki title of the Short being made (set by auto.run)
_TOPIC_USES = {"n": 0}
TEXTURED: list[str] = []
TEXTURED_FILES: dict[str, str] = {}   # img file name -> prompt, for beats whose picture is only a texture     # prompts that ended as plain texture frames (a Short made mostly of these is parked, not delivered)
def gemini_image(prompt: str, dest: Path, model: str = "gemini-2.5-flash-image") -> Path:
    """Gemini native image output (uses the free GEMINI_API_KEY; the free tier may refuse it, then the ladder moves on)."""
    import httpx
    key = os.environ["GEMINI_API_KEY"]
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    last = ""
    for cfg in ({"responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": "9:16"}}, {"responseModalities": ["IMAGE"]}):
        r = httpx.post(url, headers={"x-goog-api-key": key}, timeout=120,
                       json={"contents": [{"parts": [{"text": prompt + ". Vertical 9:16 photograph, no text, no letters, no people."}]}], "generationConfig": cfg})
        if r.status_code == 200:
            for part in r.json().get("candidates", [{}])[0].get("content", {}).get("parts", []):
                data = (part.get("inlineData") or part.get("inline_data") or {}).get("data")
                if data:
                    return _fit(base64.b64decode(data), dest)
            last = "no image in reply"
        else:
            last = f"HTTP {r.status_code}"
            if r.status_code in (429, 403):
                break
    raise RuntimeError(f"gemini image failed: {last}")


_MISSES: dict[str, int] = {}
_DEAD: set[str] = set()      # providers that told us their free quota is exhausted (reset per process)


LOOK = ", candid documentary photograph, muted natural colours, soft overcast light, fine film grain, true-to-life materials, no glow, no neon, no lens flare, no digital art"


def _styled(prompt: str) -> str:
    """every generation request ends with the same documentary look: the model's default is a glowing, over-saturated 'AI' render that the judge scores 3-4"""
    return prompt if "no neon" in prompt else prompt.rstrip(" .") + LOOK


def generate(prompt: str, dest: Path, seed: int = 7) -> tuple[Path, str]:
    """free ladder: Cloudflare FLUX -> Pollinations -> Gemini image -> real photos (NASA, Wikimedia Commons, Openverse; each vision-verified) -> texture. Returns (file, provider)."""
    errs = []
    if os.environ.get("CLOUDFLARE_API_TOKEN") and os.environ.get("CLOUDFLARE_ACCOUNT_ID") and "cloudflare" not in _DEAD:
        try:
            return flux(_styled(prompt), dest), "cloudflare-flux"
        except Exception as e:  # 429 / quota / network -> next provider
            errs.append(f"cloudflare: {e!r}")
            if "daily free allocation" in str(e):         # the quota is gone until the daily reset: no point waiting or retrying
                _DEAD.add("cloudflare")
            elif "429" in str(e):                          # rate limit or the daily quota: wait once and retry; two misses in a row = skip it for this process
                import time
                time.sleep(20)
                try:
                    return flux(_styled(prompt), dest), "cloudflare-flux"
                except Exception as e2:
                    errs.append(f"cloudflare retry: {e2!r}")
                    _MISSES["cloudflare"] = _MISSES.get("cloudflare", 0) + 1
                    if _MISSES["cloudflare"] >= 2:
                        _DEAD.add("cloudflare")
    if "pollinations" not in _DEAD:
        try:
            return pollinations(_styled(prompt), dest, seed=seed), "pollinations"
        except Exception as e:
            errs.append(str(e))
            if "HTTP 402" in str(e):
                _DEAD.add("pollinations")
    if os.environ.get("GEMINI_API_KEY") and "gemini" not in _DEAD:
        try:
            return gemini_image(_styled(prompt), dest), "gemini-image"
        except Exception as e:
            errs.append(str(e))
            if "429" in str(e) or "403" in str(e):
                _DEAD.add("gemini")
    for name, fn in (("nasa-photo", lambda p, d: _verified(lambda: nasa_still(p, d), keywords(prompt, 4), d)),
                     ("commons-photo", lambda p, d: _verified(lambda: commons(keywords(p, 4), d), keywords(prompt, 4), d)),
                     ("openverse-photo", lambda p, d: _verified(lambda: openverse(keywords(p, 3), d), keywords(prompt, 4), d))):
        try:
            return fn(prompt, dest)[0], name
        except Exception as e:
            errs.append(f"{name}: {e}")
    if TOPIC and _TOPIC_USES["n"] < 3:      # photos of the topic itself (different ones per beat): better than a blank background, at most 3 per Short
        for name, fn in (("topic-commons", lambda: commons(TOPIC, dest)), ("topic-openverse", lambda: openverse(TOPIC, dest))):
            try:
                out = fn()[0]
                _TOPIC_USES["n"] += 1
                return out, name
            except Exception as e:
                errs.append(f"{name}: {e}")
    TEXTURED.append(prompt)
    TEXTURED_FILES[Path(dest).with_suffix(".jpg").name] = prompt
    print("  all picture sources failed (" + "; ".join(errs)[:300] + ") -> plain texture frame", flush=True)
    return texture_still(prompt, dest, seed), "texture-fallback"


def commons(query: str, dest: Path, min_w: int = 700) -> tuple[Path, dict]:
    """real photo from Wikimedia Commons (free licences only). Returns (file, credit). Landscape photos are shown whole over a blurred fill."""
    import io
    import re

    import httpx
    from PIL import Image, ImageFilter
    h = {"User-Agent": "AgentShiftShorts/1.0 (https://youtube.com/@agentshiftai; educational explainer Shorts)"}
    r = httpx.get("https://commons.wikimedia.org/w/api.php", headers=h, timeout=30, params={
        "action": "query", "format": "json", "generator": "search", "gsrsearch": f"filetype:bitmap {query}", "gsrnamespace": 6, "gsrlimit": 12,
        "prop": "imageinfo", "iiprop": "url|size|mime|extmetadata", "iiurlwidth": 1600})
    r.raise_for_status()
    pages = sorted((r.json().get("query", {}).get("pages", {})).values(), key=lambda x: x.get("index", 99))
    used = _used_titles(dest)
    for pg in pages:
        if pg["title"] in used:
            continue
        ii = (pg.get("imageinfo") or [{}])[0]
        md = ii.get("extmetadata", {})
        lic = (md.get("LicenseShortName", {}).get("value") or "").lower()
        if ii.get("mime") not in ("image/jpeg", "image/png") or ii.get("width", 0) < min_w:
            continue
        if not (lic.startswith("cc") or "public domain" in lic or lic == "pd"):
            continue
        if re.search(r"logo|map|diagram|flag|svg|coat of arms", pg["title"].lower()) or BAD_TITLE.search(pg["title"]):
            continue
        img = httpx.get(ii.get("thumburl") or ii["url"], headers=h, timeout=60, follow_redirects=True)
        if img.status_code != 200:
            continue
        im = Image.open(io.BytesIO(img.content)).convert("RGB")
        bg = _layout(im)
        dest = Path(dest).with_suffix(".jpg")
        bg.save(dest, quality=92)
        credit = {"file": pg["title"], "license": ii["extmetadata"].get("LicenseShortName", {}).get("value"),
                  "artist": re.sub(r"<[^>]+>", "", md.get("Artist", {}).get("value", "")), "url": ii.get("descriptionurl")}
        cj = dest.parent / "credits.json"
        allc = json.loads(cj.read_text()) if cj.exists() else {}
        allc[dest.name] = credit
        cj.write_text(json.dumps(allc, indent=1))
        return dest, credit
    raise RuntimeError(f"no free Commons photo for {query!r}")


def ensure(spec: dict, run: Path) -> list[Path]:
    img = run / "img"
    img.mkdir(parents=True, exist_ok=True)
    missing = []
    for b in spec["beats"]:
        for shot in [b] + b.get("cuts", []):
            if "img" not in shot:
                continue
            p = img / shot["img"]
            if p.exists() or p.with_suffix(".jpg").exists():
                continue
            if shot.get("photo"):                      # real photo first: free, unlimited, credible, and it saves the daily image-generation quota
                done = False
                for name, fn in (("commons", lambda: _verified(lambda: commons(shot["photo"], p), shot["photo"], p)),
                                 ("nasa", lambda: _verified(lambda: nasa_still(shot["photo"], p), shot["photo"], p)),
                                 ("openverse", lambda: _verified(lambda: openverse(shot["photo"], p), shot["photo"], p))):
                    try:
                        fn()
                        done = True
                        break
                    except Exception as e:
                        print(f"  {name} {shot['photo']!r}: {e}", flush=True)
                if done:
                    continue
                print("  no real photo found -> generating instead", flush=True)
            if shot.get("prompt") and os.environ.get("STILLS", "free") == "free":
                generate(shot["prompt"], p, seed=int(shot.get("seed", 7)))
            else:
                missing.append((shot["img"], shot.get("prompt", "(no prompt in spec)")))
    if missing:
        raise FileNotFoundError("missing stills — generate these (9:16, photoreal, no text) into img/:\n" +
                                "\n".join(f"  {n}: {pr}" for n, pr in missing))
    return sorted(img.glob("*"))


if __name__ == "__main__" and len(sys.argv) > 3 and sys.argv[1] == "gen":
    print(generate(sys.argv[2], Path(sys.argv[3])))
