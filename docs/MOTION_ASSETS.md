# Motion assets (helper visuals)

Stills with a push-in read as a slideshow. The compositor now adds **moving layers** so a Short has a video feel without a
video-generation model:

| layer | what | where | cost |
|---|---|---|---|
| motion bank | text-free looping light/colour fields blended over the still | `assets/motion/*.mp4` (31 clips, 2.6 MB) | none |
| NASA footage | real cutaway clip replaces a beat's still (max 2 per Short, space/Earth/science beats) | fetched at render time (`app/footage.py`) | none, no key |

## Motion bank (curated from the HyperFrames "Make" catalog)
Source: `~/Library/Application Support/HyperFrames/catalog.json` — 448 registry items (210 blocks, 238 components); 215 list a preview clip, 144
were downloadable (the other 67 return HTTP 403 and were skipped). All 144 were reviewed on contact sheets. Kept only clips with **no baked-in
text or brand**, centre-cropped to 9:16, 540x960, 15 fps, no audio (`scripts/curate_motion.py`). Metadata for all 448 items is in
`assets/motion/catalog_all.json`; per-clip role/mood/blend in `assets/motion/manifest.json`.

Roles: **ambient** (full-frame light on black, screen-blended: aurora, godrays, frost-sequence-camera-orbit = drifting debris, lens-flare),
**wash** (colour/texture overlay: blob, mesh-gradient, flowing-gradient, plasma, swirl, fractal-noise), **object** (centred orbs/waveforms/
glass: kept for accents, never overlaid because they read as stickers on a photo).
Rejected as templates with baked-in text/UI/brands: captions, phone/app mock-ups, maps, transitions demos, HeyGen promos.

Selection (`app/motionbank.pick`): a beat can set `"motion": "godrays"`, `"motion": false`, or `"mood": "space"`; otherwise the mood is
inferred from the beat text/title (space, danger, data, tech, calm, warm). Never the same clip twice in a row, at most 5 distinct clips per
Short, `dim` beats are left clean, the light is calmer under the caption/UI zone.

## NASA footage
`"footage": "<2-3 nouns, most specific first>"` on a beat. The NASA Image and Video Library API (no key) ANDs words, so `search()` tries the phrase,
word pairs, then single words and ranks by word hits; the first word must be in the title/keywords and multi-word queries need >= 2 hits. A 4.5 s
segment is cut straight from the `~medium.mp4` rendition with ffmpeg (no full download), rejected if dark or frozen. No match -> the still is used.
Credits go to `vid/credits.json` and into the Telegram caption. NASA media is generally public domain; check an item's own page for third-party restrictions.

## More galleries (free licences; verify each site's licence page before use)
Mixkit, Pexels, Pixabay and Coverr advertise free commercial use without attribution (per secondary sources; licence pages not verified here);
Vidsplay asks for a credit link. NASA images.nasa.gov for space footage. None of these need to be in the repo: add a clip to
`scripts/curate_motion.py` KEEP (name -> blend, moods, role) and re-run it.

## Known limits
Ambient clips are only 4; washes are subtle. More ambient fields (smoke, dust, embers, film grain, bokeh) would raise variety most. Footage relevance depends on NASA's
catalogue (good for space/Earth, none for finance/biology), so the judge's frame review is the safety net.
