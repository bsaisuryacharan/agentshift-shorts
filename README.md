# Shorts Factory

A production system for creating source-backed, original YouTube Shorts. It is designed to fail closed: no render reaches delivery or publishing without hard QA, source validation, and an independent editorial review.

## What it does

`channel analytics monitor + trend research → source discovery → script → fact ledger → voice → source imagery → 3 art-directed motion candidates → hard QA → frame-based visual review → winner → Telegram → YouTube`

The default is `PUBLISH_MODE=review`: an approved MP4 and its evidence packet are delivered to Telegram; publishing remains a deliberate action. Set `PUBLISH_MODE=schedule` only after OAuth is configured and the channel has passed editorial review.

## Live trend analyzer

Run `python -m app.main analyze-trends` to create `data/latest_trend_report.json`. It combines:

- YouTube's current popular Science & Technology chart as **short-form candidates**—not falsely as a canonical Shorts trend list;
- seven-day Google News RSS signals;
- current NASA primary-source candidates; and
- optionally, performance from the connected Instagram business account's own Reels.

Instagram does not expose a public global Reels trend feed through this integration. Reels data is therefore clearly labeled as connected-account performance, while news and primary sources supply the evidence required for scripting. All trend signals guide packaging and topic selection only; they can never become factual claims without a direct source.

## Growth and capability audit

After a review-mode run, use `python -m app.main audit-growth --run-dir output/<run-id>`. The audit evaluates appeal, engagement, satisfaction, and originality, plus source integrity, candidate-frame reviews, a bounded YouTube packaging scan, and installed production capabilities.

It does **not** predict views or promise virality. YouTube ranks Shorts by individual viewer response—whether viewers choose to watch, stick around, and feel satisfied. The system changes generation constraints only when a measured audit identifies one; hooks are now capped at nine words. Missing tools are recommendations only: nothing is downloaded or enabled automatically.

## Channel-performance monitor

Run `python -m app.main monitor-analytics` to create `data/latest_channel_analytics.json`. It compares the latest completed 30-day Shorts period with the preceding equal-length period, recording views, engaged views, watch time, average view duration/percentage, engagement, shares, and subscriber movement. Its bounded topic guidance is read before trend discovery.

The monitor never turns missing metrics into zero, predicts virality, or copies a successful Short's topic or footage. “Shown in feed” and “chose to view” are reported only when an approved source provides them. Run `python -m app.main authorize-youtube` again once to add **read-only YouTube Analytics** access; publishing remains review-only.

## Supervised teacher loop

`python -m app.main teacher-loop --target 3 --max-attempts 9` runs one Short at a time until three review-mode Telegram deliveries pass every gate, or a real external dependency requires waiting. Each run writes `teacher_notes.json` beside its manifest; the batch ledger is `data/teacher_loop_state.json`. It checks analytics and trends before each run, retains structured visual-review feedback, remembers visually unsuitable sources, and never approves a text-only or unavailable visual review. `scripts/install-teacher-loop.sh` registers the local 1:10 PM loop, timed after the current visual-review quota reset window.

## Local macOS scheduler

For an independent Mac setup, run `scripts/install-local-schedule.sh` once. macOS `launchd` then runs the monitor, trend analysis, and fail-closed production cycle locally every day at 6:00 AM. Logs stay in `logs/`; no Codex session, GitHub Action, or chat presence is required.

## Setup

1. Install Python 3.11+, `ffmpeg`, and Chromium/Google Chrome.
2. `python -m venv .venv && source .venv/bin/activate`
3. `pip install -e '.[dev]'`
4. `cp .env.example .env` and enter the provider credentials.
5. Put the Google OAuth desktop client file at `oauth_client.json`; run `python -m app.main authorize-youtube` once on a machine with a browser.
   For Telegram, open the bot, send it `/start`, then run `python -m app.main telegram-chat-id` and save its output as `TELEGRAM_CHAT_ID`.
6. Run a production dry run: `python -m app.main run --dry-run`
7. Run delivery only after inspecting the run: `python -m app.main run`

## Production contract

- Every numeric or factual claim must cite a primary or reputable source in `fact_ledger.json`; an automatic topic also needs at least four distinct first-party source images before narration is generated.
- Scripts are rejected if too similar to the last 30 approved scripts.
- Video must be 20–60s, 1080×1920, below Telegram's delivery limit, caption-safe, non-frozen, and audio-normalized.
- A distinct model evaluates hook, visual coherence, accuracy, originality, and policy risk.
- The candidate renderer starts from a 200-item, attributed public motion-reference library. It stores only metadata and distilled techniques—not third-party prompts, copy, thumbnails, or video assets.
- Each run produces kinetic-evidence, editorial-collage, and data-pulse candidates. A visual reviewer sees decoded contact-sheet frames and can reject any candidate. Only the highest approved candidate can reach Telegram.
- Learning is bounded: measured review scores reorder future candidate tests and a small allowlist of visual fixes can refine the third candidate. It cannot alter code, credentials, publishing settings, or install tools from internet feedback.
- Regeneration targets only the failing stage and stops after the configured retry limit.
- Secrets are environment variables or CI secrets only. Generated media, OAuth tokens, and databases are gitignored.

## CI scheduling

The workflow runs daily at 12:30 UTC (18:00 IST), supports manual dispatch, and uses GitHub Actions secrets. Keep the repository active: GitHub can disable scheduled workflows after 60 days without repository activity.

## Required account actions

You must create accounts/tokens for Gemini or Groq, Cloudflare Workers AI, Telegram, and Google OAuth. The system will refuse to publish if OAuth credentials or an explicit schedule are missing.
