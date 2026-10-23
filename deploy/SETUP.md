# Telegram orchestrator

## Start now (Mac, 2 minutes) — uses your EXISTING bot, nothing new to create
```
cd shorts_factory && pip install -e . && playwright install chromium
python -m app.orchestrator listen
```
It reads the bot token, chat id and LLM keys from your `.env` (never printed) and answers only your chat. Message the bot `/help`, then `/new <topic>`
or describe a change to the current Short. Works while the Mac is awake and this command is running.

## Always-on version (free, no Mac needed) — one-time, ~20 minutes
Skip step 1 (your bot already exists; reuse its token and chat id).

You talk to a Telegram bot. A free Cloudflare Worker forwards each message to GitHub, a GitHub Actions job runs the pipeline, and the
video comes back to the same chat. Keys live only in GitHub / Cloudflare secrets — never paste them into a chat with me.

1. **Telegram bot.** In Telegram open @BotFather -> /newbot -> copy the token. Send your new bot any message ("hi").
   Your chat id: open `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser and read `message.chat.id`.
2. **GitHub repo (public = unlimited free minutes).** Push the shorts_factory folder (NOT `.env`, `token.json`, `oauth_client.json` — add them to `.gitignore`;
   also ignore `runs/`). Move `scripts/free-daily.yml` and `deploy/orchestrator.yml` into `.github/workflows/`.
   Repo -> Settings -> Secrets and variables -> Actions: add `GEMINI_API_KEY`, `GROQ_API_KEY`, `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN`,
   `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.
3. **GitHub token for the Worker.** Settings -> Developer settings -> Fine-grained token, only this repo, permission **Contents: Read and write**
   (that is what `repository_dispatch` needs).
4. **Cloudflare Worker.** Dashboard -> Workers -> Create -> paste `deploy/worker.js`. Add variables/secrets: `TG_SECRET` (any long random string),
   `TG_TOKEN` (bot token), `ALLOWED_CHAT` (your chat id), `GH_TOKEN` (step 3), `GH_REPO` (`owner/repo`).
5. **Connect Telegram to the Worker** (run once in your own terminal; replace the placeholders):
   `curl "https://api.telegram.org/bot<TOKEN>/setWebhook" -d "url=https://<your-worker>.workers.dev" -d "secret_token=<TG_SECRET>"`
6. Message the bot `/help`, then `/new <topic>`.

Behaviour: one job at a time (send changes one by one). Only your chat id is obeyed. Free limits: Gemini/Groq/Cloudflare daily quotas decide how many Shorts per day.
