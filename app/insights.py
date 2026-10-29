"""Compact, committed insights the cloud pipeline can read (the raw trend/analytics reports only exist on the owner's Mac).

    python -m app.insights          # rebuild assets/insights.json from data/latest_*.json, then run deploy/sync_repo.py

auto.pick_topic and auto.write_spec read it via load(); it is advisory text for the LLM, never a source of facts for a script.
"""
from __future__ import annotations

import collections
import json
import re
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "insights.json"


NICHE = re.compile(r"\b(?:scien|space|nasa|esa\b|planet|moon|mars\b|solar|star\b|stars\b|galax|universe|black hole|telescope|rocket|satellite|orbit|astronaut|physic|quantum|chemi|biolog|"
                   r"animal|nature|ocean|climate|earth\b|volcan|earthquake|dinosaur|fossil|species|brain|psycholog|histor|ancient|empire|archaeolog|discover|experiment|"
                   r"robot|artificial intelligence|\bai\b|computer|chip|semiconductor|internet|engineer|invent|technolog|\btech\b|nuclear|energy|battery|laser|submarine|"
                   r"aircraft|jet\b|train|bridge|skyscraper|mystery|unsolved|explained|how .{2,30} works?)", re.I)
# channel direction (owner, 2026-10-29): curiosity explainers - science, space, nature, history, tech and engineering - plus big tech news explained.
# Shopping content (reviews, deals, unboxings, tutorials for products) is never in scope; the channel's own results decide the weighting (app/picker.py).
OFF_NEWS = re.compile(r"\b(?:dementia|cancer|diabet|vaccin|drug|overdose|psychedelic|mushroom|cannabis|aspirin|dose|disease|patients?|clinical|"
                      r"killed|dead|deaths?|died|shooting|war\b|attack|crash|murder|election|president|trump|biden|congress|senat|lawsuit|sued)\b", re.I)
JUNK_WINNER = re.compile(r"(?:\bep\.?\s*\d|episode|part\s*\d|compilation|moments|#hindi|#tamil|#telugu|\bbhai\b|\bkya\b|\baur\b|nges|lele|belut)", re.I)


def good_winner(title: str) -> bool:
    """a niche 'winner' worth learning from: English, a single idea (not a compilation or an episode series)"""
    return _ascii_ratio(title) > 0.9 and not JUNK_WINNER.search(title) and bool(re.search(r"[a-z]{3,}", title.lower()))


def _ascii_ratio(s: str) -> float:
    return sum(c.isascii() for c in s) / max(len(s), 1)


def build(data: Path = ROOT / "data") -> dict:
    out: dict = {"generated_at": datetime.now(UTC).isoformat(timespec="seconds"), "channel": {}, "trending": []}
    ca = data / "latest_channel_analytics.json"
    if ca.exists():
        c = json.loads(ca.read_text())
        cur = (c.get("current_period") or {}).get("summary") or {}
        if c.get("status") == "ok" and cur:
            out["channel"] = {"period": f"{c['current_period']['start']}..{c['current_period']['end']}",
                              "views": cur.get("views"), "avg_view_seconds": cur.get("averageViewDuration"), "avg_view_pct": cur.get("averageViewPercentage"),
                              "net_subscribers": cur.get("netSubscribers"), "likes": cur.get("likes"), "shares": cur.get("shares"),
                              "caveat": "all Shorts on the channel, last 30 days"}
    # what the pipeline itself has learned: every delivered Short's judge scores live in the ledger the cloud commits daily
    hist = data / "history.jsonl"
    if hist.exists():
        rows = []
        for line in hist.read_text().splitlines()[-60:]:
            try:
                h = json.loads(line)
            except ValueError:
                continue
            sc = h.get("scores") or {}
            if sc:
                rows.append({"title": h.get("title", "")[:80], "avg": round(sum(sc.values()) / len(sc), 1), "weakest": min(sc, key=sc.get)})
        if rows:
            rows.sort(key=lambda r: -r["avg"])
            weak = collections.Counter(r["weakest"] for r in rows).most_common(3)
            out["learned"] = {"shorts_scored": len(rows), "best": rows[:3], "worst": rows[-3:][::-1] if len(rows) > 3 else [],
                              "weakest_dimensions": [w for w, _ in weak]}
    sc = data / "scorecards.jsonl"                    # per-stage grades of every Short the pipeline has judged
    if sc.exists():
        stage_scores: dict[str, list[float]] = {}
        for line in sc.read_text().splitlines()[-40:]:
            try:
                for k, v in json.loads(line).get("stages", {}).items():
                    stage_scores.setdefault(k, []).append(v["score"])
            except (ValueError, KeyError):
                continue
        if stage_scores:
            avg = {k: round(sum(v) / len(v), 1) for k, v in stage_scores.items()}
            out["stage_averages"] = avg
            out["weakest_stage"] = min(avg, key=avg.get)
    tr = data / "latest_trend_report.json"
    if tr.exists():
        t = json.loads(tr.read_text())
        rows = [s for s in t.get("signals", []) if s.get("title") and _ascii_ratio(s["title"]) > 0.9]
        rows.sort(key=lambda s: -(s.get("metric") or 0))
        out["region"] = t.get("region")
        out["trend_signals_total"] = len(t.get("signals", []))
        out["trend_signals_on_niche"] = sum(1 for s in rows if NICHE.search(s["title"]))
        rows = [s for s in rows if NICHE.search(s["title"])]                  # phone reviews and celebrity clips are popular but are not this channel
        news = [s for s in t.get("signals", []) if s.get("source") in ("news", "nasa", "science_feed") and s.get("title") and _ascii_ratio(s["title"]) > 0.9
                and not OFF_NEWS.search(s["title"])]                       # medical, drug, tragedy and political headlines are never Shorts for this channel
        yt = [s for s in t.get("signals", []) if s.get("format") == "niche_short" and s.get("title") and good_winner(s["title"])]
        out["niche_winners"] = [{"title": s["title"][:90], "views": s.get("metric"), "url": s.get("url")} for s in yt[:8]]
        out["news"] = [re.sub(r"\s+[-|]\s+[^-|]{3,60}$", "", s["title"]).strip()[:110] for s in news[:12]]      # drop the " - Publisher" tail
        out["trending"] = [re.sub(r"#\w+", "", s["title"]).strip(" |-!") for s in rows[:12]]
    return out


