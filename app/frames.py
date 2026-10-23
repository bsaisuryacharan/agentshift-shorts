"""Deterministic HyperFrames frame generator.

The LLM decides *what* each beat says; this module decides *how* it is built, so a
bad model can never improvise invalid GSAP or break the frame contract. Every
generated frame follows the rules learned from the delivered Earth short:

* 1080x1920, 30fps, one paused timeline seeked to 0
* copy stays above y=1400 (caption band starts at 1452)
* no infinite repeats, no letterSpacing tweens, no drawSVG
* grain is GSAP-animated so ffmpeg freezedetect never sees a frozen stretch
* at least one non-text visual layer per beat (rings, gauge, bars, rail, globe)

Scene kinds: hook, stat, compare, timeline, diagram, statement, close.
"""
from __future__ import annotations

import html
import math
import re
import shutil
from pathlib import Path

from .models import Beat, VideoSpec

ACCENTS = {
    "hot": ("#FF3B1F", "255, 59, 31"),
    "electric": ("#2AE5FF", "42, 229, 255"),
    "acid": ("#E8FF3D", "232, 255, 61"),
}

FONTS = {
    "anton-latin-400-normal.woff2": "Anton",
    "inter-latin-400-normal.woff2": "Inter",
    "inter-latin-600-normal.woff2": "Inter",
    "inter-latin-800-normal.woff2": "Inter",
    "inter-latin-900-normal.woff2": "Inter",
    "jetbrains-mono-latin-500-normal.woff2": "JetBrains Mono",
    "jetbrains-mono-latin-700-normal.woff2": "JetBrains Mono",
}

