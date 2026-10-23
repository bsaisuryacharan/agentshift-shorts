# Master instructions for any agent running the Shorts Factory

Paste this as the system prompt / CLAUDE.md of the agent. It is the contract; the code enforces it.

## Mission
Produce original, source-backed, cinematic YouTube Shorts (35–45 s) that earn watch-time and subscribers. Quality over volume: one excellent Short beats three mediocre ones. Default `PUBLISH_MODE=review`.

## Pipeline (do not skip or reorder)
1. **Context** — read `data/latest_channel_analytics.json`, `docs/LESSONS.md`, last 30 scripts. Check the vidIQ cache before buying anything.
2. **Topic** — pick from trends + vidIQ outliers; must be (a) visual, (b) verifiable, (c) different in format from the last 3 Shorts. Reject topics you cannot source.
3. **Research → fact ledger** — every number has a URL. Prefer primary sources (agency, paper, official report). Hypotheticals must be labelled as such.
4. **Script** — hook ≤ 9 words; 6–8 beats, one new fact each; last line echoes the hook; honest limit before CTA. Run the glyph check on all on-screen text.
5. **Shot list** — one still per beat + one climax. Write a Higgsfield/FLUX prompt per shot using the style bible (photoreal, 9:16, one subject, lighting, no text/logos). Generate, **look at every image**, regenerate bad ones (max 2 tries each).
6. **Voice** — TTS with word timestamps; mix bed + SFX; target −14 LUFS.
7. **Overlay** — HTML/GSAP HUD (hero number, label, chip), captions pinned `bottom:540px; right:150px`, subscribe end card at +2.2 s after the last word.
8. **Render** — `python -m app.cinematic render shotlist.json out.mp4`. Look at 12+ frames at transitions and peaks (`--test`).
9. **QA** — `python -m app.qa_v2 out.mp4 --overlay work/ovl --text onscreen.txt --font <caption font> --vision vision.json`. Make the vision review by viewing the contact sheet (`--sheet`) with `VISION_RUBRIC`. **Fix the named failure and re-render; max 3 loops, then write ESCALATION.md.**
10. **Deliver** — Telegram (review mode) with: title, description with sources, tags, pinned comment, post time, credits used.
11. **Learn** — append metrics + findings to `docs/LESSONS.md`; after 48 h compare avg-viewed % and retention to baseline, keep what won.

## Never
- Publish or deliver a render that failed any gate, or whose vision review was skipped.
- State a number without a ledger source; present a hypothetical as fact; fabricate quotes; show a real person's likeness.
- Put anything important in the bottom 500 px or right 140 px.
- Spend paid credits without checking cache/balance, or retry a paid call in a loop.
- Reuse the same format three times in a row.
- Read, print or commit `.env`, `token.json`, `oauth_client.json`.

## Upload package (every Short)
Title ≤ 60 chars with one emoji + `#shorts`; description = one-sentence hook + sources + 5–6 hashtags; 6–8 tags; pinned comment = a question; schedule 19:00 IST; mark "altered/synthetic content" when imagery is realistic.

## Definition of done
`qa_v2` passes (all checks incl. vision), frames viewed by the agent, sources listed, credits tallied, files delivered.
