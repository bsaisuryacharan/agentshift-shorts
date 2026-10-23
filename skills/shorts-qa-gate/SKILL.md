---
name: shorts-qa-gate
description: Run the hard QA gate and the frame-based vision review; loop on named fixes. Use on every render.
---
1. `python -m app.qa_v2 out.mp4 --overlay work/ovl --text onscreen.txt --font <font.ttf> --sheet work/sheet.jpg`
2. VIEW work/sheet.jpg and score it with `qa_v2.VISION_RUBRIC` (any vision-capable model, or yourself). Save `vision.json`; re-run with `--vision vision.json`.
3. Each failing check names its fix: distinct_shots → add cuts/images; loudness → loudnorm; safe_zone → move element; glyphs → change font; vision fixes → apply verbatim.
4. Max 3 loops; then write ESCALATION.md (metrics, sheet path, three questions). Never ship on a skipped review.