TEMPLATE = """<template>
  <div id="root" data-composition-id="@@ID@@" data-duration="@@D@@" data-fps="30" data-width="1080" data-height="1920">
    <style>
@@FONTS@@
      #root {
        position: absolute;
        inset: 0;
        overflow: hidden;
        isolation: isolate;
        background: #08080b;
        color: #f2ede3;
        font-family: "Inter", system-ui, sans-serif;
        --accent: @@ACCENT@@;
        --accent-rgb: @@ACCENT_RGB@@;
      }
      #bg {
        position: absolute;
        inset: -10%;
        background:
          radial-gradient(58% 40% at 52% 74%, rgba(var(--accent-rgb), 0.34) 0%, rgba(var(--accent-rgb), 0.07) 48%, transparent 72%),
          radial-gradient(46% 30% at 15% 10%, rgba(242, 237, 227, 0.07) 0%, transparent 70%),
          #08080b;
      }
      #grid {
        position: absolute;
        inset: 0;
        background-image: linear-gradient(rgba(242, 237, 227, 0.055) 1px, transparent 1px);
        background-size: 100% 8px;
        opacity: 0.55;
      }
      #cam { position: absolute; inset: 0; transform-origin: 50% 58%; }
      #scene { position: absolute; inset: 0; width: 1080px; height: 1920px; }
      .meta {
        position: absolute;
        left: 88px;
        font-family: "JetBrains Mono", monospace;
        font-weight: 500;
        font-size: 28px;
        letter-spacing: 0.18em;
        text-transform: uppercase;
        color: rgba(242, 237, 227, 0.66);
      }
      #meta-top { top: 112px; display: flex; gap: 22px; white-space: nowrap; }
      #meta-top b { color: var(--accent); font-weight: 500; }
      #meta-bot { bottom: 560px; right: 88px; left: auto; color: rgba(242, 237, 227, 0.5); }
      #copy { position: absolute; left: 88px; width: 904px; top: @@TOP@@; }
      .kick {
        font-family: "JetBrains Mono", monospace;
        font-weight: 500;
        font-size: 28px;
        letter-spacing: 0.22em;
        text-transform: uppercase;
        color: var(--accent);
        margin-bottom: 26px;
      }
      .l {
        display: block;
        font-family: "Anton", sans-serif;
        text-transform: uppercase;
        line-height: 0.88;
        letter-spacing: -0.012em;
        color: #f2ede3;
      }
      #sub {
        margin-top: 34px;
        max-width: 820px;
        font-family: "Inter", system-ui, sans-serif;
        font-weight: 600;
        font-size: 34px;
        line-height: 1.34;
        color: rgba(242, 237, 227, 0.84);
      }
      #big {
        font-family: "Anton", sans-serif;
        line-height: 0.98;
        padding-bottom: 26px;
        color: #f2ede3;
        letter-spacing: -0.02em;
      }
      #unit {
        margin-top: 30px;
        font-family: "JetBrains Mono", monospace;
        font-size: 30px;
        letter-spacing: 0.24em;
        color: var(--accent);
        text-transform: uppercase;
      }
      .row { margin-top: 34px; }
      .row .rl {
        font-family: "JetBrains Mono", monospace;
        font-size: 28px;
        letter-spacing: 0.2em;
        color: rgba(242, 237, 227, 0.7);
        text-transform: uppercase;
      }
      .row .rv {
        font-family: "Anton", sans-serif;
        font-size: 78px;
        line-height: 1;
        margin-top: 6px;
      }
      .bar { position: relative; height: 10px; margin-top: 14px; background: rgba(242, 237, 227, 0.13); }
      .bar i { position: absolute; inset: 0 auto 0 0; background: var(--accent); transform-origin: 0% 50%; }
      #sweep {
        position: absolute;
        top: 0;
        left: -160px;
        width: 92px;
        height: 1920px;
        background: linear-gradient(90deg, transparent, rgba(242, 237, 227, 0.045), transparent);
      }
      #grain { position: absolute; inset: 0; width: 1080px; height: 1920px; opacity: 0.07; }
      #vig {
        position: absolute;
        inset: 0;
        background: radial-gradient(72% 58% at 50% 48%, transparent 40%, rgba(0, 0, 0, 0.55) 100%);
      }
      @@EXTRA_CSS@@
    </style>

    <div id="bg"></div>
    <div id="grid"></div>
    <div id="scene-wrap">
      <svg id="scene" viewBox="0 0 1080 1920" preserveAspectRatio="none" data-layout-ignore aria-hidden="true">
@@SCENE@@
      </svg>
    </div>
    <div id="cam">
      <div id="copy">
@@COPY@@
      </div>
      <div id="meta-top" class="meta">@@KICKER@@</div>
      <div id="meta-bot" class="meta">@@META_BOT@@</div>
    </div>
    <svg id="rail" viewBox="0 0 1080 1920" data-layout-ignore aria-hidden="true">
@@RAIL@@
    </svg>
    <div id="sweep" data-layout-ignore></div>
    <svg id="grain" viewBox="0 0 1080 1920" preserveAspectRatio="none" data-layout-ignore aria-hidden="true">
      <filter id="gn"><feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="2" stitchTiles="stitch"/><feColorMatrix type="saturate" values="0"/></filter>
      <rect width="1080" height="1920" filter="url(#gn)" opacity="0.5"/>
    </svg>
    <div id="vig"></div>

    <script>
      const tl = gsap.timeline({ paused: true });
      const D = @@D@@;
      const REPEATS = Math.max(1, Math.floor(D / 0.22) - 1);
      gsap.set("#root", { autoAlpha: 1 });
@@LINES@@
@@SCENE_JS@@
      tl.fromTo("#cam", { scale: 1 }, { scale: @@CAM@@, duration: D, ease: "none" }, 0);
      tl.fromTo("#sweep", { x: 0 }, { x: 1400, duration: D * 0.9, ease: "none" }, 0.1);
      tl.to("#grain", { opacity: 0.24, duration: 0.22, repeat: REPEATS, yoyo: true, ease: "none" }, 0.2);
      tl.seek(0);
      window.__timelines["@@ID@@"] = tl;
    </script>
  </div>
</template>
"""

FONT_FACE = """      @font-face {
        font-family: "@@FAMILY@@";
        font-weight: @@WEIGHT@@;
        font-display: block;
        src: url("assets/fonts/@@FILE@@") format("woff2"),
          url("https://cdn.jsdelivr.net/npm/@fontsource/@@PKG@@/files/@@FILE@@") format("woff2");
      }"""


def _esc(text: str) -> str:
    return html.escape(text, quote=True)


def _line_size(line: str) -> int:
    return int(max(46, min(190, 904 / (0.52 * max(len(line), 4)))))


