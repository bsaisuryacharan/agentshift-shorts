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

## NASA clip index (`assets/motion/nasa_index.json`)
1,088 NASA Image and Video Library clips indexed by theme (space 400 / tech 270 / science 270 / earth 200) with title + keywords, built from
80 theme queries against the keyless API; briefings, interviews and talking-head items were dropped by title. Nothing is stored - `app/footage.py`
ranks the index first (no API round trip), falls back to the live API, cuts a 4.5 s segment from the `~medium.mp4` rendition, drops burned-in
subtitles by cropping, rejects dark/frozen clips and asks a vision model to confirm the frame shows the requested subject. Together with the
31 local motion-bank loops the library is ~1,100 clips. When the free image quota is gone, beats whose still is only a texture get one of these
clips as their picture instead (`footage.ensure(need_pictures=...)`, up to 4 per Short).

## Real photos from the internet (`app/stills.py`)
For any real subject the writer names (`"photo"`), and as the fallback ladder when generation is out of quota: Wikimedia Commons (CC/PD) ->
NASA photos (PD) -> Openverse (keyless; CC0/PDM/BY/BY-SA, commercial-use filter). Every candidate is shown to a vision model and rejected
unless it clearly shows the subject (keyword matching alone picked a White House event for "Carrington Event"). Credits are recorded and sent
with the Short. A per-Short colour grade (`theme`: cool/warm/mono/earth, chosen by the writer, applied in `app/cinematic.py`) keeps generated
stills, downloaded photos and footage looking like one film.

## More galleries (free licences; verify each site's licence page before use)
Mixkit, Pexels, Pixabay and Coverr advertise free commercial use without attribution (per secondary sources; licence pages not verified here);
Vidsplay asks for a credit link. NASA images.nasa.gov for space footage. None of these need to be in the repo: add a clip to
`scripts/curate_motion.py` KEEP (name -> blend, moods, role) and re-run it.

## Known limits
Ambient clips are only 4; washes are subtle. More ambient fields (smoke, dust, embers, film grain, bokeh) would raise variety most. Footage relevance depends on NASA's
catalogue (good for space/Earth, none for finance/biology), so the judge's frame review is the safety net.
