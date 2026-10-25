"""Render the overlay (HUD) only, with synthetic timing, and save a contact sheet. No LLM, no pictures, no voice: it costs no free quota.

    python -m app.hudtest [out_dir]        # used by .github/workflows/hud-test.yml; needs Playwright Chromium

Every gallery component gets one beat with sample values; the sheet shows each beat late enough for its animation to have landed.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import cv2
import numpy as np

from . import gallery_hf, hud, overlay

SAMPLES = {
    "per-word-rise": {"text": "Tracked reality for decades", "accent": "green"},
    "scramble-reveal": {"text": "KESSLER CASCADE", "style": "terminal"},
    "kinetic-type-swap": {"prefix": "Orbit becomes", "options": "crowded,hazardous,unusable", "accent": "blue"},
    "count-up": {"start": 0, "end": 27000, "suffix": " objects", "accent": "violet"},
    "chart-story": {"type": "bars", "data": "3, 12, 41, 87", "labels": "1960, 1990, 2010, 2026", "emphasize": 3, "unit": "%", "accent": "green"},
    "titlecard-lockup": {"wordmark": "Kessler Syndrome", "label": "WHEN ORBIT FILLS UP", "kicker": "WHAT IF"},
    "grid-card-assemble": {"items": "GPS,Weather,TV,Phones", "layout": "grid", "accent": "blue"},
    "vox-annotate": {"text": "One collision can cascade", "keyword": "cascade", "note": "chain reaction", "style": "highlight"},
    "native-notification-pop": {"title": "GPS signal lost", "body": "Satellites unavailable", "app_label": "Maps", "os": "ios"},
}


def synthetic(names: list[str]) -> tuple[dict, dict, float]:
    beats, segs, t = [], [], 0.0
    for i, n in enumerate(names):
        words = "this is how it would look when the sample plays out on screen now".split()
        ws = [{"w": w, "s": round(t + 0.1 + k * 0.28, 3), "e": round(t + 0.3 + k * 0.28, 3)} for k, w in enumerate(words)]
        key = f"b{i}"
        beats.append({"key": key, "say": " ".join(words), "hud": [{"t": "chip", "text": n.upper(), "col": "cy", "at": "this"},
                                                                  {"t": "hf", "name": n, "vars": SAMPLES[n], "at": "how", "dur": 3.4}]})
        segs.append({"key": key, "text": " ".join(words), "start": round(t, 3), "dur": 4.2, "words": ws})
        t += 4.4
    return {"id": "hudtest", "title": "t", "brand": "AGENT SHIFT", "series_label": "TEST", "beats": beats,
            "subscribe": {"title": "SUBSCRIBE", "sub": "for daily what-ifs"}}, {"segments": segs, "total": t}, t


def main(out: Path) -> int:
    out.mkdir(parents=True, exist_ok=True)
    names = gallery_hf.names()
    spec, timing, total = synthetic(names)
    problems = [e for b in spec["beats"] for el in b["hud"] if el["t"] == "hf" for e in gallery_hf.check(el)]
    if problems:
        print("sample problems:", problems)
        return 2
    page = hud.write(spec, timing, total, out / "page.html")
    fps = overlay.FPS
    t0 = [timing["segments"][i]["start"] + 0.89 for i in range(len(names))]      # the component starts at the anchor word ("how")
    want = [int((t + dt) * fps) for t in t0 for dt in (1.0, 2.6)]
    asyncio.run(overlay.render(page, total, out / "ovl", only=want, step=1, pages=1))
    tiles = []
    for k, w in enumerate(want):
        n = names[k // 2]
        f = out / "ovl" / f"{w:05d}.png"
        im = cv2.imread(str(f), cv2.IMREAD_UNCHANGED) if f.exists() else None
        if im is None:
            tiles.append(np.zeros((480, 270, 3), np.uint8))
            continue
        bg = np.full(im.shape[:2] + (3,), (110, 90, 70), np.uint8)       # mid-tone stand-in for a photo
        a = im[..., 3:4].astype(np.float32) / 255
        comp = (im[..., :3] * a + bg * (1 - a)).astype(np.uint8)
        cv2.putText(comp, n if k % 2 == 0 else "+1.6s", (60, 1860), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (0, 255, 255), 3)
        tiles.append(cv2.resize(comp, (270, 480)))
    cols = 6
    while len(tiles) % cols:
        tiles.append(np.zeros_like(tiles[0]))
    rows = [np.hstack(tiles[r:r + cols]) for r in range(0, len(tiles), cols)]
    cv2.imwrite(str(out / "sheet.jpg"), np.vstack(rows), [cv2.IMWRITE_JPEG_QUALITY, 88])
    print(json.dumps({"components": names, "sheet": str(out / "sheet.jpg")}))
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("hudtest_out")))
