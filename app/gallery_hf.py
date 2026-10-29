"""HyperFrames component gallery (open source, Apache-2.0) mounted as HUD motion graphics.

assets/gallery/hyperframes/components/<name>/ holds unmodified copies of nine registry components (see SOURCE.md). Each is an elastic,
parameterised snippet: it reads its variables from window.__hyperframes.getVariables(), builds itself in a host box and registers one paused
GSAP timeline under window.__timelines[<name>]. The overlay page mounts it in an iframe and drives its timeline from the Short's master timeline,
so the overlay renderer (which seeks that master timeline frame by frame) renders it deterministically.

Writer-facing element:
    {"t": "hf", "name": "count-up", "vars": {"end": 87, "suffix": "%"}, "at": "word", "dur": 2.5, "h": 380}

    names()                -> available component names
    prompt_block()         -> the list for the script writer's system prompt (names, required and optional variables)
    check(el)              -> list of problems with one element (empty = fine)
    build(page, beat, el, eid, at) -> HTML for the host box; appends the mount/drive JS to the page's timeline script
"""
from __future__ import annotations

import html as _h
import json
import re
from pathlib import Path

LIB = Path(__file__).resolve().parent.parent / "assets" / "gallery" / "hyperframes" / "components"
GSAP = Path(__file__).resolve().parent / "assets" / "gsap.min.js"

# default host-box height (px, width is the 870px stage) and the variables that must be supplied (others keep the component's own default)
HEIGHT = {"per-word-rise": 360, "scramble-reveal": 300, "kinetic-type-swap": 340, "count-up": 380, "chart-story": 700,
          "titlecard-lockup": 420, "grid-card-assemble": 560, "vox-annotate": 420, "native-notification-pop": 260}
MUST = {"per-word-rise": ["text"], "scramble-reveal": ["text"], "kinetic-type-swap": ["prefix", "options"], "count-up": ["end"],
        "chart-story": ["data", "labels"], "titlecard-lockup": ["wordmark"], "grid-card-assemble": ["items"],
        "vox-annotate": ["text", "keyword", "note"], "native-notification-pop": ["title", "body"]}
USE = {"per-word-rise": "a headline that lands word by word with the narration", "scramble-reveal": "a technical term or claim resolving like a terminal",
       "kinetic-type-swap": "one sentence whose key word rolls through alternatives (options = comma list, last is final)",
       "count-up": "ONE statistic counting up to its exact value (needs a number from FACTS)", "chart-story": "a small chart of 3-6 real values (type bars|line|donut|progress)",
       "titlecard-lockup": "a calm title card (wordmark, optional kicker/label)", "grid-card-assemble": "3-6 labelled cards assembling (items = comma list)",
       "vox-annotate": "a sentence with ONE keyword marked by hand and a short note", "native-notification-pop": "a phone notification banner (title, body)"}
BLOCKED_VARS = {"exit", "cues"}      # the master timeline owns timing and exits


# chart-story and grid-card-assemble stay vendored but are not offered to the writer: their axis/label text is ~12 px at 870 px width, unreadable on a phone
# (the built-in bars/line/rows/list elements cover charts and lists at proper size)
ENABLED = ["per-word-rise", "kinetic-type-swap", "count-up", "titlecard-lockup", "vox-annotate"]            # native-notification-pop ships an opaque demo backdrop; scramble-reveal reads as garbled text in mid-animation frames (judge complaint)


def names() -> list[str]:
    return [n for n in ENABLED if (LIB / n / f"{n}.html").exists()]


def meta(name: str) -> dict:
    return json.loads((LIB / name / "registry-item.json").read_text())


def _vars(name: str) -> dict[str, dict]:
    return {v["id"]: v for v in meta(name).get("variables", [])}


def prompt_block() -> str:
    out = []
    for n in names():
        vs = _vars(n)
        must = MUST[n]
        opt = [f"{k}({'|'.join(str(o['value']) for o in v['options'])})" if v.get("type") == "enum" else k
               for k, v in vs.items() if k not in must and k not in BLOCKED_VARS and k not in ("accent",)]
        out.append(f'{n}: {USE[n]}. needs vars {must}; optional {opt[:6]}; accent green|blue|violet')
    return "\n".join(out)


def repair(el: dict) -> None:
    """fix the slips writers make most (lists for strings, long strings, numbers as text, unknown extra vars) in place, so a good script is not thrown away"""
    name, given = el.get("name"), el.get("vars")
    if name not in names() or not isinstance(given, dict):
        return
    vs = _vars(name)
    for k in list(given):
        d, v = vs.get(k), given[k]
        if d is None or k in BLOCKED_VARS:
            if k not in MUST[name]:
                given.pop(k)
            continue
        t = d.get("type")
        if t == "string":
            if isinstance(v, list):
                v = ", ".join(map(str, v))
            v = str(v)
            if len(v) > 90:
                cut = v[:90]
                v = cut[:cut.rfind(",")] if "," in cut else cut[:cut.rfind(" ")] if " " in cut else cut
            given[k] = v.strip(" ,")
        elif t == "number" and isinstance(v, str):
            try:
                given[k] = float(v.replace(",", "")) if "." in v else int(v.replace(",", ""))
            except ValueError:
                pass
        elif t == "boolean" and isinstance(v, str):
            given[k] = v.strip().lower() in ("true", "yes", "1")


