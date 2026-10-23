---
name: shorts-render
description: Render the overlay and composite the final MP4 with app.cinematic. Use after stills + voice exist.
---
1. TTS with word timestamps → `timing.json`; mix bed (duck −12 dB) + whoosh/impact/ding → `mix.wav`.
2. Build the HUD page (transparent background, `window.__timelines.main` paused GSAP timeline). Captions `bottom:540px; left:60px; right:150px`. Add subscribe card 2.2 s after the last word.
3. `python -m app.overlay page.html <total> work/ovl` → PNG per frame.
4. `python -m app.cinematic test shotlist.json 60,150,…` → review stills at every transition and peak; fix before the full render.
5. `python -m app.cinematic render shotlist.json out.mp4` (loudnorm −14 included).
