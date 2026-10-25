"""What the channel is steering towards, and how far each Short and the channel are from it.

TARGET is the owner's goal (views per Short). Views cannot be commanded, so the system tracks the thing it can influence (quality per stage, retention,
shares) against the thing it wants (views, then YouTube Partner Programme eligibility) and adjusts the next Shorts.

CURVE is an ASSUMPTION, not a measurement: the share of a Short's first-30-day views usually reached by a given age. It is only used to say "on track /
behind / far behind" early, before the final number exists; real data from data/performance.jsonl replaces it as the channel gathers history.
"""
from __future__ import annotations

TARGET = {"views_per_short": 1_000_000}

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
