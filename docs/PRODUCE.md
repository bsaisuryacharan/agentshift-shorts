# One-command production (`app.produce`)

```
python -m app.produce run examples/doomsday.json --out runs/        # full Short, fails closed at QA
python -m app.loop produce --spec examples/doomsday.json              # same, via the main CLI
python -m app.produce qa runs/<id> --vision vision.json               # re-gate after the frame review
```

Stages (timings land in `runs/<id>/manifest.json`): stills check -> voice (parallel edge-tts, per-word timing) -> mix
(bed ducked under voice, synthetic SFX, -14 LUFS) -> HUD page -> overlay PNGs (15 fps, 3 pages) -> cinematic composite
(all cores, streamed to ffmpeg) -> `qa_v2` gate.

**Stills are the one human/agent step.** Put 9:16 photoreal, text-free images in `runs/<id>/img/` (Higgsfield
`gpt_image_2_5`, 0.25 credit each). A missing still stops the run and lists the prompts to generate. Every beat/cut in the spec
names its `img`; give it a `prompt` so the stop message is actionable.

**Vision gate.** `qa_v2` fails without a frame-based review. Open `runs/<id>/sheet.jpg`, score it with
`qa_v2.VISION_RUBRIC`, save `vision.json`, re-run `qa`. Approve only if all scores >= 7 and visual_variety >= 8.
For high-stakes uploads use a reviewer that did not make the video.

**Safe zones** (enforced by `qa_v2.safe_zone_overlay`): nothing bright in the bottom 500 px or right 140 px; captions
sit at `bottom:540px; right:150px`; content column x 60-930.

Spec reference: `examples/doomsday.json` (beats: `key,img,focal,zoom,say,sfx,hud[],cuts[],vfx[]`).
Measured on 2 cores, 42 s Short: ~310 s end to end (overlay ~97 s, composite ~170 s, QA ~42 s).