def load() -> dict:
    try:
        return json.loads(OUT.read_text())
    except (OSError, ValueError):
        return {}


def hint(max_chars: int = 1500) -> str:
    """one advisory paragraph for the LLM prompts ('' when there is nothing)"""
    i = load()
    parts = []
    c = i.get("channel") or {}
    if c.get("avg_view_pct") is not None:
        parts.append(f"Channel Shorts ({c['period']}, {c['caveat']}): {c['views']:.0f} views, average viewed {c['avg_view_pct']:.0f}% "
                     f"({c['avg_view_seconds']:.0f}s), {c['net_subscribers']:.0f} net subs. Keep hooks fast and Shorts tight.")
    l = i.get("learned") or {}
    if l.get("shorts_scored"):
        parts.append(f"Judge history over {l['shorts_scored']} Shorts: strongest were " + "; ".join(f"'{r['title']}' ({r['avg']})" for r in l["best"]) +
                     (". Weakest were " + "; ".join(f"'{r['title']}' ({r['avg']})" for r in l["worst"]) if l.get("worst") else "") +
                     f". Dimensions that fail most: {', '.join(l['weakest_dimensions'])} - choose topics and angles that avoid those weaknesses.")
    perf = i.get("performance") or {}
    if perf.get("shorts"):
        y = perf.get("ypp", {}).get("tier2_ads", {})
        parts.append(f"TARGET {perf['target_views_per_short']:,} views per Short. {len(perf['shorts'])} Short(s) tracked: {perf['on_track']} on track, {perf['behind']} behind"
                     + (f", best '{perf['best']['title'][:50]}' with {perf['best']['views']:,} views" if perf.get("best") else "")
                     + f". Monetisation progress: {y.get('subs_pct', 0)}% of 1,000 subscribers, {y.get('views_pct', 0)}% of 10M Shorts views in 90 days.")
    if perf.get("lessons"):
        parts.append("Lessons from results so far: " + " | ".join(perf["lessons"]))
    if i.get("weakest_stage"):
        parts.append(f"Across recent Shorts the weakest stage is '{i['weakest_stage']}' (average {i['stage_averages'][i['weakest_stage']]}): put extra care there.")
    if i.get("niche_winners"):
        parts.append("Short videos winning in this niche in the last two weeks (study the hook, never copy): " + "; ".join(f"'{w['title'][:60]}' ({w['views']:,} views)" for w in i["niche_winners"][:4]))
    if i.get("trending") and not i.get("niche_winners"):
        parts.append("Popular on YouTube now (inspiration only, do not copy titles): " + "; ".join(i["trending"][:6]))
    from . import ideabank, vidiq                         # vidIQ snapshot and the idea bank: own budgets so they never crowd out the channel's own results
    return " ".join([" ".join(parts)[:max_chars], vidiq.hint(), ideabank.hint()]).strip()


if __name__ == "__main__":
    d = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(d, indent=1, ensure_ascii=False))
    print("wrote", OUT, "-", hint()[:200])
