"""One command, one Short:  spec.json -> voice -> mix -> HUD -> cinematic render -> QA -> manifest.

    python -m app.produce run  spec.json --out runs/           # full production (fails closed at QA)
    python -m app.produce qa   runs/<id> [--vision vision.json]   # re-gate / add the frame-based review

Speed design (measured on a 2-core cloud box, 45 s Short): voice synthesised per beat concurrently; HUD rendered at 15 fps on
3 concurrent browser pages; frames composited on every core with INTER_LINEAR and streamed straight into ffmpeg (no temp
frames on disk). Each stage's wall time is recorded in manifest.json so regressions are visible.
Spec format: see examples/doomsday.json.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

from . import cinematic, footage, hud, motionbank, overlay, qa_v2, stills, voice

TAIL_S = 2.2  # end-card time after the last spoken word


def _timed(m: dict, name: str, t0: float) -> float:
    m["stages"][name] = round(time.time() - t0, 1)
    print(f"  {name:<10} {m['stages'][name]:>6.1f}s", flush=True)
    return time.time()


def shotlist(spec: dict, timing: dict, total: float, vids: dict | None = None) -> dict:
    shots, flip = [], 1
    seg = {s["key"]: s for s in timing["segments"]}
    fxs = motionbank.pick(spec)
    for b, fx in zip(spec["beats"], fxs):
        start = seg[b["key"]]["start"] if shots else 0.0
        items = [(start, b)]
        for c in b.get("cuts", []):
            items.append((voice.word_time(timing, b["key"], c["at"], c.get("nth", 0)) - 0.05, c))
        for t, s in items:
            shots.append({"img": f"img/{s['img']}", "start": round(t, 3), "focal": s.get("focal", [0.5, 0.52]),
                          "zoom": s.get("zoom", 1.32), "rot": s.get("rot", 0.7 * flip), "flash": s.get("flash", 0.12), "fx": fx}
                         | ({"video": vids[b["key"]], "zoom": 1.08} if vids and s is b and b["key"] in vids else {}))
            flip = -flip
    bursts = []
    for b in spec["beats"]:
        for v in b.get("vfx", []):
            bursts.append({"t": voice.word_time(timing, b["key"], v["at"], v.get("nth", 0)), "x": v.get("x", .5), "y": v.get("y", .5),
                           "n": v.get("n", 220), "speed": v.get("speed", 1000), "life": v.get("life", [0.8, 1.6])})
    return {"total": round(total, 3), "audio": "mix.wav", "overlay_dir": "ovl", "overlay_step": 2, "shots": shots, "bursts": bursts,
            "theme": spec.get("theme")}


def onscreen_text(spec: dict) -> str:
    out = []
    for b in spec["beats"]:
        for el in b.get("hud", []):
            for k in ("text", "html"):
                if k in el:
                    out.append(el[k])
            for row in el.get("items", []) + el.get("steps", []):
                out.append(" ".join(map(str, row)))
    return "\n".join(out)


def run(spec_path: Path, out_root: Path, workers: int | None = None) -> dict:
    spec = json.loads(spec_path.read_text())
    run_dir = out_root / spec["id"]
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "spec.json").write_text(json.dumps(spec, indent=1, ensure_ascii=False))
    m: dict = {"id": spec["id"], "stages": {}}
    t0 = T = time.time()
    print(f"[{spec['id']}] producing", flush=True)

    stills.ensure(spec, run_dir); t0 = _timed(m, "stills", t0)
    # beats whose still is only a texture (free image quota gone) get real footage as their picture instead
    need = {b["key"]: stills.keywords(stills.TEXTURED_FILES[b["img"]], 3) for b in spec["beats"] if b.get("img") in stills.TEXTURED_FILES}
    vids = footage.ensure(spec, run_dir, need); t0 = _timed(m, "footage", t0)
    timing = asyncio.run(voice.synth(spec, run_dir)); t0 = _timed(m, "voice", t0)
    last = max(w["e"] for s in timing["segments"] for w in s["words"])
    total = round(last + TAIL_S, 2)
    voice.mix(spec, timing, run_dir, total); t0 = _timed(m, "mix", t0)
    page = hud.write(spec, timing, total, run_dir / "page.html"); t0 = _timed(m, "hud", t0)
    sl = shotlist(spec, timing, total, vids)
    (run_dir / "shotlist.json").write_text(json.dumps(sl, indent=1))
    asyncio.run(overlay.render(page, total, run_dir / "ovl", step=2, pages=3)); t0 = _timed(m, "overlay", t0)
    final = run_dir / "final.mp4"
    cinematic.Cinematic(sl, run_dir).encode(final, run_dir / "mix.wav", workers); t0 = _timed(m, "composite", t0)
    (run_dir / "onscreen.txt").write_text(onscreen_text(spec))
    qa_v2.contact_sheet(final, run_dir / "sheet.jpg")
    res = qa_v2.evaluate(final, run_dir / "ovl", onscreen_text(spec), None, None)
    (run_dir / "qa.json").write_text(json.dumps(res, indent=1, ensure_ascii=False))
    _timed(m, "qa", t0)
    m.update({"total_s": round(time.time() - T, 1), "video_s": total, "qa_passed": res["passed"], "checks": res["checks"],
              "next": "view sheet.jpg, score with qa_v2.VISION_RUBRIC -> vision.json, then: python -m app.produce qa <run> --vision vision.json"})
    (run_dir / "manifest.json").write_text(json.dumps(m, indent=1, ensure_ascii=False))
    print(f"  TOTAL      {m['total_s']:>6.1f}s for a {total:.0f}s Short")
    return m


def regate(run_dir: Path, vision: Path | None) -> dict:
    v = json.loads(vision.read_text()) if vision else None
    res = qa_v2.evaluate(run_dir / "final.mp4", run_dir / "ovl", (run_dir / "onscreen.txt").read_text(), None, v)
    (run_dir / "qa.json").write_text(json.dumps(res, indent=1, ensure_ascii=False))
    return res


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[0] == "run":
        r = run(Path(a[1]), Path(a[a.index("--out") + 1]) if "--out" in a else Path("runs"))
        print(json.dumps(r["checks"], indent=1, ensure_ascii=False))
    else:
        r = regate(Path(a[1]), Path(a[a.index("--vision") + 1]) if "--vision" in a else None)
        print(json.dumps(r, indent=1, ensure_ascii=False))
        raise SystemExit(0 if r["passed"] else 2)