def _wrap(text: str, max_lines: int = 3) -> list[str]:
    words = text.split()
    if not words:
        return [""]
    target = min(18, max(8, math.ceil(len(text) / max_lines) + 2))
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and len(candidate) > target and len(lines) < max_lines - 1:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines[:max_lines]


def _copy_html(beat: Beat) -> tuple[str, int]:
    parts: list[str] = []
    top = 452
    if beat.kicker:
        parts.append(f'<div class="kick">{_esc(beat.kicker)}</div>')

    if beat.kind == "stat" and beat.value:
        size = int(max(80, min(240, 904 / (0.56 * max(len(beat.value), 3)))))
        parts.append(f'<div id="big" style="font-size:{size}px">{_esc(beat.value)}</div>')
        if beat.unit:
            parts.append(f'<div id="unit">{_esc(beat.unit)}</div>')
        if beat.sub:
            parts.append(f'<div id="sub">{_esc(beat.sub)}</div>')
        elif beat.headline:
            parts.append(f"<div id='sub' style='font-family:\"Anton\",sans-serif;font-size:74px;line-height:0.94;text-transform:uppercase'>{_esc(beat.headline)}</div>")
    elif beat.kind == "compare":
        lines = _wrap(beat.headline, 2)
        for index, line in enumerate(lines, 1):
            parts.append(f'<span id="l{index}" class="l" style="font-size:{min(104, _line_size(line))}px">{_esc(line)}</span>')
        parts.append(_compare_instrument(beat))
    elif beat.kind == "timeline":
        lines = _wrap(beat.headline, 2)
        for index, line in enumerate(lines, 1):
            parts.append(f'<span id="l{index}" class="l" style="font-size:{min(104, _line_size(line))}px">{_esc(line)}</span>')
        if beat.sub:
            parts.append(f'<div id="sub">{_esc(beat.sub)}</div>')
        parts.append(_timeline_instrument(beat))
    elif beat.kind == "close":
        lines = _wrap(beat.headline, 3)
        for index, line in enumerate(lines, 1):
            parts.append(f'<span id="l{index}" class="l" style="font-size:{min(150, _line_size(line))}px">{_esc(line)}</span>')
        if beat.sub:
            parts.append(f"<div id='sub' style='font-family:\"JetBrains Mono\",monospace;letter-spacing:0.2em;text-transform:uppercase;font-size:28px'>{_esc(beat.sub)}</div>")
    else:
        lines = _wrap(beat.headline, 2 if beat.kind == "hook" else 3)
        for index, line in enumerate(lines, 1):
            size = _line_size(line)
            if beat.kind == "hook":
                size = min(180, size)
            elif beat.kind == "statement":
                size = min(132, size)
            else:
                size = min(112, size)
            parts.append(f'<span id="l{index}" class="l" style="font-size:{size}px">{_esc(line)}</span>')
        if beat.sub:
            parts.append(f'<div id="sub">{_esc(beat.sub)}</div>')

    if beat.kind == "hook":
        top = 492
    elif beat.kind == "stat":
        top = 430
    elif beat.kind == "compare":
        top = 548
    elif beat.kind == "timeline":
        top = 470
    elif beat.kind == "close":
        top = 588
    else:
        top = 566
    return "\n".join(parts), top


def _compare_instrument(beat: Beat) -> str:
    left = max(1, min(100, beat.left_pct))
    right = max(1, min(100, beat.right_pct))
    return (
        '<div class="row">'
        f'<div class="rl">{_esc(beat.left)}</div><div class="rv" style="color:var(--accent)">{left}%</div>'
        f'<div class="bar"><i id="barL" style="width:{left}%"></i></div></div>'
        '<div class="row">'
        f'<div class="rl">{_esc(beat.right)}</div><div class="rv">{right}%</div>'
        f'<div class="bar"><i id="barR" style="width:{right}%;opacity:.55"></i></div></div>'
    )


