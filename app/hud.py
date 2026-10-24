"""Spec -> transparent HUD page (HTML + one paused GSAP timeline) for app.overlay / app.cinematic.

Everything lives inside the safe column  x 60..930  (right 150 px reserved for YouTube buttons) and stage y 150..1270
(bottom 500 px reserved for channel/title). Captions are pinned bottom:540px. qa_v2.safe_zone_overlay enforces this.

Beat HUD elements (beat["hud"] = list, rendered top-to-bottom, each anchored on a spoken word via "at"):
  {"t":"bubble","text":"what if?"}                       speech-bubble opener
  {"t":"title","html":"1960 said *doomsday*"}            hero line, *x* = accent colour
  {"t":"chip","text":"SCIENCE · 1960","col":"cy"}       small outlined tag
  {"t":"big","text":"24","count":{"to":24,"dec":0,"suffix":""},"col":"am"}   hero number (optional count-up)
  {"t":"label","text":"estimates"}   {"t":"sub","html":"≈ <b>2,000 years</b>"}
  {"t":"rows","items":[["1960","3.0","billion","ok"],["2026","8.3","billion","ir"]]}   comparison rows
  {"t":"chain","steps":[["1","crash"],["1,000s","fragments"]]}                       process steps
  {"t":"list","items":[["📡","GPS","navigation"]]}       icon rows
  {"t":"stamp","text":"NOT INFINITY"}                    rotated stamp
Colours: cy am ok ir pk vi.   "at": "word" or {"word":"x","nth":1}; default = beat start + 0.15.
"""
from __future__ import annotations

import html as _h
import json
import re
from pathlib import Path

from . import motion
from .voice import word_time

COL = {"cy": "#38e1ff", "am": "#ffb547", "ok": "#3dff9a", "ir": "#ff3b5c", "pk": "#ff4fd8", "vi": "#a78bfa"}
ASSETS = Path(__file__).parent / "assets"


def _accent(s: str) -> str:
    return re.sub(r"\*(.+?)\*", r"<b>\1</b>", s)


