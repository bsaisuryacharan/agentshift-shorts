# The Shorts Factory — operating system

A source-backed, deterministic, self-correcting pipeline that turns a verified research
file into a 1080×1920 HyperFrames short. The LLM writes **content**; Python and the
HyperFrames compiler own **structure**. That split is the safety property: a weak or
hallucinating model cannot break the frame contract, and a broken template cannot
invent facts.

```
research.json ──plan──▶ spec.json ──build──▶ SCRIPT + STORYBOARD + frames
                         │
                         ├─ audio (Kokoro)  ─▶ audio_meta.json
                         ├─ captions        ─▶ compositions/captions.html
                         ├─ assemble        ─▶ index.html
                         ├─ lint + check    ─▶ errors block, warnings inform
                         ├─ render          ─▶ renders/*.mp4
                         ├─ loudnorm        ─▶ -14 LUFS
                         ├─ gate            ─▶ qa.json
                         ├─ observe         ─▶ observer_report.json + contact sheet
                         ├─ diagnose        ─▶ findings
                         ├─ correct (≤N)    ─▶ re-render
                         └─ learn           ─▶ creative_learning.json + docs/LESSONS.md
```

## Commands

```bash
# 1. Verified research (sources + claims). The loop refuses to plan without it.
videos/<id>/research.json

# 2. Spec from research (free-first LLM ladder, fails closed)
python -m app.loop plan --video-id <id> --topic "..." --research videos/<id>/research.json

# 3. Produce, score, correct, learn
python -m app.loop run --video-id <id> --max-attempts 3

# 4. Re-score an existing render without rebuilding
python -m app.loop observe --video-id <id>
```

Exit codes: `0` passed, `2` escalated (read `videos/<id>/ESCALATION.md`).

## What "perfect" means

A run ships only when **all** of these are true:

| Check | Threshold | Evidence |
|---|---|---|
| duration | 20–60 s | `ffprobe` |
| resolution | exactly 1080×1920 | `ffprobe` |
| audio | stream exists | `ffprobe` |
| size | < 49 MB | filesystem |
| citations | every claim has `source_ids` | spec |
| originality | < 60% word overlap with prior scripts | SCRIPT.md corpus |
| freeze | no frozen stretch > 0.5 s | `freezedetect` |
| loudness | −16.5 … −11.5 LUFS | `ebur128` |
| silence | no continuous gap ≥ 1.2 s | `silencedetect` |
| frames | 0 lint errors, 0 check errors | `hyperframes lint/check` |
| visual | vision score ≥ 6 when a VL model is available | contact sheet |

Warnings are allowed and recorded; errors are not. `container_overflow` on decorative
layers is a warning on purpose — the composition clips it.

### Good vs. not good (by example)

**Good hook** — specific, falsifiable, creates a gap the viewer wants closed:
> "You are standing still, and you are moving faster than a rifle bullet."

**Not good** — generic, no stake, no number:
> "Space is really interesting. Let's learn some facts."

**Good stat beat** — one number, one comparison, one consequence:
> 1,670 km/h · *"That is a commercial jet, multiplied by two."*

**Not good** — three numbers in one beat; the viewer reads nothing and remembers nothing:
> "1,670 km/h, 465 m/s, and 40,075 km circumference."

**Good close** — reframes what the viewer already knew, loops back to the hook:
> "The trick is not that the planet is still. The trick is that you are moving with it."

**Not good** — a summary or a CTA stuffed into the last frame:
> "Thanks for watching, like and subscribe for more science facts."

**Good caption group** — 3–5 words, ends on a content word, may split a sentence:
> `the surface travels at` / `1670 km per hour.`

**Not good** — single words or dangling conjunctions (fixed by the function-word rule in
`captions.mjs`):
> `and` / `because` / `the`

**Good visual** — one instrument per beat that proves the sentence (rings for orbit,
gauge for speed, bars for comparison). **Not good** — decoration that could belong to any
beat, or a second focal point competing with the headline.

## Where the design lives

* `app/frames.py` — the frame contract. Every frame is a `<template>` with
  `#root[data-composition-id]`, one GSAP timeline in `window.__timelines`, `tl.seek(0)`.
  Layout: 88 px side margins, copy above y≈1400, caption band 1428–1772, type floor 28 px.
  Animations are property-disjoint: one `fromTo` per element per property. CSS animations
  are paused by the capture engine, so ambience is GSAP-driven (grain shimmer).
* `templates/project/` — fonts (Anton / Inter / JetBrains Mono), caption skin, project
  manifest. Copied into every video so CI has no external font dependency.
* `vendor/faceless-explainer/scripts/` — audio, captions, assembly, transitions. Vendored
  and pinned so the cloud run does not depend on a personal skills directory.

## Free-model ladder

`app/llm.py` tries providers in order and records every attempt in `logs/llm_usage.jsonl`:

1. **opencode Zen** — OpenAI-compatible: `https://opencode.ai/inference/openai/v1`,
   `OPENCODE_API_KEY`, models `OPENCODE_TEXT` (default `deepseek-v4.1-flash-free`) and
   `OPENCODE_VISION` (default `nemotron-3.5-super-vl-free`). Verified zero-cost ids include
   `glm-5.3-flash-free`, `qwen3.6-plus-free`, `deepseek-v4-flash-free`,
   `longcat-2.5-preview-free`, `minimax-m3.1-flash-free`, `ling-3.1-flash-free`.
2. **OpenRouter** free ids, e.g. `nvidia/nemotron-3-super-120b-a12b:free`.
3. **Groq** `openai/gpt-oss-120b`.
4. **Gemini** `gemini-2.5-flash` (last resort; quota-limited).

Failover is per call, so a 429 from one provider does not fail the run. Vision review is
cached by contact-sheet hash in `data/vision_cache/` to avoid burning free quota on
re-renders that did not change the picture. No provider key means the visual critic is
skipped, not faked.

## Correction policy

Bounded and deterministic. The loop never "just tries again" with the same inputs.

| Finding | Automatic correction | Escalates when |
|---|---|---|
| freeze / low visual richness | additive scene drift (`SCENE-DRIFT`) on every frame | still < 6 after N attempts |
| loudness out of range | `loudnorm I=-14 TP=-1.5` | re-measure still out of band |
| script too short | refused at build time with the measured seconds | always (needs more words) |
| lint / check error | none — templates are code | always, with the exact error |
| silence ≥ 1.2 s | none (padding with silence is banned) | always |
| citation / originality / resolution | none | always |

Escalation writes `ESCALATION.md` with the metrics, the contact sheet path, and three
questions a human or coding agent must answer. That file is the handoff contract.

## Cloud shape

GitHub Actions is the worker (Chromium + ffmpeg, no GPU); Cloudflare Workers cannot render
HyperFrames. `.github/workflows/short.yml` runs plan → build → render → gate → upload on
`workflow_dispatch` or a nightly cron. Artifacts: the mp4, `qa.json`,
`observer_report.json`, `report.md`. Secrets: the provider keys only; no repository
credentials are needed at runtime.

Costs: GitHub Actions minutes, Kokoro TTS download, free LLM quota. No paid API is on the
critical path.

## Learning loop

Each attempt appends to `data/creative_learning.json` (`loop_runs`, capped at 200) and to
`docs/LESSONS.md`: duration, size, freezes, scene changes, LUFS, vision scores, findings,
and the beat shape. Those records are the training signal for the next prompt revision —
read them before changing `app/frames.py` or the planner instruction.
