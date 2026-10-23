# Tool registry — what the system may use, cost, and when

| Stage | Tool | Cost | Use | Notes |
|---|---|---|---|---|
| Trends | YouTube Data API (`mostPopular`), Google News RSS, NASA APIs | free | topic candidates | already in `app/trends.py` |
| Trends (outliers) | **vidIQ** (`outliers`, `trending_videos`, `keyword_research`) | credits | packaging + "what is breaking out" | **cache first** (`store.py find/top`); state credit cost; save every paid result; running tally in replies |
| Own analytics | YouTube Analytics API (read-only OAuth) | free | retention/avg-viewed baseline | `app/analytics.py` |
| Writing | LLM ladder: opencode Zen free → OpenRouter free → Groq → Gemini | free | script, spec, fact ledger | per-call failover, `logs/llm_usage.jsonl` |
| Voice | edge-tts (`en-US-AndrewNeural` / `AvaMultilingual`), Kokoro fallback | free | narration + **word timestamps** | rate +10 %; never even-split captions |
| Stills (best) | **Higgsfield** `gpt_image_2_5` 9:16 | 0.25 cr/image | one photoreal frame per beat (8–10 / Short ≈ 2–2.5 cr) | check `balance` first; `generate_image_batch`, resubmit on 429 |
| Stills (free) | Cloudflare Workers AI FLUX | free tier ≈130 img/day | fallback / volume | same prompt template |
| Motion (optional) | Higgsfield video (MiniMax H3 4 s ≈ 8 cr; Seedance 5 s ≈ 35 cr) | credits | hook or climax only | **ask first**; free VFX covers most needs |
| Compositing | `app/cinematic.py` (OpenCV + NumPy + ffmpeg) | free | push-ins, portals, particles, grain, loudnorm | CPU only, ~5 min / 45 s Short |
| HUD overlay | HTML + GSAP rendered by `app/overlay.py` (Playwright/Chromium) or HyperFrames | free | numbers, chips, captions, subscribe card | transparent PNG per frame |
| Audio finishing | ffmpeg `loudnorm`, bed + sidechain duck, synth SFX | free | −14 LUFS | |
| QA | `app/qa_v2.py` + frame-based vision review | free | hard gate | vision review required |
| Delivery | Telegram Bot (review-first) | free | human glance before publish | `PUBLISH_MODE=review` |
| Publish | YouTube Data API `videos.insert` | free | `schedule` mode after audit | unaudited API projects upload as **private** until Google's audit passes |

## Budget rules
- Typical Short: **≈ 2.5 Higgsfield credits** (stills) + 0 for everything else.
- Never spend paid credits without checking cache/balance; never loop paid calls on failure.
- Every paid call → saved to the local store and appended to the reply's running tally.