def _timeline_instrument(beat: Beat) -> str:
    ticks = beat.ticks or ["NOW", "+1", "+2", "+3", "+4", "+5", "+6"]
    cells = "".join(
        f'<span style="flex:1;text-align:center">{_esc(tick)}</span>' for tick in ticks[:7]
    )
    return (
        '<div style="margin-top:38px;display:flex;border-top:2px solid rgba(242,237,227,.28);padding-top:14px;'
        "font-family:'JetBrains Mono',monospace;font-size:28px;letter-spacing:.1em;color:rgba(242,237,227,.62)\">"
        f"{cells}</div>"
        '<div style="position:relative;height:14px;margin-top:-9px">'
        '<i id="marker" style="position:absolute;top:-8px;left:0;width:16px;height:30px;background:var(--accent)"></i>'
        "</div>"
    )


def _scene_svg(kind: str) -> str:
    if kind == "hook":
        rings = "".join(
            f'<circle cx="770" cy="1160" r="{180 + i * 82}" fill="none" stroke="rgba(242,237,227,{0.2 - i * 0.026:.3f})" stroke-width="2"/>'
            for i in range(4)
        )
        return (
            '<defs><radialGradient id="planet" cx="38%" cy="30%" r="72%">'
            '<stop offset="0%" stop-color="rgba(242,237,227,.30)"/><stop offset="60%" stop-color="rgba(255,59,31,.22)"/>'
            '<stop offset="100%" stop-color="rgba(8,8,11,0)"/></radialGradient></defs>'
            f'<g id="rings">{rings}</g>'
            '<circle cx="770" cy="1160" r="176" fill="url(#planet)" stroke="rgba(242,237,227,.4)" stroke-width="2"/>'
            '<path d="M 600 1160 A 340 96 0 0 1 940 1160" fill="none" stroke="rgba(255,59,31,.5)" stroke-width="4"/>'
        )
    if kind == "stat":
        ticks = "".join(
            f'<line x1="{540 + 300 * math.cos(math.radians(a)):.1f}" y1="{980 + 300 * math.sin(math.radians(a)):.1f}" '
            f'x2="{540 + 322 * math.cos(math.radians(a)):.1f}" y2="{980 + 322 * math.sin(math.radians(a)):.1f}" '
            'stroke="rgba(242,237,227,.35)" stroke-width="3"/>'
            for a in range(30, 151, 20)
        )
        return (
            '<path d="M 240 980 A 300 300 0 0 0 840 980" fill="none" stroke="rgba(242,237,227,.14)" stroke-width="10"/>'
            '<path id="gauge" d="M 240 980 A 300 300 0 0 0 840 980" pathLength="100" fill="none" '
            'stroke="rgba(255,59,31,.85)" stroke-width="10" stroke-linecap="round" stroke-dasharray="100" stroke-dashoffset="100"/>'
            f'<g data-layout-ignore>{ticks}</g>'
        )
    if kind == "compare":
        return (
            '<g opacity=".9">'
            '<rect x="88" y="900" width="904" height="2" fill="rgba(242,237,227,.18)"/>'
            '<rect x="88" y="1290" width="904" height="2" fill="rgba(242,237,227,.18)"/>'
            '</g>'
        )
    if kind == "timeline":
        return (
            '<circle cx="150" cy="1040" r="34" fill="rgba(255,59,31,.85)" id="sun"/>'
            '<path d="M 88 1112 H 992" stroke="rgba(242,237,227,.22)" stroke-width="2"/>'
        )
    if kind == "diagram":
        lat = "".join(
            f'<ellipse cx="540" cy="{1010 + dy}" rx="{math.sqrt(max(1, 300 ** 2 - dy ** 2)):.0f}" ry="26" fill="none" stroke="rgba(242,237,227,.12)" stroke-width="2"/>'
            for dy in (-170, -90, 0, 90, 170)
        )
        winds = "".join(
            f'<path id="w{i}" d="M 300 {880 + i * 72} C 470 {830 + i * 72}, 610 {950 + i * 72}, 790 {880 + i * 72}" '
            'fill="none" stroke="rgba(42,229,255,.55)" stroke-width="4" pathLength="100" stroke-dasharray="100" stroke-dashoffset="0"/>'
            for i in range(3)
        )
        return (
            '<circle cx="540" cy="1010" r="300" fill="rgba(242,237,227,.03)" stroke="rgba(242,237,227,.32)" stroke-width="3"/>'
            f'<g data-layout-ignore>{lat}</g>'
            '<ellipse cx="540" cy="1010" rx="300" ry="104" fill="none" stroke="rgba(255,59,31,.55)" stroke-width="3"/>'
            f'<g id="winds" data-layout-ignore>{winds}</g>'
            '<path d="M 540 710 V 1310" stroke="rgba(242,237,227,.16)" stroke-width="2" stroke-dasharray="8 12"/>'
        )
    if kind == "statement":
        waves = "".join(
            f'<path d="M 0 {1250 + i * 54} Q 270 {1180 + i * 54}, 540 {1250 + i * 54} T 1080 {1250 + i * 54}" '
            f'fill="none" stroke="rgba(242,237,227,{0.16 - i * 0.03:.2f})" stroke-width="{3 - i * 0.4:.1f}"/>'
            for i in range(4)
        )
        return f'<g id="waves" data-layout-ignore>{waves}</g><circle cx="860" cy="560" r="120" fill="rgba(255,59,31,.12)"/>'
    # close
    return (
        '<g id="loop">'
        '<circle cx="540" cy="1268" r="150" fill="none" stroke="rgba(242,237,227,.22)" stroke-width="3"/>'
        '<circle id="looparc" cx="540" cy="1268" r="150" fill="none" stroke="rgba(255,59,31,.8)" stroke-width="4" '
        'pathLength="100" stroke-dasharray="100" stroke-dashoffset="100" transform="rotate(-90 540 1268)"/>'
        '<circle cx="540" cy="1118" r="10" fill="#ff3b1f"/>'
        '</g>'
        '<path d="M 300 1420 H 780" stroke="rgba(242,237,227,.16)" stroke-width="2"/>'
    )


