# Plan coverage — 24 Oct 2026

Everything below runs in the cloud (GitHub Actions + Cloudflare Worker). Nothing is scheduled on the owner's Mac any more
(both launchd agents were unloaded). The Mac is only where code is edited and `python3 deploy/sync_repo.py` is run.

| Plan item | State | Where |
|---|---|---|
| Automatic topic picking (trends + Wikipedia most-read + evergreen, no-repeat ledger) | done | `app/auto.py pick_topic` |
| Research from Wikipedia, every number checked against FACTS | done | `auto.wiki_facts`, `validate_spec` |
| Script -> spec (free LLM ladder, schema validation, provider rotation, throttling wait) | done | `auto.write_spec`, `auto.ask` |
| Stills: FLUX -> Pollinations -> Gemini -> real photos (Commons, NASA, Openverse, vision-verified) -> texture | done | `app/stills.py` |
| Real photos preferred for real subjects (`"photo"`), writer told to use them on >= 3 beats | done | `stills.ensure`, `auto.SYSTEM` |
| Motion bank (31 text-free loops from the HyperFrames Make catalog) blended over stills | done | `assets/motion`, `app/motionbank.py` |
| NASA clip index (1,088 clips, fetched on demand, subtitles cropped, vision-verified) | done | `assets/motion/nasa_index.json`, `app/footage.py` |
| Footage replaces the picture when image quota is gone | done | `produce.run` -> `footage.ensure(need_pictures)` |
| One colour grade per Short (cool/warm/mono/earth) so all sources match | done | `app/cinematic.py THEMES` |
| Voice (edge-tts, retries), mix, HUD, overlay, composite, hard gates, judge (different model), 3 attempts, DRAFT delivery | done (pre-existing + fixes) | `app/produce.py`, `app/qa_v2.py`, `auto.finish` |
| Telegram: delivery, `/new /status /list /use /approve /help`, slash-command menu, one "Not today" message on failure | done | `app/orchestrator.py`, `app/botmenu.py`, `deploy/worker.js` |
| Daily Short visible to `/status /list /approve` | done | `orchestrator register` step in `free-daily.yml` |
| Daily schedule 11:30 UTC (17:00 IST) | deployed, first automatic firing not yet observed | `scripts/free-daily.yml` |
| Weekly insights: trend signals + channel analytics + judge history -> picker/writer | done; channel analytics needs the `YOUTUBE_TOKEN_JSON` secret, YouTube trend signals need `YOUTUBE_API_KEY` | `scripts/weekly-insights.yml`, `app/weekly.py`, `app/insights.py` |
| Self-improvement: best/worst past Shorts and weakest judge dimensions steer topic + angle | done (judge history now; view/retention data once the token secret is set) | `insights.build/hint` |
| YouTube upload | intentionally manual (Telegram only, `/approve` gives the publish pack) | `orchestrator.publish_pack` |
| vidIQ | not wired (paid credits; owner decision) | docs only |

## Secrets the owner must add for the two optional insight sources (values never pass through the agent)
```
gh secret set YOUTUBE_API_KEY  -R bsaisuryacharan/agentshift-shorts            # paste the key when prompted
gh secret set YOUTUBE_TOKEN_JSON -R bsaisuryacharan/agentshift-shorts < token.json
```
Then: `gh workflow run weekly-insights.yml -R bsaisuryacharan/agentshift-shorts`.

## Known limits (honest)
- Free image quota: Cloudflare's 10,000 neurons/day covers ~3-4 full runs; beyond that the Short is made from real photos + NASA footage and
  the judge scores it lower. Keep it to one Short a day.
- NASA covers space/Earth/aviation/science; Openverse and Commons cover most real objects; abstract "concept art" prompts have no real-photo match.
- The judge's main complaint remains the AI-generated look of FLUX stills; real photos and footage reduce it but do not remove it.
- The stale local file `.github/workflows/daily-production.yml` (legacy, not deployed) should be deleted by the owner.


## Update 25 Oct 2026
- Only Shorts that pass the judge reach Telegram; `/approve` approves AND uploads (public; if YouTube forces private for an unaudited API project the reply says so). `/upload` retries.
- Target system (docs/TARGETS.md): hourly monitor, per-stage scorecards, guideline checks, playbook, `/target`.
- Gallery motion graphics (6 HyperFrames components) are required in every Short.
- Still unproven live: the first real upload (no Short has passed the judge yet) and the first hourly monitor run with real data.
