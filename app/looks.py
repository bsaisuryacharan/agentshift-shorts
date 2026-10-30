"""One visual look per Short, from the Claude Video 2.0 style library (MIT, github.com/ItsssssJack/claude-video-2; vendored in
assets/styles/claude-video-2/styles/<look>/STYLE.md with the full rules: palette, type, easing, motion rules, ban list).

    LOOKS            the looks that suit vertical Shorts, with their tokens (taken from each STYLE.md)
    css(look)        CSS appended to the overlay page: the look's fonts and colours for every caption and graphic (one visual language)
    background(look) a designed 1080x1920 ground for "graphic" beats (pure motion graphics instead of an AI picture)
    prompt_block()   the menu the script writer chooses from

Why: the judge's most frequent complaints were AI renders of real objects and mixed fonts/colours. A graphic beat carries the idea with big type,
numbers and diagrams on the look's ground; photo and footage beats keep their pictures but share the same type and accent.
"""
from __future__ import annotations

import math
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "assets" / "styles" / "claude-video-2" / "styles"

# tokens transcribed from each STYLE.md (ground, text ink, card/panel, accent, fonts) + the background pattern that STYLE.md describes
LOOKS = {
    "poster-pop": {"ground": "#FFD400", "ink": "#111111", "panel": "#111111", "panel_ink": "#FFFFFF", "accent": "#111111", "dark": False,
                   "display": "League Gothic", "body": "Archivo Black", "gfonts": "League+Gothic&family=Archivo+Black", "pattern": "rays",
                   "best": "hooks, big claims, countdowns, '3 things' lists"},
    "swiss-grid": {"ground": "#FFFFFF", "ink": "#111111", "panel": "#111111", "panel_ink": "#FFFFFF", "accent": "#E4002B", "dark": False,
                   "display": "Inter", "body": "Inter", "gfonts": "Inter:wght@700;900", "pattern": "grid:#E6E6E6",
                   "best": "titles, product facts, kinetic type, clean explainers"},
    "blueprint": {"ground": "#0E3A66", "ink": "#EAF3FC", "panel": "#0B2E52", "panel_ink": "#EAF3FC", "accent": "#FFD23F", "dark": True,
                  "display": "Archivo", "body": "JetBrains Mono", "gfonts": "Archivo:wght@700;900", "pattern": "grid:#1C4D80",
                  "best": "how things work, engineering, machines, step by step"},
    "midnight-grid": {"ground": "#0B1220", "ink": "#E8EDF7", "panel": "#111A2E", "panel_ink": "#E8EDF7", "accent": "#5B8CFF", "dark": True,
                      "display": "Inter", "body": "Inter", "gfonts": "Inter:wght@600;700;900", "pattern": "dots:#1E2A44",
                      "best": "tech explainers, AI and software, space, diagrams"},
    "editorial-paper": {"ground": "#FFF1E5", "ink": "#1A1A1A", "panel": "#1A1A1A", "panel_ink": "#FFF1E5", "accent": "#0F5499", "dark": False,
                        "display": "Playfair Display", "body": "Playfair Display", "gfonts": "Playfair+Display:wght@700;900", "pattern": "paper:#E3D3C3",
                        "best": "data, history, 'what the numbers say'"},
    "explainer-diagram": {"ground": "#FFFFFF", "ink": "#14213D", "panel": "#14213D", "panel_ink": "#FFFFFF", "accent": "#2F6BFF", "dark": False,
                          "display": "Inter", "body": "Inter", "gfonts": "Inter:wght@700;800", "pattern": "dots:#E2E2E8",
                          "best": "how something works, systems, processes, comparisons"},
    "graphite-ui": {"ground": "#0E0F12", "ink": "#ECEDEF", "panel": "#17181C", "panel_ink": "#ECEDEF", "accent": "#3DD68C", "dark": True,
                    "display": "Inter", "body": "Inter", "gfonts": "Inter:wght@600;700", "pattern": "vignette",
                    "best": "tech news, software, scores and stats cards"},
    "risograph": {"ground": "#F5F0E6", "ink": "#0078BF", "panel": "#FF48B0", "panel_ink": "#FFFFFF", "accent": "#FF48B0", "dark": False,
                  "display": "Archivo Black", "body": "Archivo Black", "gfonts": "Archivo+Black", "pattern": "halftone:#FF48B0",
                  "best": "playful nature and culture topics, bold announcements"},
}
DEFAULT_BY_FORMAT = {"ranked": "poster-pop", "scale": "midnight-grid", "versus": "explainer-diagram", "how_it_works": "blueprint",
                     "timeline": "editorial-paper", "unsolved": "graphite-ui", "myth_vs_fact": "swiss-grid", "what_if": "midnight-grid"}


def pick(look: str | None, fmt: str | None = None) -> str:
    return look if look in LOOKS else DEFAULT_BY_FORMAT.get(fmt or "", "midnight-grid")


def prompt_block() -> str:
    return "; ".join(f"{k} ({v['best']})" for k, v in LOOKS.items())


