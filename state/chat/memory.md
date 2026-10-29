# Agent Shift - long-term memory
(Kept by the chat agent; seeded 2026-10-29 from the owner's sessions with Claude Code on the Mac. Newest items last in each section.)

## Decisions
- 2026-10-24 Everything runs in the cloud on free tiers (GitHub Actions + Cloudflare Worker). Nothing scheduled on the Mac.
- 2026-10-25 Only Shorts that pass the judge reach Telegram; drafts are never sent.
- 2026-10-25 Uploads are public, never private.
- 2026-10-25 Formats rotate (9 formats); never stuck on "what if".
- 2026-10-28 Review bar recalibrated (review_bar): policy 10, accuracy >= 9, hook >= 7, no core score below 5, average >= 6.8; originality and visual variety count only in the average. The old all-scores-7 bar never passed on free imagery.
- 2026-10-28 Topic picker drops consumer products, brands, gadgets and AI-chatbot topics; niche is science, space, nature, physics, brain, history.
- 2026-10-28 Stay on free tiers; first paid upgrade, if ever needed, would be the Gemini API for script + judge (about Rs 100-150/month). Pexels keys are paused for new signups; Pixabay is used.
- 2026-10-29 One Short a day, posted automatically when the judge approves (AUTO_POST, repo variable; set it to false to go back to /approve).
- 2026-10-29 Claude (this chat) is the first layer for every Telegram message; code changes only as pull requests that go live on the owner's /merge.

## Owner's rules and preferences
- Target: 1,000,000 views per Short and the YouTube Partner Programme.
- Channel results (vidIQ, 2026-10-25): space/brain/Earth-scale curiosity wins (1,689 and 1,110 views); AI tools/prompts/phone tips flop (21-183). Best length 27-32 s.
- Visual direction: real photos and NASA/stock footage with 1-2 big animated numbers or comparisons; AI images only for abstract ideas, never for a named real object.
- Replies short, plain language, phone-friendly. Never print secrets.

## Changes made (outside the chat, by Claude Code on the Mac)
- 2026-10-25 vidIQ snapshot (assets/vidiq.json) incl. channel analytics feeds picker and writer; cache is primary, live vidIQ only refreshes it.
- 2026-10-28 Pixabay stock video and photos added (PIXABAY_API_KEY); a clip is never reused in one Short.
- 2026-10-29 Self-learning: judge complaints become standing writer rules (app/lessons.py, data/judge_notes.jsonl); format choice leans to best-scoring formats.
- 2026-10-29 Topic picker: best of 3 options by real-picture coverage (refuses < 50%).
- 2026-10-29 Fact checks: numbers must match Wikipedia FACTS in context ('22 crewed descents' does not support '22 humans'); screen numbers must be spoken; the judge now receives the FACTS.
- 2026-10-29 Captions never end on a dangling word; scramble-reveal graphic retired; loudness corrected to -14 LUFS; upload pack credits only pictures that are in the video.
- 2026-10-29 Schedule: 3 daily slots (09:47, 14:17, 18:07 IST); later slots skip once today's Short is delivered.
- 2026-10-29 Stage tests: stage-check.yml (pick | script | pictures) on several topics.
- 2026-10-29 Chat agent got long-term memory (this file) and an automatic action log; /memory and /actions show them; Telegram buttons for model, effort, settings, changes

## Open items
- 2026-10-29 Mariana Trench Short (first judge-approved, "mariana-trench-mystery-a2") approved by the owner but NOT yet on YouTube: the first upload failed on an expired YouTube login; the login was renewed. Send /upload (owner's go-ahead given) to post it. Its narration says "22 people have reached these depths" (Wikipedia: 22 crewed descents) - the owner chose to post anyway.
- 2026-10-29 Owner should set the Google Cloud OAuth consent screen to "In production", or the YouTube login expires every 7 days.
- Free AI quota (Gemini/Groq) runs out after ~2 full runs a day; avoid extra test runs.
- Pronunciation of the voice is not checked automatically.
