# Shorts Factory audit — 23 Oct 2026

Evidence, not opinion. Every finding below was measured on your files; fixes ship in this upgrade.

| # | Finding | Evidence | Fix |
|---|---|---|---|
| 1 | **The delivered Short is one picture for 49 s.** | `app/qa_v2.py` on `output/…326c29ce/final.mp4`: **1 distinct shot in 49 s** (a good Short has ≥ 1 per 5–6 s). Contact sheet: same illustration all the way through; only a slow zoom. | `app/cinematic.py` (shot list, push-ins, portal transitions, VFX) + `shots ≥ duration/6` gate |
| 2 | **Audio too quiet and the gate did not know.** | Measured **−22.1 LUFS** (your own SYSTEM.md range is −16.5…−11.5; target −14). `app/qa.py` (v1) never measures loudness — only `loop.py` does, the legacy `main.py` path skips it. | loudnorm −14 LUFS built into `Cinematic.encode`; loudness is a hard gate in `qa_v2` |
| 3 | **The "review" never looks at the video.** | `review.json` gives `visual_quality: 8` from `providers.review_video(settings, script, qa_report)` — inputs are script text and a QA text report. It scored a 1-picture video 8/10. | `qa_v2` refuses to approve without a frame-based review (`contact_sheet` + `VISION_RUBRIC`) |
| 4 | **Fail-open hole.** README says "fails closed", but `docs/LESSONS.md` shows runs marked **PASS with `vision: skipped`** when Groq returned 400 / Gemini 429. A run with no visual review shipped as a pass. | LESSONS.md, 4 of 6 entries | `vision` is a required check; missing review = fail, not skip |
| 5 | **Captions sit under YouTube's UI.** | SYSTEM.md "caption band 1428–1772". YouTube covers the bottom ≈ 500 px (y > 1420) with channel + title, and 140 px at the right with buttons. Captions there are partly hidden. | Captions pinned at `bottom: 540px; right: 150px` (y ≈ 1220–1380); `safe_zone_overlay` gate |
| 6 | **Missing-glyph (tofu) on screen.** | Frame 1 caption reads "what □300 can buy" — the ₹ sign is absent from the caption font (Arial). | `glyph_audit()` gate; ship Noto Sans/Inter with ₹ |
| 7 | **Captions are not synced to speech.** | `render.make_srt` allocates time evenly per line ("Even allocation is conservative"). | Use per-word timestamps (edge-tts `WordBoundary`, or Kokoro + forced alignment) — the HyperFrames path already does; retire the legacy path |
| 8 | **Two pipelines, two truths.** | `app/main.py` + `render.py` + `creative.py` (PIL/ffmpeg, Cloudflare/NASA images, 3 candidates) vs `app/loop.py` + `frames.py` (HyperFrames, Kokoro). README describes the first, SYSTEM.md the second. | One path: `loop.py` for logic, `cinematic.py` for picture. Legacy kept only as fallback |
| 9 | **HyperFrames path is graphics-only.** | LESSONS.md: `visual_richness 4` then `6` (rejected → approved only after changing a sphere's size). No photographic/cinematic imagery anywhere. | Photoreal stills per beat (Higgsfield `gpt_image_2_5` 0.25 cr, or Cloudflare FLUX free) as the background layer; HyperFrames/HTML becomes the HUD overlay |
| 10 | **No sound design, no ending.** | Voice + nothing else; no bed, ducking, SFX, subscribe card, or loop-back. | Bed + ducking + 3 SFX types in the render step; subscribe end card; closing line echoes the hook |
| 11 | **Analytics is a 1-Short sample.** | `latest_channel_analytics.json`: 1 Short row, 5,417 views, avg viewed 62 %, 8 subs. | Don't tune on it yet; use vidIQ outliers for packaging (cache first, see AGENT_INSTRUCTIONS) |

What is already good and kept: source/fact ledger, similarity guard, bounded retry + escalation file, free-LLM ladder, Telegram review-first delivery, hard technical gates, learning log, tests.

## Same gate run on my own ep24 Short (it found two real defects there too)
Before fixes: −19.2 LUFS (too quiet) and a graphic running under the right-hand button column. After fixes: loudness −14.6 and layout moved inside the safe zone. The gate is not a rubber stamp.
