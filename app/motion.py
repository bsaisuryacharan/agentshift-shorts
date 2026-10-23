"""Motion-graphics kit for the HUD layer (original implementations; no third-party media or prompts).

Technique families come from the 200-card reference library (data/motion_reference_library.json: product_film, ui_motion, editorial,
abstract_form, data_story, kinetic_type). The library only records technique labels; this file implements the techniques ourselves.

Element types (all anchored by spoken word via "at", all GSAP-timeline driven so frames are deterministic):
  {"t":"bars","items":[["1960","3.0","ir"],["2026","8.3","ok"]],"unit":"B"}   animated bar chart (data_story)
  {"t":"line","values":[3,3.5,4,5,6.5,8.3],"labels":["1960","2026"],"col":"cy"}  draw-on line chart with end dot (data_story)
  {"t":"ring","pct":62,"label":"of the 1960 rate","col":"am"}                   progress ring with count-up (data_story)
  {"t":"delta","text":"+176%","dir":"up","col":"ok"}                            arrow + figure pop (data_story)
  {"t":"kinetic","text":"it *tracked* reality better"}                         per-word slam-in type (kinetic_type)
  {"t":"tape","text":"CLASSIFIED","col":"am"}                                  paper strip with tape, rotated (editorial_collage)
  {"t":"toast","title":"New paper","sub":"Science, 1960","icon":"📄"}          UI notification card (ui_motion)
  {"t":"cursor","text":"SUBSCRIBE"}                                             cursor glides in and clicks a button (ui_motion)
Any element also accepts  "fx":"shine"  = a light sweep across it (product_film).
"""
from __future__ import annotations

import html as _h
import re

CSS = """
.shw{position:relative;display:inline-block;border-radius:14px}.sh{opacity:0;position:absolute;top:-20%;left:0;width:34%;height:140%;
background:linear-gradient(100deg,transparent,#ffffffd0,transparent);transform:skewX(-18deg);pointer-events:none}
.bars{margin-top:50px;width:760px;height:430px;display:flex;align-items:flex-end;justify-content:center;gap:30px}
.bw{flex:1;max-width:190px;display:flex;flex-direction:column;align-items:center;justify-content:flex-end;height:100%}
.bar{width:100%;border-radius:14px 14px 0 0;transform-origin:50% 100%;box-shadow:0 0 40px var(--c)}.bv{font-weight:800;font-size:60px;margin-bottom:10px;text-shadow:0 3px 20px #000}
.bn{margin-top:12px;font:700 28px "JetBrains Mono",monospace;letter-spacing:.1em;text-shadow:0 2px 12px #000}
.linec{margin-top:50px;width:780px}.linec svg{width:780px;height:380px;overflow:visible;filter:drop-shadow(0 0 14px var(--c))}
.linec .lbl{display:flex;justify-content:space-between;font:700 28px "JetBrains Mono",monospace;margin-top:10px;text-shadow:0 2px 12px #000}
.ringw{margin-top:50px;position:relative;width:420px;height:420px}.ringw svg{width:420px;height:420px;transform:rotate(-90deg);filter:drop-shadow(0 0 16px var(--c))}
.ringw .rv{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;font-weight:800;font-size:120px;text-shadow:0 4px 30px #000}
.rl{margin-top:14px;font-weight:800;font-size:56px;text-shadow:0 4px 30px #000}
.delta{margin-top:50px;display:flex;align-items:center;gap:20px;font-weight:800;font-size:170px;line-height:1;text-shadow:0 6px 40px #000}.delta i{font-style:normal;font-size:150px}
.kin{margin-top:60px;max-width:820px;font-weight:800;font-size:100px;line-height:1.08;text-shadow:0 4px 30px #000,0 0 3px #000}.kin .kw{display:inline-block;margin:0 .14em}.kin b{color:var(--ac)}
.tape{margin-top:60px;position:relative;padding:22px 52px;background:#f4ecd8;color:#241c10;font:800 64px "JetBrains Mono",monospace;letter-spacing:.08em;transform:rotate(-3deg);box-shadow:0 14px 40px #000a}
.tape:before,.tape:after{content:"";position:absolute;top:-18px;width:120px;height:38px;background:#ffffff88;border:1px solid #ffffff55}.tape:before{left:-34px;transform:rotate(-24deg)}.tape:after{right:-34px;transform:rotate(22deg)}
.tape u{position:absolute;left:30px;right:30px;bottom:14px;height:8px;background:var(--c);text-decoration:none}
.toast{margin-top:50px;width:760px;display:flex;align-items:center;gap:26px;padding:26px 34px;border-radius:30px;background:#14181fe6;border:2px solid #ffffff22;box-shadow:0 16px 60px #000a;text-align:left}
.toast .ic{width:92px;height:92px;border-radius:24px;display:flex;align-items:center;justify-content:center;font-size:54px;background:var(--c)}
.toast b{display:block;font-size:46px;line-height:1.1}.toast span{display:block;font-size:32px;opacity:.75;margin-top:6px}
.curw{margin-top:80px;position:relative;width:640px;height:260px}.cbtn{position:absolute;left:60px;top:70px;width:520px;padding:30px 0;border-radius:26px;background:#ff2d4d;font-weight:800;font-size:64px;box-shadow:0 12px 50px #ff2d4d77}
.cur{position:absolute;left:0;top:0;width:90px;height:90px;filter:drop-shadow(0 6px 10px #000)}.rip{position:absolute;left:290px;top:130px;width:60px;height:60px;margin:-30px;border-radius:50%;border:6px solid #fff;opacity:0}
"""