def _lines_js(copy_html: str) -> str:
    tween = []
    for index in range(1, 4):
        if f'id="l{index}"' in copy_html:
            tween.append(
                f'      tl.from("#l{index}", {{ y: 76, opacity: 0, duration: 0.52, ease: "power4.out" }}, {0.06 + (index - 1) * 0.09:.2f});'
            )
    if 'id="sub"' in copy_html:
        tween.append('      tl.from("#sub", { y: 26, opacity: 0, duration: 0.5, ease: "power2.out" }, 0.42);')
    if tween:
        tween.append('      tl.from(".kick", { opacity: 0, duration: 0.4, ease: "power2.out" }, 0.02);')
    return "\n".join(tween)


def _scene_js(kind: str, beat: Beat) -> str:
    if kind == "stat":
        raw = beat.value.replace(",", "")
        script = []
        if raw.isdigit():
            script.append(f'      const COUNT_TO = {int(raw)};')
            script.append(
                '      tl.to({ v: 0 }, { v: COUNT_TO, duration: 1.5, ease: "power2.out", '
                'onUpdate() { const el = document.querySelector("#big"); if (el) el.textContent = Math.round(this.targets()[0].v).toLocaleString("en-US"); } }, 0.3);'
            )
        script.append('      tl.fromTo("#gauge", { strokeDashoffset: 100 }, { strokeDashoffset: 12, duration: 1.8, ease: "power2.inOut" }, 0.2);')
        script.append('      tl.from("#unit", { opacity: 0, duration: 0.5, ease: "power2.out" }, 1.1);')
        return "\n".join(script)
    if kind == "compare":
        return (
            '      tl.from("#barL", { scaleX: 0, duration: 0.9, ease: "power3.out" }, 0.35);\n'
            '      tl.from("#barR", { scaleX: 0, duration: 0.9, ease: "power3.out" }, 0.6);\n'
            '      tl.from(".rv", { y: 22, opacity: 0, stagger: 0.12, duration: 0.5, ease: "power2.out" }, 0.3);'
        )
    if kind == "timeline":
        return (
            '      tl.fromTo("#marker", { x: 0 }, { x: 860, duration: Math.max(1.2, D - 1.4), ease: "none" }, 0.6);\n'
            '      tl.fromTo("#sun", { scale: 0.6, opacity: 0.5 }, { scale: 1, opacity: 1, duration: 0.7, ease: "power3.out" }, 0.2);'
        )
    if kind == "diagram":
        return (
            '      for (const w of ["#w0", "#w1", "#w2"]) tl.from(w, { strokeDashoffset: 100, duration: 1.1, ease: "power2.out" }, 0.4);\n'
            '      tl.to("#winds", { opacity: 0.3, duration: 0.4, ease: "none" }, Math.max(1.4, D - 1.2));'
        )
    if kind == "statement":
        return (
            '      tl.from("#waves", { opacity: 0, y: 40, duration: 0.9, ease: "power3.out" }, 0.25);'
        )
    if kind == "close":
        return (
            '      tl.fromTo("#looparc", { strokeDashoffset: 100 }, { strokeDashoffset: 0, duration: 1.7, ease: "power2.inOut" }, 0.3);\n'
            '      tl.from("#loop", { opacity: 0, duration: 0.8, ease: "power2.out" }, 0.15);'
        )
    # hook
    return '      tl.from("#rings", { opacity: 0, scale: 0.94, duration: 1.1, ease: "power3.out" }, 0.1);'