def css(look: str | None) -> str:
    """fonts and colours of the look for the overlay page; graphic beats (.beat.graphic) also take its ground-matched text colours and panels"""
    if look not in LOOKS:
        return ""
    t = LOOKS[look]
    d, b = f'"{t["display"]}",sans-serif', f'"{t["body"]}",sans-serif'
    return (f'@import url("https://fonts.googleapis.com/css2?family={t["gfonts"]}&display=block");'
            f':root{{--ac:{t["accent"]}}}'
            f'html,body{{font-family:{b}}}'
            f'.ttl,.big,.lab,.bub,.stamp,.row b,.li b,.stp b,#caps{{font-family:{d};letter-spacing:-.01em}}'
            f'.bub{{background:{t["panel"]};color:{t["panel_ink"]}}}.bub:after{{border-top-color:{t["panel"]}}}'
            f'.ttl b,.bub span,.sub b,.li em{{color:{t["accent"] if t["accent"] != t["ink"] else t["panel_ink"]}}}'
            f'.beat.graphic .scrim,.beat.graphic .dim{{display:none}}'
            f'.beat.graphic .ttl,.beat.graphic .big,.beat.graphic .lab,.beat.graphic .arw{{color:{t["ink"]};text-shadow:none}}'
            f'.beat.graphic .sub,.beat.graphic .row,.beat.graphic .li,.beat.graphic .stp,.beat.graphic .chip,.beat.graphic .stamp'
            f'{{background:{t["panel"]};color:{t["panel_ink"]};border-color:{t["accent"]};box-shadow:none}}'
            f'.beat.graphic .ttl{{font-size:132px}}.beat.graphic .big{{font-size:240px}}')


def _rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[4:6], 16), int(h[2:4], 16), int(h[0:2], 16)         # BGR for OpenCV


def background(look: str, w: int = 1080, h: int = 1920, seed: int = 0) -> np.ndarray:
    """the look's designed ground as described in its STYLE.md: flat colour plus its pattern (rays, grid, dots, paper grain, halftone, vignette)"""
    t = LOOKS[pick(look)]
    img = np.zeros((h, w, 3), np.uint8)
    img[:] = _rgb(t["ground"])
    kind, _, col = t["pattern"].partition(":")
    rng = np.random.default_rng(seed)
    off = (seed * 23) % 60                                          # every graphic beat gets a visibly different ground (same look, shifted pattern)
    if kind == "rays":                                              # poster burst: alternating wedges, rotated and moved per beat
        cx, cy = w // 2 + ((seed * 97) % 400) - 200, int(h * 0.30) + (seed * 131) % 500
        darker = tuple(max(0, c - 34) for c in _rgb(t["ground"]))
        rot = seed * 0.21
        for i in range(0, 24, 2):
            a0, a1 = i * math.pi / 12 + rot, (i + 1) * math.pi / 12 + rot
            pts = np.array([[cx, cy], [cx + 3000 * math.cos(a0), cy + 3000 * math.sin(a0)], [cx + 3000 * math.cos(a1), cy + 3000 * math.sin(a1)]], np.int32)
            cv2.fillPoly(img, [pts], darker)
    elif kind == "grid":
        th = 2 if t["dark"] else 1
        for x in range(off, w, 60):
            cv2.line(img, (x, 0), (x, h), _rgb(col), th)
        for y in range(off, h, 60):
            cv2.line(img, (0, y), (w, y), _rgb(col), th)
    elif kind == "dots":
        for x in range(20 + off % 40, w, 40):
            for y in range(20 + (off * 2) % 40, h, 40):
                cv2.circle(img, (x, y), 3, _rgb(col), -1)
    elif kind == "halftone":
        for y in range(0, h, 28):
            for x in range(0, w, 28):
                r = int(6 * max(0.0, 1 - math.hypot(x - (w * 0.8 if seed % 2 == 0 else w * 0.2), y - (h * 0.15 + (seed * 160) % 1200)) / 900))
                if r:
                    cv2.circle(img, (x, y), r, _rgb(col), -1)
    elif kind == "paper":
        for y in range(off, h, 64):
            cv2.line(img, (0, y), (w, y), _rgb(col), 1)
    if kind in ("paper", "rays", "halftone") or not t["dark"]:          # fine grain so flat grounds do not band after compression
        img = np.clip(img.astype(np.int16) + rng.normal(0, 3, img.shape[:2])[..., None].astype(np.int16), 0, 255).astype(np.uint8)
    if t["dark"]:                                                   # soft vignette keeps the eye in the centre
        yy, xx = np.mgrid[0:h, 0:w]
        v = 1 - 0.35 * (((xx - w / 2) / (w / 2)) ** 2 + ((yy - h * 0.45) / (h / 2)) ** 2)
        img = np.clip(img * v[..., None], 0, 255).astype(np.uint8)
    return img


def write_background(look: str, dest: Path, seed: int = 0) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(dest), background(look, seed=seed), [cv2.IMWRITE_JPEG_QUALITY, 92])
    return dest
