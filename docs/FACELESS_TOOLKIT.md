# Faceless Shorts toolkit: what exists, where it fits, what to build next

## Stage -> tool
| Stage | In the factory now | Available to add (from the owner's Claude skills / repos; verify before relying) |
|---|---|---|
| Topic + packaging | `picker`, `topicscore` (new), `ideabank`, `refs` (saved reference Shorts), `vidiq` snapshot, `trends` | `youtube-full`, `youtube-transcript` (study winners' hooks), `video-content-strategist` |
| Research + facts | Wikipedia + `research.py` (Tavily), claims audit, number validator | `firecrawl-research`, `deep-research` for primary sources |
| Script | `auto.write_spec` + `formats` + `lessons` | `short-video-script` rules (hook <= 9 words) |
| Voice | edge-tts (`voice.py`) | `elevenlabs-tts`, Kokoro (used by Lemo-Opuscar) |
| Real pictures / footage | NASA index, Commons, Openverse, Pexels/Pixabay stock, FLUX stills | `google-image-search`, `nano-banana`, `gpt-image-2` for abstract beats |
| Motion graphics | HyperFrames gallery (6 components), Claude Video 2.0 looks (now 12) | `hyperframes`, `hyperframes-registry`, `motion-graphics`, `faceless-explainer` (vendored) |
| Whole-film styles | none (looks only recolour) | **Lemo-Opuscar**: 66 film styles, code-rendered, vertical via `--size 1080x1920` |
| QA | `qa_v2` hard gates + contact-sheet judge + scorecard | `a11y-audit` style checks for captions/contrast |
| Publish + learn | autopost, hourly monitor, strategy, `learning` | YouTube Analytics per-video (token) |

## Topic class -> look -> closest Lemo-Opuscar style (`app/stylemap.py` PLAN)
| Topic class | Looks now (vendored) | Lemo-Opuscar styles to build as kits first |
|---|---|---|
| awe_scale | midnight-grid, poster-pop, editorial-paper, ink-line | Data Storytelling, Satellite Briefing |
| inside_machine | blueprint, explainer-diagram, graphite-ui | Exploded Teardown, Blueprint |
| myth_fact | swiss-kinetic, swiss-grid, poster-pop | Caption News, Swiss Motion Graphics |
| what_if | midnight-grid, graphite-ui, paper-cut | Sci-fi Hologram HUD, Isometric Infographic |
| earth_hazard | paper-cut, risograph, editorial-paper | Risograph Print, Satellite Briefing |
| history_event | time-travel, editorial-paper, risograph | 1920s Newsreel, Archive Light Table |
| jargon_science | explainer-diagram, ink-line, blueprint | Whiteboard Explainer, Chalkboard |
| tech_explainer / ai_tips | graphite-ui, midnight-grid, swiss-kinetic | Dark Tech Keynote, Living Screencast |

## How a Lemo-Opuscar style becomes an automatic look (the part not built yet)
A Lemo film is hand-directed code (a page exposing `render(t)`), rendered frame by frame with `core/render/video.mjs` (~2 minutes for 40 s on 3 workers: fine for a free GitHub runner).
To use one automatically: (1) pick a style whose output is mostly type + shapes + data (Data Storytelling, Blueprint, Whiteboard, Risograph, Caption News); (2) turn its demo page
into a kit that takes the factory's `spec.json` (beats, numbers, captions, timings from `voice.py`) instead of a hand-written story; (3) register it in `stylemap.PLAN` as an engine
for that class; (4) A/B it against the HTML looks using `stylemap.look_results` before it replaces them. `spec["style_map"]["lemo_style"]` already records the intended style per Short.