class Page:
    def __init__(self, spec: dict, timing: dict, total: float):
        self.spec, self.tm, self.total = spec, timing, total
        self.html, self.js = [], []
        self.n = 0

    def safe_element(self, beat: dict, el: dict, i: int) -> str:
        """one malformed hud element (LLM output) must never kill a render: drop it, say so, keep the Short."""
        n = len(self.js)
        try:
            return self.element(beat, el, i)
        except Exception as e:
            del self.js[n:]
            print(f"  hud: skipped malformed {el.get('t')!r} element in beat {beat.get('key')}: {type(e).__name__}: {e}", flush=True)
            return ""

    def A(self, s: str) -> None:
        self.js.append("try{" + s + "}catch(e){console.error('hud:',e.message)}")

    def at(self, beat: dict, el: dict, i: int) -> float:
        a = el.get("at")
        seg = next(s for s in self.tm["segments"] if s["key"] == beat["key"])
        if not a:
            return round(seg["start"] + 0.15 + 0.25 * i, 3)
        word, nth = (a, 0) if isinstance(a, str) else (a["word"], a.get("nth", 0))
        return round(word_time(self.tm, beat["key"], word, nth, default=seg["start"] + 0.4) - 0.05, 3)

    def element(self, beat: dict, el: dict, i: int) -> str:
        self.n += 1
        eid = f"e{self.n}"
        t, col = el["t"], COL.get(el.get("col", "cy"), el.get("col", "#38e1ff"))
        at = self.at(beat, el, i)
        sel = f"#{eid}"
        if t == "bubble":
            h = f'<div class="bub" id="{eid}">{_h.escape(el["text"][:-1])}<span>{_h.escape(el["text"][-1])}</span></div>'
            self.A(f'tl.from("{sel}",{{scale:.3,rotation:-8,opacity:0,duration:.5,ease:"back.out(2.2)"}},{at});')
        elif t == "title":
            h = f'<div class="ttl" id="{eid}" style="--ac:{col}">{_accent(el["html"])}</div>'
            self.A(f'tl.from("{sel}",{{y:50,opacity:0,duration:.5,ease:"expo.out"}},{at});')
        elif t == "chip":
            h = f'<div class="chip mono" id="{eid}" style="color:{col};border-color:{col}">{_h.escape(el["text"])}</div>'
            self.A(f'tl.from("{sel}",{{scale:.4,opacity:0,duration:.3,ease:"back.out(2)"}},{at});')
        elif t == "big":
            c = el.get("count")
            if isinstance(c, (int, float)) and not isinstance(c, bool):      # writers sometimes send a bare number
                c = {"to": c}
            elif not isinstance(c, dict):
                c = None
            h = f'<div class="big" id="{eid}" style="color:{col}">{_h.escape(el["text"]) if not c else "0"}</div>'
            self.A(f'tl.from("{sel}",{{scale:1.5,opacity:0,duration:.45,ease:"expo.out"}},{at});')
            if c:
                dec = int(c.get("dec", 0))
                fmt = f"c.v.toFixed({dec})" if dec else "Math.round(c.v).toLocaleString('en-US')"
                self.A(f'(function(){{var c={{v:0}},e=document.querySelector("{sel}");tl.to(c,{{v:{c["to"]},duration:{c.get("dur",1.1)},ease:"power2.out",'
                       f'onUpdate:function(){{e.textContent={fmt}+"{c.get("suffix","")}"}}}},{at});}})();')
        elif t == "label":
            h = f'<div class="lab" id="{eid}">{_h.escape(el["text"])}</div>'
            self.A(f'tl.from("{sel}",{{y:30,opacity:0,duration:.4,ease:"expo.out"}},{at});')
        elif t == "sub":
            h = f'<div class="sub" id="{eid}">{_accent(el["html"])}</div>'
            self.A(f'tl.from("{sel}",{{y:30,opacity:0,duration:.4,ease:"expo.out"}},{at});')
        elif t == "rows":
            rows = "".join(f'<div class="row" style="border-color:{COL.get(c, "#fff")}88"><em class="mono">{_h.escape(str(l or ""))}</em>'
                           f'<b style="color:{COL.get(c, "#fff")}">{_h.escape(str(v or ""))}</b><span>{_h.escape(str(u or ""))}</span></div>' for l, v, u, c in el["items"])
            h = f'<div class="rows" id="{eid}">{rows}</div>'
            self.A(f'tl.from("{sel} .row",{{x:-100,opacity:0,duration:.4,stagger:{el.get("stagger", .6)},ease:"expo.out"}},{at});')
        elif t == "chain":
            parts = []
            for k, (a, b) in enumerate(el["steps"]):
                parts.append(f'<div class="stp"><b>{_h.escape(a)}</b><i>{_h.escape(b)}</i></div>')
                if k < len(el["steps"]) - 1:
                    parts.append('<div class="arw">→</div>')
            h = f'<div class="chain" id="{eid}" style="--ac:{col}">{"".join(parts)}</div>'
            self.A(f'tl.from("{sel} .stp",{{scale:.4,opacity:0,duration:.35,stagger:{el.get("stagger", .5)},ease:"back.out(2)"}},{at});')
            self.A(f'tl.from("{sel} .arw",{{opacity:0,x:-16,duration:.25,stagger:{el.get("stagger", .5)}}},{at + .2});')
        elif t == "list":
            rows = "".join(f'<div class="li"><i>{_h.escape(a)}</i><b>{_h.escape(b)}</b><em>{_h.escape(c)}</em></div>' for a, b, c in el["items"])
            h = f'<div class="list" id="{eid}">{rows}</div>'
            self.A(f'tl.from("{sel} .li",{{x:-120,opacity:0,duration:.3,stagger:{el.get("stagger", .5)},ease:"expo.out"}},{at});')
        elif t == "stamp":
            h = f'<div class="stamp mono" id="{eid}" style="color:{col};border-color:{col}">{_h.escape(el["text"])}</div>'
            self.A(f'tl.from("{sel}",{{scale:2.4,opacity:0,rotation:-10,duration:.4,ease:"expo.out"}},{at});')
        else:
            h = motion.build(self, beat, el, eid, col, at, COL)
            if h is None:
                raise ValueError(f"unknown hud element: {t}")
        if el.get("fx") == "shine":
            h = motion.shine(self, h, eid, at)
        return h

    def build(self) -> str:
        sub = self.spec.get("subscribe", {"title": "SUBSCRIBE", "sub": "for daily shorts"})
        last = max(w["e"] for s in self.tm["segments"] for w in s["words"])
        sub_t = round(last + 0.3, 2)
        brand = _h.escape(self.spec.get("brand", "AGENT SHIFT"))
        tag = _h.escape(self.spec.get("series_label", ""))
        for bi, beat in enumerate(self.spec["beats"]):
            seg = next(s for s in self.tm["segments"] if s["key"] == beat["key"])
            end = self.tm["segments"][bi + 1]["start"] if bi + 1 < len(self.tm["segments"]) else sub_t
            inner = "".join(self.safe_element(beat, el, i) for i, el in enumerate(beat.get("hud", [])))
            dim = '<div class="dim"></div>' if beat.get("dim") else '<div class="scrim"></div>'
            self.html.append(f'<div class="beat" id="b{bi}">{dim}{inner}</div>')
            self.A(f'tl.set("#b{bi}",{{display:"flex"}},{seg["start"]});tl.set("#b{bi}",{{display:"none"}},{round(end, 3)});')
        caps = self.captions()
        card = (f'<div id="card"><div class="logo">A</div><div class="nm">@agentshiftai</div><div class="btn"><span>🔔</span>{_h.escape(sub["title"])}</div>'
                f'<div class="st">{_h.escape(sub["sub"])}</div></div>')
        self.A(f'tl.set("#card",{{display:"flex"}},{sub_t});tl.from("#card",{{scale:.7,opacity:0,duration:.45,ease:"back.out(1.6)"}},{sub_t});'
               f'tl.set(".cg",{{display:"none"}},{sub_t - .05});')
        self.A(f'tl.fromTo("#prog",{{scaleX:0}},{{scaleX:1,duration:{self.total},ease:"none"}},0);')
        return TEMPLATE.replace("@@BRAND@@", brand).replace("@@TAG@@", tag).replace("@@BEATS@@", "".join(self.html)) \
            .replace("@@CAPS@@", caps).replace("@@CARD@@", card).replace("@@JS@@", "\n".join(self.js)) \
            .replace("@@FONTS@@", self.spec.get("gfonts", "Bricolage+Grotesque:opsz,wght@12..96,700;12..96,800")) \
            .replace("@@GSAP@@", (ASSETS / "gsap.min.js").as_uri()).replace("</style>", motion.CSS + "</style>", 1)

    def captions(self) -> str:
        """3-word kinetic caption groups, active word highlighted; pinned bottom:540px (inside the safe zone)."""
        out, gi = [], 0
        hl = {re.sub(r"[^a-z0-9]", "", w.lower()) for w in self.spec.get("highlight", [])}
        for seg in self.tm["segments"]:
            ws = seg["words"]
            groups, cur = [], []
            for w in ws:
                cur.append(w)
                if len(cur) >= 3 or re.search(r"[.,!?;:]$", w["w"]):
                    groups.append(cur); cur = []
            if cur:
                groups.append(cur)
            for g in groups:
                a, b = g[0]["s"], max(x["e"] for x in g) + 0.12
                spans = "".join(f'<span id="w{gi}_{k}" class="{"hl" if re.sub(r"[^a-z0-9]", "", x["w"].lower()) in hl else ""}">{_h.escape(x["w"])}</span> '
                                for k, x in enumerate(g))
                out.append(f'<div class="cg" id="g{gi}">{spans}</div>')
                self.A(f'tl.set("#g{gi}",{{display:"block"}},{a:.3f});tl.set("#g{gi}",{{display:"none"}},{b:.3f});')
                for k, x in enumerate(g):
                    self.A(f'tl.set("#w{gi}_{k}",{{scale:1.07,color:"#ffd84a"}},{x["s"]:.3f});tl.set("#w{gi}_{k}",{{scale:1,color:"#fff"}},{x["e"]:.3f});')
                gi += 1
        return "".join(out)


