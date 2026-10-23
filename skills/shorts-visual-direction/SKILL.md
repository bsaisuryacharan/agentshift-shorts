---
name: shorts-visual-direction
description: Turn a script into a cinematic shot list and generate/choose the stills. Use after the script is approved.
---
1. Read docs/STYLE_BIBLE.md. One dominant hue + one accent per video.
2. For each beat write a prompt: subject, camera, lighting, mood, "9:16 vertical, photoreal, no text, no logos". Keep the subject in the upper 60 % (the lower 500 px is covered by YouTube UI).
3. Generate with Higgsfield `gpt_image_2_5` (0.25 cr each, batch; resubmit on 429) or Cloudflare FLUX. Check `balance` first.
4. VIEW every image. Reject: artefacts, text/gibberish, clip-art look, subject low in frame. Max 2 regenerations per shot.
5. Write `shotlist.json` (see examples/shotlist.example.json): img, start (from word timing), focal point, zoom 1.25–1.5, flash 0.12 (0.55 on the impact cut), optional bursts.
