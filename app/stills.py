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


def flux(prompt: str, dest: Path, width: int = 768, height: int = 1344) -> Path:
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
        last = r.status_code
    r = httpx.post(base + "flux-1-schnell", headers=h, json={"prompt": prompt, "steps": 8}, timeout=120)   # square -> cropped
    if r.status_code == 200:
        return _fit(base64.b64decode(r.json()["result"]["image"]), dest)
    raise RuntimeError(f"cloudflare image models failed (klein {last}, schnell {r.status_code})")


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


STYLE = {"photoreal", "photorealistic", "cinematic", "image", "shot", "view", "dramatic", "lighting", "light", "ultra", "detailed", "highly", "background",
         "style", "realistic", "closeup", "close-up", "wide", "angle", "aerial", "macro", "top-down", "silhouette", "soft", "natural", "documentary", "with", "from",
         "against", "above", "over", "into", "that", "this", "their", "while", "scene", "composition", "depth", "field", "bokeh", "sharp", "focus"}


def _blur_fit(raw: bytes, dest: Path) -> Path:
    """landscape photos are shown whole (width 1000) over a blurred, darkened copy of themselves; portrait/square photos are cover-fitted."""
    import io

    from PIL import Image, ImageEnhance, ImageFilter
    im = Image.open(io.BytesIO(raw)).convert("RGB")
    W, H = 1080, 1920
    if im.width / im.height < 0.75:
        return _fit(raw, dest)
    sc = max(W / im.width, H / im.height)
    bg = im.resize((int(im.width * sc) + 1, int(im.height * sc) + 1), Image.LANCZOS).filter(ImageFilter.GaussianBlur(40))
    bg = ImageEnhance.Brightness(bg.crop(((bg.width - W) // 2, (bg.height - H) // 2, (bg.width - W) // 2 + W, (bg.height - H) // 2 + H))).enhance(0.7)
    fg = im.resize((1000, int(im.height * 1000 / im.width)), Image.LANCZOS)
    bg.paste(fg, ((W - 1000) // 2, 620 - fg.height // 2))
    bg.save(dest.with_suffix(".jpg"), quality=92)
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
    head = q.split()[0] if q else ""
    r = httpx.get("https://images-api.nasa.gov/search", params={"q": q, "media_type": "image"}, timeout=30)
    r.raise_for_status()
    items = r.json()["collection"]["items"]
    if not items and len(q.split()) > 1:                       # the API ANDs words: retry with the subject alone
        items = httpx.get("https://images-api.nasa.gov/search", params={"q": head, "media_type": "image"}, timeout=30).json()["collection"]["items"]
    words = q.split()
    for it in items[:10]:
        d = it["data"][0]
        text = (d.get("title", "") + " " + " ".join(d.get("keywords", []) or [])).lower()
        if head not in text or sum(1 for w in words if w in text) < min(2, len(words)):      # relevance floor: a wrong real photo is worse than none
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


_DEAD: set[str] = set()      # providers that told us their free quota is exhausted (reset per process)


def generate(prompt: str, dest: Path, seed: int = 7) -> tuple[Path, str]:
    """free ladder: Cloudflare FLUX -> Pollinations -> real NASA photo -> real Wikimedia Commons photo. Returns (file, provider)."""
    errs = []
    if os.environ.get("CLOUDFLARE_API_TOKEN") and os.environ.get("CLOUDFLARE_ACCOUNT_ID") and "cloudflare" not in _DEAD:
        try:
            return flux(prompt, dest), "cloudflare-flux"
        except Exception as e:  # 429 / quota / network -> next provider
            errs.append(f"cloudflare: {e!r}")
            if "429" in str(e):
                _DEAD.add("cloudflare")                  # daily free quota is gone: skip it for the rest of this process
    if "pollinations" not in _DEAD:
        try:
            return pollinations(prompt, dest, seed=seed), "pollinations"
        except Exception as e:
            errs.append(str(e))
            if "HTTP 402" in str(e):
                _DEAD.add("pollinations")
    for name, fn in (("nasa-photo", nasa_still), ("commons-photo", lambda p, d: commons(keywords(p, 4), d))):
        try:
            return fn(prompt, dest)[0], name
        except Exception as e:
            errs.append(f"{name}: {e}")
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
    for pg in pages:
        ii = (pg.get("imageinfo") or [{}])[0]
        md = ii.get("extmetadata", {})
        lic = (md.get("LicenseShortName", {}).get("value") or "").lower()
        if ii.get("mime") not in ("image/jpeg", "image/png") or ii.get("width", 0) < min_w:
            continue
        if not (lic.startswith("cc") or "public domain" in lic or lic == "pd"):
            continue
        if re.search(r"logo|map|diagram|flag|svg|coat of arms", pg["title"].lower()):
            continue
        img = httpx.get(ii.get("thumburl") or ii["url"], headers=h, timeout=60, follow_redirects=True)
        if img.status_code != 200:
            continue
        im = Image.open(io.BytesIO(img.content)).convert("RGB")
        W, H = 1080, 1920
        bg = im.copy()
        sc = max(W / bg.width, H / bg.height)
        bg = bg.resize((int(bg.width * sc) + 1, int(bg.height * sc) + 1), Image.LANCZOS).filter(ImageFilter.GaussianBlur(40))
        bg = bg.crop(((bg.width - W) // 2, (bg.height - H) // 2, (bg.width - W) // 2 + W, (bg.height - H) // 2 + H))
        if im.width / im.height < 0.75:       # portrait: cover-fit
            sc = max(W / im.width, H / im.height)
            fg = im.resize((int(im.width * sc) + 1, int(im.height * sc) + 1), Image.LANCZOS)
            bg = fg.crop(((fg.width - W) // 2, (fg.height - H) // 2, (fg.width - W) // 2 + W, (fg.height - H) // 2 + H))
        else:                                  # landscape/square: whole photo, width 1000, centred over blur
            fw = 1000
            fg = im.resize((fw, int(im.height * fw / im.width)), Image.LANCZOS)
            bg.paste(fg, ((W - fw) // 2, 520 - fg.height // 2 + 300 if fg.height < 900 else (H - fg.height) // 2))
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
            if shot.get("photo"):
                try:
                    commons(shot["photo"], p)
                    continue
                except Exception as e:
                    print(f"  commons {shot['photo']!r}: {e} -> generating instead", flush=True)
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