TEMPLATE = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=1080">
<link href="https://fonts.googleapis.com/css2?family=Anton&family=JetBrains+Mono:wght@500;700&family=@@FONTS@@&display=block" rel="stylesheet">
<script src="@@GSAP@@"></script>
<style>
html,body{margin:0;width:1080px;height:1920px;background:transparent;overflow:hidden;font-family:"Bricolage Grotesque",system-ui,sans-serif;color:#fff}
.mono{font-family:"JetBrains Mono",monospace}
#top{position:absolute;left:60px;right:150px;top:56px;display:flex;justify-content:space-between;font:700 26px "JetBrains Mono",monospace;letter-spacing:.14em;text-shadow:0 2px 12px #000}
#top i{display:inline-block;width:14px;height:14px;border-radius:50%;background:#ff3b5c;margin-right:12px;box-shadow:0 0 14px #ff3b5c}
#prog{position:absolute;left:0;bottom:0;height:8px;width:1080px;transform-origin:0 50%;background:linear-gradient(90deg,#38e1ff,#ffb547,#ff3b5c,#ff4fd8)}
.stage{position:absolute;left:60px;top:150px;width:870px;height:1120px}
.beat{display:none;position:absolute;inset:0;flex-direction:column;align-items:center;text-align:center;padding-top:10px}
.beat>*{flex:none}
.scrim{position:absolute;left:-60px;width:1080px;top:-150px;height:760px;background:linear-gradient(#000000cc,#00000080 55%,transparent);z-index:-1}
.dim{position:absolute;left:-60px;width:1080px;top:-150px;height:1920px;background:#00000085;z-index:-1}
.bub{margin-top:30px;padding:16px 46px 22px;border-radius:44px;background:#fff;color:#111;font-weight:800;font-size:92px;line-height:1;position:relative;box-shadow:0 8px 40px #000a}
.bub span{color:#ff3b5c}.bub:after{content:"";position:absolute;left:90px;bottom:-34px;border:24px solid transparent;border-top:36px solid #fff;border-bottom:0}
.ttl{margin-top:60px;font-weight:800;font-size:104px;line-height:1.03;text-shadow:0 4px 30px #000,0 0 3px #000}.ttl b{color:var(--ac)}
.chip{margin-top:24px;padding:10px 28px;border-radius:999px;border:3px solid;font-size:28px;font-weight:700;letter-spacing:.12em;background:#00000080}
.big{margin-top:46px;font-weight:800;font-size:190px;line-height:1;white-space:nowrap;text-shadow:0 6px 40px #000,0 0 4px #000}
.lab{margin-top:6px;font-weight:800;font-size:72px;text-shadow:0 4px 30px #000}
.sub{margin-top:40px;padding:18px 34px;border-radius:24px;background:#000000a8;border:2px solid #ffffff33;font-size:44px;font-weight:700}.sub b{color:#ffb547}
.rows{margin-top:44px;width:830px;display:flex;flex-direction:column;gap:18px}
.row{display:flex;align-items:baseline;gap:22px;padding:14px 36px;border-radius:30px;background:#000000b0;border:3px solid}
.row em{font-style:normal;font-size:36px;color:#8b90b8;width:130px;text-align:left}.row b{font-weight:800;font-size:130px;line-height:1.05}.row span{font-size:46px;font-weight:700}
.chain{margin-top:56px;display:flex;align-items:center;gap:8px}
.stp{width:232px;padding:24px 8px;border-radius:28px;background:#000000b8;border:3px solid var(--ac);display:flex;flex-direction:column;align-items:center}
.stp b{font-weight:800;font-size:66px;line-height:1}.stp i{font-style:normal;font-size:30px;font-weight:700;color:var(--ac);margin-top:6px}.arw{font-size:44px;text-shadow:0 2px 12px #000}
.list{margin-top:56px;width:820px;display:flex;flex-direction:column;gap:20px}
.li{display:flex;align-items:center;gap:26px;padding:24px 34px;border-radius:28px;background:#000000b8;border:2px solid #ffb54788}
.li i{font-style:normal;font-size:70px}.li b{font-weight:800;font-size:70px;flex:1;text-align:left}.li em{font-style:normal;font-size:38px;font-weight:700;color:#ffb547}
.stamp{margin-top:70px;padding:12px 34px;border:6px solid;font-size:56px;font-weight:800;letter-spacing:.1em;border-radius:12px;transform:rotate(-4deg);background:#00000070;max-width:800px}
#caps{position:absolute;left:60px;right:150px;bottom:540px;text-align:center;font-family:Anton,sans-serif;font-size:86px;line-height:1.08;text-transform:uppercase;text-shadow:0 4px 18px #000,0 0 4px #000}
.cg{display:none}.cg span{display:inline-block;margin:0 .1em;color:#fff;-webkit-text-stroke:2px #000;paint-order:stroke fill}
#card{display:none;position:absolute;left:60px;width:870px;top:520px;flex-direction:column;align-items:center;padding:50px 20px;border-radius:44px;background:#0b0d14ee;border:2px solid #ffffff22}
#card .logo{width:150px;height:150px;border-radius:50%;background:#c2410c;font:400 90px/150px Anton,sans-serif;text-align:center}
#card .nm{margin-top:24px;font-size:40px;font-weight:700;color:#e7e8ec}
#card .btn{margin-top:36px;padding:24px 56px;border-radius:60px;background:#ff0033;font:400 76px Anton,sans-serif;letter-spacing:.02em}.btn span{font-size:56px;margin-right:16px}
#card .st{margin-top:30px;font-size:50px;font-weight:700;color:#5eead4}
</style></head><body>
<div id="top"><div><i></i>@@BRAND@@</div><div>@@TAG@@</div></div>
<div class="stage">@@BEATS@@</div>
<div id="caps">@@CAPS@@</div>@@CARD@@
<div id="prog"></div>
<script>
const tl = gsap.timeline({paused:true});
@@JS@@
// Fit: no HUD text may run past the 870px stage (x 60-930) into YouTube's right-hand button zone (qa_v2 safe_zone).
// Beats are display:none until their time, so each is shown invisibly, measured and shrunk before the timeline is exposed.
function __fit(){
  const MAX = 870;
  document.querySelectorAll('.beat').forEach(b => {
    const prev = b.style.cssText; b.style.cssText = 'display:flex;visibility:hidden';
    b.querySelectorAll('.big,.ttl,.bub,.lab,.stamp,.kin,.sub,.chip,.rows,.li,.stp').forEach(e => {
      for (let i = 0; i < 6 && e.scrollWidth > MAX; i++) {
        const fs = parseFloat(getComputedStyle(e).fontSize);
        e.style.fontSize = Math.max(28, fs * MAX / e.scrollWidth * 0.96) + 'px';
        e.style.whiteSpace = 'normal'; e.style.maxWidth = MAX + 'px'; e.style.overflowWrap = 'anywhere';
      }
    });
    b.style.cssText = prev;
  });
}
document.fonts.ready.then(() => { try { __fit(); } catch (e) {} window.__timelines = {main: tl}; });
</script></body></html>"""


def write(spec: dict, timing: dict, total: float, out: Path) -> Path:
    out.write_text(Page(spec, timing, total).build(), encoding="utf-8")
    return out
