"""Test pipeline steps one at a time in the cloud, on several different topics, before running the whole thing.

    python -m app.stagecheck pick 4                    # 4 topic picks: topic, format, real-picture coverage, niche/product checks
    python -m app.stagecheck script 4                  # pick 4 topics, write a script for each: validation, words, beats, real-picture terms
    python -m app.stagecheck pictures 2                # script + stills + footage for 2 topics: where every picture came from (no voice/render/judge)

Every check prints PASS/WARN/FAIL lines and writes out/report.json (uploaded by .github/workflows/stage-check.yml). Nothing is recorded in the
topic ledger and nothing is sent to Telegram.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from . import auto, formats, picker


def _line(ok: bool | None, msg: str) -> str:
    tag = "PASS" if ok else "WARN" if ok is None else "FAIL"
    print(f"  [{tag}] {msg}", flush=True)
    return tag


def check_pick(n: int) -> list[dict]:
    out, seen, recent = [], set(), auto.recent_formats()
    for i in range(n):
        t0 = time.time()
        fmt = formats.choose(recent)
        recent.append(fmt)
        topic, wiki, fmt = auto.pick_topic(fmt=fmt)
        cov = picker.visual_coverage([wiki])
        r = {"topic": topic, "wiki": wiki, "format": fmt, "secs": round(time.time() - t0)}
        print(f"pick {i + 1}: {topic!r} ({wiki}, {fmt})", flush=True)
        r["checks"] = [
            _line(bool(auto.insights.NICHE.search(topic + " " + wiki)), "on-niche (science/space/nature/history)"),
            _line(not picker.PRODUCT.search(topic + " " + wiki), "not a consumer product or AI brand"),
            _line(auto._norm_topic(wiki) not in seen, "different from the other picks"),
            _line(cov >= 0.5 if cov else None, f"real moving pictures for the subject itself: {cov:.0%}"),
        ]
        seen.add(auto._norm_topic(wiki))
        out.append(r)
    return out


def check_script(n: int, keep: Path | None = None) -> list[dict]:
    out = []
    for i, p in enumerate(check_pick(n)):
        t0 = time.time()
        r = {"topic": p["topic"], "wiki": p["wiki"], "format": p["format"]}
        try:
            facts = auto.wiki_facts(p["wiki"])
            spec, writer = auto.write_spec(p["topic"], facts, [], p["format"])
        except Exception as e:
            r["error"] = str(e)[:300]
            _line(False, f"script for {p['wiki']}: {r['error']}")
            out.append(r)
            continue
        beats = spec["beats"]
        words = sum(len(b["say"].split()) for b in beats)
        real = sum(1 for b in beats if b.get("photo") or b.get("footage"))
        hook = beats[0]["say"]
        r.update({"writer": writer, "secs": round(time.time() - t0), "beats": len(beats), "words": words, "real_terms": real,
                  "hf": sum(1 for b in beats for e in b.get("hud", []) if e.get("t") == "hf"), "hook": hook, "title": spec["title"]})
        print(f"script {i + 1}: {spec['title']!r} by {writer}: {len(beats)} beats, {words} words", flush=True)
        r["checks"] = [
            _line(True, "passes validation (numbers in FACTS, screen numbers spoken, 2+ gallery graphics)"),
            _line(real >= len(beats) // 2, f"beats with a real photo/footage term: {real}/{len(beats)}"),
            _line(any(ch.isdigit() for ch in hook) or None, f"hook has a concrete number: {hook!r}"),
            _line(not hook.lower().startswith(("here are", "facts about", "let's", "did you know")), "hook is not a generic opener"),
        ]
        if keep:
            keep.mkdir(parents=True, exist_ok=True)
            spec["_facts"] = facts
            r["spec_path"] = str(keep / f"{spec['id']}.spec.json")
            Path(r["spec_path"]).write_text(json.dumps(spec, ensure_ascii=False, indent=1))
        out.append(r)
    return out


def check_pictures(n: int, work: Path) -> list[dict]:
    from . import footage, stills
    out = []
    for s in check_script(n, keep=work / "specs"):
        if "error" in s:
            out.append(s)
            continue
        spec = json.loads(Path(s["spec_path"]).read_text())
        run = work / spec["id"]
        t0 = time.time()
        stills.TEXTURED.clear()
        stills.TOPIC, stills._TOPIC_USES["n"] = s["wiki"], 0
        stills.ensure(spec, run)
        need = {b["key"]: stills.keywords(stills.TEXTURED_FILES[b["img"]], 3) for b in spec["beats"] if b.get("img") in stills.TEXTURED_FILES}
        vids = footage.ensure(spec, run, need)
        credits = {}
        for cj in (run / "img" / "credits.json", run / "vid" / "credits.json"):
            if cj.exists():
                credits.update(json.loads(cj.read_text()))
        imgs = {b["img"] for b in spec["beats"]}
        real_imgs = sum(1 for i in imgs if any(k.startswith(Path(i).stem) for k in credits))
        textured = sum(1 for i in imgs if i in stills.TEXTURED_FILES)
        ai = len(imgs) - real_imgs - textured
        s.update({"pictures_secs": round(time.time() - t0), "beats": len(spec["beats"]), "footage_beats": len(vids),
                  "real_stills": real_imgs, "ai_stills": ai, "textured": textured, "sources": sorted({v.get("license", "")[:20] for v in credits.values()})})
        print(f"pictures for {spec['title']!r}: {len(vids)} footage beats, {real_imgs} real stills, {ai} AI stills, {textured} placeholders", flush=True)
        s["checks"] = s.get("checks", []) + [
            _line(len(vids) + real_imgs >= len(spec["beats"]) // 2, f"real pictures or footage on at least half the beats ({len(vids) + real_imgs}/{len(spec['beats'])})"),
            _line(textured == 0 or None, f"no placeholder textures ({textured})"),
        ]
        out.append(s)
    return out


def main(argv: list[str]) -> int:
    stage, n = argv[0], int(argv[1]) if len(argv) > 1 else 4
    out = Path(argv[2]) if len(argv) > 2 else Path("stagecheck_out")
    out.mkdir(parents=True, exist_ok=True)
    rows = {"pick": lambda: check_pick(n), "script": lambda: check_script(n), "pictures": lambda: check_pictures(n, out)}[stage]()
    tags = [t for r in rows for t in r.get("checks", [])] + ["FAIL" for r in rows if "error" in r]
    summary = {"stage": stage, "runs": len(rows), "pass": tags.count("PASS"), "warn": tags.count("WARN"), "fail": tags.count("FAIL"), "rows": rows}
    (out / "report.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False))
    print(f"\n{stage}: {summary['pass']} pass, {summary['warn']} warn, {summary['fail']} fail over {len(rows)} runs")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
