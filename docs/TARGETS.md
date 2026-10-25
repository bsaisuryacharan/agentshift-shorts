# Target, monetisation and the self-correcting loop

## The goal
**1,000,000 views per Short**, then YouTube Partner Programme (YPP) eligibility. YPP, as YouTube publishes it:
- fan funding tier: 500 subscribers + 3 public uploads in 90 days + (3,000 public watch hours in 12 months or 3M public Shorts views in 90 days)
- ads tier: 1,000 subscribers + (4,000 public watch hours in 12 months or 10M public Shorts views in 90 days)

Views and income cannot be commanded or guaranteed. What the system controls is the quality of every stage and how fast it learns from the numbers.

## Guideline risk (read this)
YouTube's monetisation rules exclude "inauthentic / mass-produced" content: repetitive templated videos and content with no original value-add. A fully automated channel is
the typical target of that rule. Defences built in: original narration and analysis per Short, sources and credits for every third-party picture/footage, synthetic-media
disclosure on every upload, no real people's faces, a check against repeating the same format, and the owner's `/approve` before anything is published. If the channel is ever
reviewed and rejected, that is a policy outcome the code cannot change.

## The loop (all in the cloud)
| when | what | where |
|---|---|---|
| per attempt | every Short is graded per stage (hook, story, visuals, polish, policy: A >= 9, B >= 8, C >= 7, D < 7), the weakest stage is named, and the next attempt fixes that stage first | `app/scorecard.py`, `scorecard.json` per run, `data/scorecards.jsonl` |
| per attempt | guideline checks: sources, credited third-party media, under 60 s (hard: a failing Short is not approved); original narration, template repetition (warnings) | `scorecard.policy` |
| hourly | real views/likes/comments of every uploaded Short, compared with the target curve (on track / behind / far behind, projected 30-day views), subscribers, YPP progress | `.github/workflows/monitor.yml` -> `app/monitor.py` -> `data/performance.jsonl`, `assets/insights.json` |
| weekly | trend signals, your channel analytics, judge history | `weekly-insights.yml` |
| every topic/script | the picker and writer read the target, progress, lessons and the weakest stage | `app/insights.py hint()` |
| as data accrues | what separates winners from losers (topic type, colour theme, opening length, gallery graphics), reported only with >= 4 Shorts older than 48 h and a >= 1.5x gap | `app/playbook.py` |
| on demand | `/target` in Telegram shows the card | `orchestrator.target_report` |

`targets.CURVE` (the share of 30-day views expected by a given age) is an assumption used for the early on-track call; it is replaced by real data as history grows.
