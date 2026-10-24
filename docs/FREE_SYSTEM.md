# Free autonomous Short system (zero-cost plan)

`python -m app.auto --topic "..." [--facts file]` (or `--trend`) does: research -> script/spec (free LLM) -> free stills -> render ->
hard gates -> judge (a different model than the writer) -> up to 3 tries -> Telegram. `.github/workflows/free-daily.yml` runs it daily.

| Stage | Free provider | Needs |
|---|---|---|
| Writer / judge | Gemini Flash, Groq Llama (writer != judge when 2 keys exist), OpenRouter free | `GEMINI_API_KEY`, `GROQ_API_KEY` |
| Stills | Cloudflare FLUX -> Pollinations -> real NASA photo -> real Commons photo -> plain texture frame (last resort, marked down by the judge) | `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN` |
| Facts | Wikipedia (or `--facts file`) | none |
| Voice | edge-tts | none |
| Render | GitHub Actions (public repo = unlimited) | none |
| Delivery | Telegram bot | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` |

Set the keys as GitHub repo secrets. Publishing stays manual until YouTube's API audit passes.
Honest limits: Pollinations stills are noticeably softer than paid ones and often fail the judge's visual_quality >= 8; use the Cloudflare key.
The number check in `validate_spec` is a heuristic; the judge's accuracy score is the second check; read the facts before you publish.

## Run it (Mac)
`./run_orchestrator.sh` - installs once, then listens on your existing Telegram bot. Message the bot:
- `/new <topic>` research -> script -> stills -> render -> judge -> video in chat (~10-15 min)
- If the automatic judge approves, you get the Short. If it is factual and policy-safe but visually short of the bar, you get it as a **DRAFT** with the weakest scores and fixes. If it fails hard gates 3x it is parked with the reason.
- Any plain message = a change request for the current Short ("shorter hook", "re-roll image 3"); only changed pictures are regenerated.
- `/approve` - returns the title, description, sources and photo credits ready to paste into YouTube Studio, and records the Short in the no-repeat ledger. Uploading stays manual (private-until-audit rule).

## Real photos
A beat about a real named person/place can set `"photo": "<search term>"`: a free-licence photo is pulled from Wikimedia Commons (CC/public domain only), shown whole over a blurred fill, credited in `img/credits.json` and in the caption/publish pack. If none is found it falls back to the generated still.

## Motion graphics
Beats can use bars, line, ring, delta, kinetic, tape, toast, cursor, plus `"fx":"shine"` (see `app/motion.py`); the writer is told when to use them.

## Moving layers (video feel without a video model)
`assets/motion/` holds 31 small text-free clips curated from the HyperFrames catalog; `app/motionbank.py` blends one over each beat's still. A beat may also ask for
real NASA footage (`"footage"`, `app/footage.py`). Details, sources and licences: `docs/MOTION_ASSETS.md`.

## Insights feed (cloud, weekly)
`.github/workflows/weekly-insights.yml` (Mondays 03:00 UTC) runs `python -m app.weekly`: trend signals (needs the `YOUTUBE_API_KEY` secret), the
owner's channel analytics (needs the `YOUTUBE_TOKEN_JSON` secret = the content of a token.json with the yt-analytics.readonly scope), and the judge
history from `data/history.jsonl`. It writes `assets/insights.json`, which the topic picker and script writer read: best/worst past Shorts and the
dimensions that fail most, so topic and angle choice adjusts week by week. Without the two optional secrets the job still runs on judge history alone.
Set them from your Mac without showing the values:  `gh secret set YOUTUBE_API_KEY -R <repo>`  (paste when prompted) and
`gh secret set YOUTUBE_TOKEN_JSON -R <repo> < token.json`.

## Telegram
Typing `/` in the chat lists the commands (`app/botmenu.py` registers them at the start of every cloud job). A run that cannot make a Short sends
one "Not today" message with the reason; nothing else runs on the owner's Mac (the launchd agents are unloaded).

## Known limits
Free image quota: Cloudflare's daily allowance covers roughly 3-4 full runs (3 attempts each) and resets at 00:00 UTC; after that the ladder falls back to real photos and plain textures.
Rendering needs Chromium; on a Linux box without root, a missing `libXdamage` can be unpacked locally and exposed via `LD_LIBRARY_PATH`. Composite with `workers=2` on machines with <=4 GB RAM.