_ACC = re.compile(r"\*(.+?)\*")


def _col(el: dict, COL: dict) -> str:
    return COL.get(el.get("col", "cy"), el.get("col", "#38e1ff"))


def build(page, beat: dict, el: dict, eid: str, col: str, at: float, COL: dict) -> str | None:
    t, sel, A = el["t"], f"#{eid}", page.A
    if t == "bars":
        items = el["items"]
        mx = max(float(v) for _, v, *_ in items) or 1
        cells = []
        for k, it in enumerate(items):
            n, v = it[0], it[1]
            c = COL.get(it[2] if len(it) > 2 else "cy", "#38e1ff")
            hgt = max(8, round(float(v) / mx * 300))
            cells.append(f'<div class="bw"><div class="bv" style="color:{c}">{_h.escape(str(v))}{_h.escape(el.get("unit", ""))}</div>'
                         f'<div class="bar" style="height:{hgt}px;background:{c};--c:{c}88"></div><div class="bn">{_h.escape(str(n))}</div></div>')
        A(f'tl.from("{sel} .bar",{{scaleY:0,duration:.8,stagger:.25,ease:"expo.out"}},{at});tl.from("{sel} .bv",{{opacity:0,y:20,duration:.4,stagger:.25}},{at + .5});')
        return f'<div class="bars" id="{eid}">{"".join(cells)}</div>'
    if t == "line":
        vals = [float(v) for v in el["values"]]
        lo, hi = min(vals), max(vals)
        pts = [(round(i / (len(vals) - 1) * 760 + 10, 1), round(350 - (v - lo) / ((hi - lo) or 1) * 320, 1)) for i, v in enumerate(vals)]
        d = "M" + " L".join(f"{x},{y}" for x, y in pts)
        lab = el.get("labels", [])
        lh = f'<div class="lbl"><span>{_h.escape(str(lab[0]))}</span><span>{_h.escape(str(lab[-1]))}</span></div>' if lab else ""
        A(f'(function(){{var p=document.querySelector("{sel} path"),L=p.getTotalLength();p.style.strokeDasharray=L;'
          f'tl.fromTo(p,{{strokeDashoffset:L}},{{strokeDashoffset:0,duration:{el.get("dur", 1.6)},ease:"power2.inOut"}},{at});'
          f'tl.from("{sel} circle",{{scale:0,transformOrigin:"center",duration:.35,ease:"back.out(3)"}},{at + el.get("dur", 1.6) - .1});}})();')
        return (f'<div class="linec" id="{eid}" style="--c:{col}"><svg viewBox="0 0 780 380"><path d="{d}" fill="none" stroke="{col}" stroke-width="12" '
                f'stroke-linecap="round" stroke-linejoin="round"/><circle cx="{pts[-1][0]}" cy="{pts[-1][1]}" r="18" fill="#fff" stroke="{col}" stroke-width="8"/></svg>{lh}</div>')
    if t == "ring":
        pct = max(0, min(100, float(el["pct"])))
        circ = 2 * 3.14159 * 170
        A(f'tl.fromTo("{sel} .fg",{{strokeDashoffset:{circ:.1f}}},{{strokeDashoffset:{circ * (1 - pct / 100):.1f},duration:1.3,ease:"power2.out"}},{at});'
          f'(function(){{var c={{v:0}},e=document.querySelector("{sel} .rv");tl.to(c,{{v:{pct},duration:1.3,ease:"power2.out",onUpdate:function(){{e.textContent=Math.round(c.v)+"%"}}}},{at});}})();')
        lab = f'<div class="rl" id="{eid}l">{_h.escape(el["label"])}</div>' if el.get("label") else ""
        if lab:
            A(f'tl.from("#{eid}l",{{y:24,opacity:0,duration:.4}},{at + .6});')
        return (f'<div class="ringw" id="{eid}" style="--c:{col}"><svg viewBox="0 0 420 420"><circle cx="210" cy="210" r="170" fill="none" stroke="#ffffff22" stroke-width="34"/>'
                f'<circle class="fg" cx="210" cy="210" r="170" fill="none" stroke="{col}" stroke-width="34" stroke-linecap="round" stroke-dasharray="{circ:.1f}" stroke-dashoffset="{circ:.1f}"/></svg>'
                f'<div class="rv" style="color:{col}">0%</div></div>{lab}')
    if t == "delta":
        up = el.get("dir", "up") == "up"
        A(f'tl.from("{sel} i",{{y:{80 if up else -80},opacity:0,duration:.5,ease:"back.out(2.4)"}},{at});tl.from("{sel} b",{{scale:1.6,opacity:0,duration:.45,ease:"expo.out"}},{at + .1});')
        return f'<div class="delta" id="{eid}" style="color:{col}"><i>{"▲" if up else "▼"}</i><b>{_h.escape(el["text"])}</b></div>'
    if t == "kinetic":
        words = []
        for w in el["text"].split():
            m = _ACC.fullmatch(w)
            words.append(f'<span class="kw">{"<b>" + _h.escape(m.group(1)) + "</b>" if m else _h.escape(w)}</span>')
        A(f'tl.from("{sel} .kw",{{y:90,scale:1.7,rotation:6,opacity:0,duration:.42,stagger:.13,ease:"back.out(2.2)"}},{at});')
        return f'<div class="kin" id="{eid}" style="--ac:{col}">{"".join(words)}</div>'
    if t == "tape":
        A(f'tl.from("{sel}",{{scale:.6,rotation:-14,y:-60,opacity:0,duration:.5,ease:"back.out(2)"}},{at});tl.from("{sel} u",{{scaleX:0,transformOrigin:"0 50%",duration:.5}},{at + .45});')
        return f'<div class="tape" id="{eid}" style="--c:{col}">{_h.escape(el["text"])}<u></u></div>'
    if t == "toast":
        A(f'tl.from("{sel}",{{y:-140,opacity:0,scale:.9,duration:.55,ease:"back.out(1.8)"}},{at});tl.from("{sel} .ic",{{rotation:-30,scale:.4,duration:.4,ease:"back.out(3)"}},{at + .15});')
        return (f'<div class="toast" id="{eid}" style="--c:{col}"><div class="ic">{_h.escape(el.get("icon", "★"))}</div>'
                f'<div><b>{_h.escape(el["title"])}</b><span>{_h.escape(el.get("sub", ""))}</span></div></div>')
    if t == "cursor":
        svg = '<svg class="cur" viewBox="0 0 24 24"><path d="M4 2l16 9-7 2-3 7z" fill="#fff" stroke="#000" stroke-width="1.2"/></svg>'
        A(f'tl.from("{sel} .cbtn",{{scale:.8,opacity:0,duration:.35,ease:"back.out(2)"}},{at});'
          f'tl.fromTo("{sel} .cur",{{x:520,y:230,opacity:0}},{{x:300,y:120,opacity:1,duration:.7,ease:"power2.inOut"}},{at + .3});'
          f'tl.to("{sel} .cbtn",{{scale:.93,duration:.1}},{at + 1.05});tl.to("{sel} .cbtn",{{scale:1,duration:.25,ease:"back.out(3)"}},{at + 1.15});'
          f'tl.fromTo("{sel} .rip",{{scale:.2,opacity:1}},{{scale:3.2,opacity:0,duration:.6,immediateRender:false}},{at + 1.05});')
        return f'<div class="curw" id="{eid}"><div class="cbtn">🔔 {_h.escape(el["text"])}</div><div class="rip"></div>{svg}</div>'
    return None


def shine(page, inner: str, eid: str, at: float) -> str:
    """wrap any element's markup with a sweeping light band (product_film technique)."""
    # clip only while the band sweeps, so the element's own entrance animation is never cropped
    page.A(f'tl.set("#{eid}w",{{overflow:"hidden"}},{at + .34});tl.fromTo("#{eid}w .sh",{{xPercent:-130}},{{xPercent:360,duration:.9,ease:"power2.inOut"}},{at + .35});'
           f'tl.set("#{eid}w",{{overflow:"visible"}},{at + 1.3});'
           f'tl.set("#{eid}w .sh",{{opacity:1}},{at + .34});tl.set("#{eid}w .sh",{{opacity:0}},{at + 1.28});')
    return f'<div class="shw" id="{eid}w">{inner}<i class="sh"></i></div>'