def _fonts_css() -> str:
    faces = []
    for file, family in FONTS.items():
        weight = re.search(r"(\d{3})-normal", file)
        pkg = "anton" if family == "Anton" else ("jetbrains-mono" if family == "JetBrains Mono" else "inter")
        faces.append(
            FONT_FACE.replace("@@FAMILY@@", family)
            .replace("@@WEIGHT@@", weight.group(1) if weight else "400")
            .replace("@@FILE@@", file)
            .replace("@@PKG@@", pkg)
        )
    return "\n".join(faces)


def frame_html(spec: VideoSpec, beat: Beat, index: int, duration: float, total: int) -> str:
    accent, accent_rgb = ACCENTS[beat.accent]
    copy, top = _copy_html(beat)
    composition_id = f"{index:02d}-{beat.id}"
    meta_bot = " · ".join([f"{index:02d}/{total:02d}", *beat.meta])[:64]
    kicker = f"<b>{_esc(spec.title[:34])}</b>"
    cam = 1.05 if beat.kind not in {"close"} else 1.03
    return (
        TEMPLATE.replace("@@FONTS@@", _fonts_css())
        .replace("@@ID@@", composition_id)
        .replace("@@D@@", f"{duration:.3f}")
        .replace("@@ACCENT@@", accent)
        .replace("@@ACCENT_RGB@@", accent_rgb)
        .replace("@@TOP@@", f"{top}px")
        .replace("@@SCENE@@", _scene_svg(beat.kind))
        .replace("@@RAIL@@", _rail_svg())
        .replace("@@COPY@@", copy)
        .replace("@@KICKER@@", kicker)
        .replace("@@META_BOT@@", _esc(meta_bot))
        .replace("@@LINES@@", _lines_js(copy))
        .replace("@@SCENE_JS@@", _scene_js(beat.kind, beat))
        .replace("@@CAM@@", f"{cam:.2f}")
    )


def _rail_svg() -> str:
    ticks = "".join(
        f'<line x1="{88 + i * 41}" y1="1322" x2="{88 + i * 41}" y2="{1336 if i % 6 else 1346}" '
        f'stroke="rgba(242,237,227,{0.30 if i % 6 == 0 else 0.14})" stroke-width="2"/>'
        for i in range(23)
    )
    return (
        '<line x1="88" y1="1300" x2="992" y2="1300" stroke="rgba(242,237,227,.12)" stroke-width="2"/>'
        f'<g id="rail-ticks">{ticks}</g>'
        '<rect x="88" y="1296" width="120" height="8" fill="rgba(255,59,31,.85)"/>'
    )


