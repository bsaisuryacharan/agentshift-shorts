"""Render a transparent HUD overlay (PNG per frame) from an HTML/GSAP page, for app.cinematic.

The page must expose a PAUSED GSAP timeline as window.__timelines.main (same contract as HyperFrames).
Caption + safe-zone rules live in docs/STYLE_BIBLE.md; app/qa_v2.safe_zone_overlay() enforces them.

    python -m app.overlay page.html 45.4 work/ovl [frame,frame,...]   (HUD at 15 fps; set overlay_step=2 in the shotlist)
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

FPS = 30


async def _worker(browser, page: Path, frames: list[int], out: Path) -> dict[int, int]:
    """contiguous frame range; a frame whose DOM is identical to the previous one is not re-screenshotted (map idx->idx)."""
    pg = await browser.new_page(viewport={"width": 1080, "height": 1920})
    errs: list[str] = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
    await pg.goto(page.resolve().as_uri())
    try:
        await pg.wait_for_function("!!(window.__timelines && window.__timelines.main)", timeout=45000, polling=100)
    except Exception as ex:
        raise RuntimeError("overlay page never built its timeline; page errors: " + " | ".join(errs)[:600] + f" ({type(ex).__name__}: {str(ex)[:120]})")
    mapping, prev_hash, prev_idx = {}, None, None
    for i in frames:
        h = await pg.evaluate("t=>{window.__timelines.main.seek(t,false);return document.body.innerHTML.length+':'+"
                              "Array.from(document.querySelectorAll('[style]')).map(e=>e.getAttribute('style')).join('|')+'|'+JSON.stringify(window.__hfT||{})}", i / FPS)
        if h == prev_hash and prev_idx is not None:
            mapping[i] = prev_idx
            continue
        await pg.screenshot(path=str(out / f"{i:05d}.png"), type="png", omit_background=True)
        prev_hash, prev_idx = h, i
    return mapping


async def render(page: Path, total: float, out: Path, only: list[int] | None = None, step: int = 2, pages: int = 3) -> None:
    """step=2 renders the HUD at 15 fps (cinematic holds frames); `pages` browser pages split the timeline into contiguous
    ranges and run concurrently; unchanged frames are de-duplicated into ovl/map.json."""
    import json
    from playwright.async_api import async_playwright
    out.mkdir(parents=True, exist_ok=True)
    frames = only or list(range(0, int(total * FPS), step))
    k = -(-len(frames) // pages)
    async with async_playwright() as p:
        b = await p.chromium.launch(args=["--no-sandbox"])
        maps = await asyncio.gather(*[_worker(b, page, frames[x:x + k], out) for x in range(0, len(frames), k)])
        await b.close()
    (out / "map.json").write_text(json.dumps({str(a): b_ for m in maps for a, b_ in m.items()}))


if __name__ == "__main__":
    a = sys.argv
    asyncio.run(render(Path(a[1]), float(a[2]), Path(a[3]), [int(x) for x in a[4].split(",")] if len(a) > 4 else None))
