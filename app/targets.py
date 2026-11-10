"""What the channel is steering towards, and how far each Short and the channel are from it.

TARGET is the owner's goal (views per Short). Views cannot be commanded, so the system tracks the thing it can influence (quality per stage, retention,
shares) against the thing it wants (views, then YouTube Partner Programme eligibility) and adjusts the next Shorts.

CURVE is an ASSUMPTION, not a measurement: the share of a Short's first-30-day views usually reached by a given age. It is only used to say "on track /
behind / far behind" early, before the final number exists; real data from data/performance.jsonl replaces it as the channel gathers history.
"""
from __future__ import annotations

TARGET = {"views_per_short": 1_000_000}
# the owner's monthly goal (set 2026-10-30): 1,000,000 channel views within one month. app/strategy.py turns it into a daily plan.
MONTH_GOAL = {"views": 1_000_000, "start": "2026-10-30", "deadline": "2026-11-29"}

# YouTube Partner Programme (as published by YouTube, 2025): both tiers need these public-upload/subscriber levels
YPP = {
    "tier1_fan_funding": {"subscribers": 500, "public_uploads_90d": 3, "or": {"public_watch_hours_365d": 3000, "shorts_views_90d": 3_000_000}},
    "tier2_ads": {"subscribers": 1000, "or": {"public_watch_hours_365d": 4000, "shorts_views_90d": 10_000_000}},
}

CURVE = [(1, 0.03), (6, 0.12), (24, 0.35), (72, 0.60), (168, 0.80), (720, 1.0)]       # (hours since publish, share of 30-day views)


def expected_share(age_h: float) -> float:
    """linear interpolation of CURVE"""
    if age_h <= 0:
        return 0.0
    prev_h, prev_s = 0.0, 0.0
    for h, s in CURVE:
        if age_h <= h:
            return prev_s + (s - prev_s) * (age_h - prev_h) / (h - prev_h)
        prev_h, prev_s = h, s
    return 1.0


def status(views: int, age_h: float, target: int | None = None) -> dict:
    """where one Short stands against the target at this age"""
    target = target or TARGET["views_per_short"]
    exp = target * expected_share(age_h)
    ratio = views / exp if exp > 0 else 0.0
    label = "on_track" if ratio >= 0.8 else "behind" if ratio >= 0.25 else "far_behind"
    if age_h < 1:
        label = "too_early"
    return {"views": views, "age_h": round(age_h, 1), "expected": int(exp), "ratio": round(ratio, 3), "status": label,
            "projected_30d": int(views / expected_share(age_h)) if expected_share(age_h) > 0.02 else None}


def ypp_progress(subscribers: int, shorts_views_90d: int, public_uploads_90d: int) -> dict:
    t1, t2 = YPP["tier1_fan_funding"], YPP["tier2_ads"]
    return {
        "subscribers": subscribers, "shorts_views_90d": shorts_views_90d, "public_uploads_90d": public_uploads_90d,
        "tier1_fan_funding": {"subs_ok": subscribers >= t1["subscribers"], "uploads_ok": public_uploads_90d >= t1["public_uploads_90d"],
                              "views_ok": shorts_views_90d >= t1["or"]["shorts_views_90d"], "views_pct": round(100 * shorts_views_90d / t1["or"]["shorts_views_90d"], 1)},
        "tier2_ads": {"subs_ok": subscribers >= t2["subscribers"], "views_ok": shorts_views_90d >= t2["or"]["shorts_views_90d"],
                      "subs_pct": round(100 * subscribers / t2["subscribers"], 1), "views_pct": round(100 * shorts_views_90d / t2["or"]["shorts_views_90d"], 1)},
    }


# ---- relative scoring (audit 2026-11-10) -------------------------------------------------------------------------------------------------------------------------
# Against a 1,000,000-per-Short curve every Short on a 17-subscriber channel is "far_behind" with ratio 0.000, so the loop gets no gradient. What it needs is
# "better or worse than this channel's own typical Short at the same age", which is what relative() says.
LADDER = [   # proposed step goals for the next 30 days instead of one 1M number (owner can edit); each step is measured by app.strategy
    {"name": "typical Short", "metric": "median views per Short at 7 days", "now_hint": 200, "goal": 1_000},
    {"name": "first breakout", "metric": "one Short above 25,000 views", "goal": 25_000},
    {"name": "audience", "metric": "subscribers", "goal": 100},
    {"name": "volume", "metric": "channel views in 30 days", "goal": 100_000},
]


def cohort_stats(shorts: list[dict]) -> dict:
    """median and spread of the channel's own Shorts that are old enough (>= 72 h) to have most of their views"""
    import statistics
    old = [s["views"] for s in shorts if s.get("age_h", 0) >= 72 and s.get("views") is not None]
    if not old:
        return {"n": 0, "median": None, "p75": None}
    old.sort()
    return {"n": len(old), "median": statistics.median(old), "p75": old[int(0.75 * (len(old) - 1))]}


def relative(views: int, age_h: float, cohort: dict) -> str:
    """breakout / above / typical / below / too_early, against the channel's own cohort (age-adjusted with CURVE)"""
    if age_h < 6:
        return "too_early"
    med = cohort.get("median")
    if not med:
        return "unknown"
    share = max(expected_share(age_h), 0.05)
    projected = views / share if age_h < 720 else views
    if projected >= 5 * med:
        return "breakout"
    if projected >= 1.5 * med:
        return "above"
    if projected >= 0.5 * med:
        return "typical"
    return "below"