def _storyboard(spec: VideoSpec, durations: dict[str, float], total: float) -> str:
    lines = [
        "---",
        "format: 1080x1920",
        f"duration: {total:.0f}s",
        f'message: "{spec.thesis}"',
        "arc: " + " → ".join(beat.kicker or beat.kind for beat in spec.beats),
        f"audience: {spec.audience}",
        "mode: autonomous",
        "music: none",
        "---",
        "",
    ]
    for index, beat in enumerate(spec.beats, 1):
        lines += [
            f"## Frame {index} — {beat.kicker or beat.headline[:40]}",
            "",
            f"- scene: {beat.kind} beat, {beat.headline[:90]}",
            f"- duration: {durations[beat.id]:.3f}s",
            f"- poster: {max(0.8, durations[beat.id] - 1.4):.1f}s",
            "- transition_in: cut",
            "- status: animated",
            f'- voiceover: "{beat.say}"',
            f"- src: compositions/frames/{index:02d}-{beat.id}.html",
            "- effects: grain-overlay, yt-camera-move, accent sweep",
            f"- claims: {', '.join(beat.claims) or 'none'}",
            "",
            beat.sub or beat.headline or beat.kind,
            "",
        ]
    return "\n".join(lines)


def _script_md(spec: VideoSpec, durations: dict[str, float]) -> str:
    lines = ["# SCRIPT", "", f"**Voice:** {spec.voice} · Kokoro · flat, low, deadpan", ""]
    for index, beat in enumerate(spec.beats, 1):
        lines += [
            f"## {index:02d} — {beat.kicker or beat.kind.title()} (Frame {index})",
            f"**duration:** {durations[beat.id]:.1f}s",
            "",
            f"    {beat.say}",
            "",
        ]
    return "\n".join(lines)


def write_project(video_dir: Path, spec: VideoSpec, durations: dict[str, float] | None = None,
                  template_dir: Path | None = None) -> dict[str, Path]:
    """Write SCRIPT.md, STORYBOARD.md and one HTML file per beat. Idempotent."""
    durations = durations or spec.estimate_durations()
    total = round(sum(durations.values()), 3)
    (video_dir / "compositions" / "frames").mkdir(parents=True, exist_ok=True)
    (video_dir / "assets" / "fonts").mkdir(parents=True, exist_ok=True)
    (video_dir / "assets" / "visuals").mkdir(parents=True, exist_ok=True)

    if template_dir:
        font_src = template_dir / "assets" / "fonts"
        if font_src.is_dir():
            for font in font_src.glob("*.woff2"):
                if not (video_dir / "assets" / "fonts" / font.name).exists():
                    shutil.copy2(font, video_dir / "assets" / "fonts" / font.name)
        skin = template_dir / ".hyperframes" / "caption-skin.html"
        if skin.is_file():
            (video_dir / ".hyperframes").mkdir(parents=True, exist_ok=True)
            shutil.copy2(skin, video_dir / ".hyperframes" / "caption-skin.html")
        project = template_dir / "hyperframes.json"
        if project.is_file() and not (video_dir / "hyperframes.json").exists():
            shutil.copy2(project, video_dir / "hyperframes.json")
        package = template_dir / "package.json"
        if package.is_file() and not (video_dir / "package.json").exists():
            shutil.copy2(package, video_dir / "package.json")

    written: dict[str, Path] = {}
    for index, beat in enumerate(spec.beats, 1):
        path = video_dir / "compositions" / "frames" / f"{index:02d}-{beat.id}.html"
        path.write_text(frame_html(spec, beat, index, durations[beat.id], len(spec.beats)), encoding="utf-8")
        written[beat.id] = path

    script = video_dir / "SCRIPT.md"
    script.write_text(_script_md(spec, durations), encoding="utf-8")
    storyboard = video_dir / "STORYBOARD.md"
    storyboard.write_text(_storyboard(spec, durations, total), encoding="utf-8")
    (video_dir / "spec.json").write_text(spec.model_dump_json(indent=2), encoding="utf-8")
    (video_dir / "fact_ledger.json").write_text(
        spec.model_dump_json(include={"sources", "claims"}, indent=2), encoding="utf-8"
    )
    (video_dir / "STYLE.md").write_text(_style_md(spec), encoding="utf-8")
    return written


def _style_md(spec: VideoSpec) -> str:
    return (
        "# STYLE\n\n"
        "ink #08080B · paper #F2EDE3 · hot #FF3B1F · electric #2AE5FF · acid #E8FF3D\n\n"
        "Anton for display, Inter for body, JetBrains Mono for meta. 88px side safe margins.\n\n"
        "Captions live at y=1452-1752; frame copy never crosses y=1400.\n\n"
        f"Promise: {spec.promise}\n\nThesis: {spec.thesis}\n"
    )
