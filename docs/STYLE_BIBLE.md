# Style bible — what "production quality" looks like here

Reference: Cleo Abram / top explainer Shorts. Not templates, not slideshows.

## Picture
1. **A real photographic frame under every beat** — 9:16, cinematic lighting, one subject, one idea. No flat vector clip-art, no stock-looking collages.
2. **The camera moves every beat.** Push-in toward a focal point (1.25–1.5×), alternate slight rotation, never a static hold > 2 s.
3. **Cut or transition every 3–5 s.** Portal/zoom-blur between scenes; hard impact flash (0.5) on the single biggest moment.
4. **One VFX moment** (debris burst, energy ring, number slam). Free particles in `cinematic.py`; paid video clip only for the hook or climax and only with approval.
5. **Colour discipline:** one dominant hue per video + one accent (e.g. cyan world, red danger). Vignette 0.45, grain σ=3.
6. **Hook frame = best frame.** Frame 0 must work with sound off: question + arresting image + bold bubble/title.

## Type & HUD (overlay layer)
- Three tiers only: **hero number/phrase** (110–200 px), **label** (60–76 px), **chip/sub** (28–46 px). Min 28 px.
- One focal graphic per beat. Numbers count up; claims land on the spoken word (`W(key, word)` timing).
- Dark scrim behind text on bright photos; never text on busy detail without it.
- Fonts must contain every glyph used (₹ € µ ⁻ ✓) — run `glyph_audit`.

## Safe zones (1080×1920) — YouTube Shorts UI
| Zone | Rule |
|---|---|
| Bottom 500 px (y > 1420) | channel name + title — **nothing important** |
| Right 140 px (x > 940) | like/comment/share buttons — **nothing important** |
| Top 130 px | status bar / progress — brand bar only |
| Captions | pinned `bottom:540px; left:60px; right:150px` (y ≈ 1220–1380) |
| Content stage | y 150 → 1270 |

## Voice & sound
- Neural voice, +8…+12 % rate, no sentence over 16 words, hook ≤ 9 words.
- Music bed ducked 12 dB under voice; whoosh on cuts, impact on the climax, ding on a key number.
- Loudness **−14 LUFS**, true peak ≤ −1.5 dB. Quiet end-card tail (≤ 3.5 s) is fine.

## Story (35–45 s)
Hook question (0–3 s) → stakes number (3–8 s) → escalation × 3 (one new fact each) → twist/payoff → honest limit ("this is hypothetical") → CTA that names the next video. Last line echoes the first.

## Honesty
Every number cited in `fact_ledger`/`sources`. Hypotheticals labelled on screen. No fabricated quotes, no real-person likeness, AI imagery is disclosed in the YouTube "altered or synthetic content" toggle when realistic.