def check(el: dict) -> list[str]:
    name = el.get("name")
    if name not in names():
        return [f"hf: unknown component {name!r}; use one of {names()}"]
    errs = []
    vs, given = _vars(name), el.get("vars") or {}
    if not isinstance(given, dict):
        return ["hf: vars must be an object"]
    for k in MUST[name]:
        if k not in given:
            errs.append(f"hf {name}: missing var {k}")
    for k, v in given.items():
        d = vs.get(k)
        if d is None or k in BLOCKED_VARS:
            errs.append(f"hf {name}: unknown var {k}")
            continue
        t = d.get("type")
        if t == "number" and (isinstance(v, bool) or not isinstance(v, (int, float))):
            errs.append(f"hf {name}.{k}: must be a number")
        elif t == "string" and (not isinstance(v, str) or len(v) > 90):
            errs.append(f"hf {name}.{k}: must be a string <= 90 chars")
        elif t == "boolean" and not isinstance(v, bool):
            errs.append(f"hf {name}.{k}: must be true/false")
        elif t == "enum" and v not in [o["value"] for o in d.get("options", [])]:
            errs.append(f"hf {name}.{k}: {v!r} not one of {[o['value'] for o in d.get('options', [])]}")
    return errs


def _template(name: str, dur: float) -> str:
    src = (LIB / name / f"{name}.html").read_text()
    m = re.search(r"<template>(.*)</template>", src, re.S)
    if not m:
        raise ValueError(f"{name}: no <template> in component")
    inner = re.sub(r"<script[^>]*src=[\"'][^\"']*gsap[^\"']*[\"'][^>]*>\s*</script>", "", m.group(1))   # the page supplies GSAP locally
    return re.sub(r'data-duration="[\d.]+"', f'data-duration="{dur:g}"', inner)


def _doc(name: str, vars_: dict, dur: float, fonts: str) -> str:
    tpl = _template(name, dur)
    return ("<!doctype html><html><head><meta charset='utf-8'>"
            f"<link href='https://fonts.googleapis.com/css2?family=Anton&family=JetBrains+Mono:wght@500;700&family={fonts}&display=block' rel='stylesheet'>"
            "<style>html,body{margin:0;width:100%;height:100%;overflow:hidden;background:transparent}"
            "#host{position:absolute;inset:0;--bg:transparent;--fg:#fff;--brand:#5eead4;--accent:#61a8ff;--accent-2:#b895ff;"
            "--font-display:'Bricolage Grotesque',Inter,system-ui,sans-serif;--font-mono:'JetBrains Mono',ui-monospace,monospace}</style>"
            f"<script src='{GSAP.as_uri()}'></script></head><body><div id='host'></div>"
            f"<script>window.__hyperframes={{getVariables:function(){{return {json.dumps(vars_)}}}}};</script>"
            f"<template id='t'>{tpl}</template>"
            "<script>document.getElementById('host').appendChild(document.getElementById('t').content.cloneNode(true));</script></body></html>")


def build(page, beat: dict, el: dict, eid: str, at: float) -> str:
    errs = check(el)
    if errs:
        raise ValueError("; ".join(errs))
    name = el["name"]
    seg_end = next((s["start"] + s["dur"] for s in page.tm["segments"] if s["key"] == beat["key"]), at + 3)
    dur = round(max(1.2, min(float(el.get("dur", 3.0)), seg_end - at)), 2)
    h = int(min(max(float(el.get("h", HEIGHT[name])), 200), 800))
    fonts = page.spec.get("gfonts", "Bricolage+Grotesque:opsz,wght@12..96,700;12..96,800")
    doc = _doc(name, el.get("vars") or {}, dur, fonts)
    src = json.dumps(doc).replace("</", "<\\/")          # a literal </script> inside the string would end the page's own script block
    page.A(
        f'(function(){{var host=document.getElementById("{eid}");var f=document.createElement("iframe");'
        f'f.setAttribute("scrolling","no");f.style.cssText="position:absolute;inset:0;width:100%;height:100%;border:0;background:transparent";'
        f'f.srcdoc={src};host.appendChild(f);window.__hf=window.__hf||[];'
        f'window.__hf.push(new Promise(function(r){{f.addEventListener("load",function(){{setTimeout(function(){{try{{f.contentDocument.fonts.ready.then(r)}}catch(e){{r()}}}},60)}})}}));'
        f'var P={{t:0}};tl.set(host,{{opacity:1}},{at});'
        f'tl.to(P,{{t:{dur},duration:{dur},ease:"none",onUpdate:function(){{window.__hfT=window.__hfT||{{}};window.__hfT["{eid}"]=P.t.toFixed(3);try{{var T=f.contentWindow.__timelines["{name}"];if(T)T.seek(P.t,false)}}catch(e){{}}}}}},{at});}})();')
    return f'<div class="hf" id="{eid}" style="width:870px;height:{h}px;opacity:0;position:relative;margin-top:30px"></div>'
