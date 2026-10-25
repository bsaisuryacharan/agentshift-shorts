// Cloudflare Worker (free): Telegram webhook -> GitHub repository_dispatch. Deploy in the Cloudflare dashboard (Workers -> Create -> paste).
// Secrets/vars to set on the Worker: TG_SECRET, TG_TOKEN, ALLOWED_CHAT, GH_TOKEN, GH_REPO ("owner/repo")
export default {
  async fetch(req, env) {
    if (req.method !== "POST") return new Response("ok");
    if (req.headers.get("X-Telegram-Bot-Api-Secret-Token") !== env.TG_SECRET) return new Response("forbidden", { status: 401 });
    const u = await req.json();
    const m = u.message || u.edited_message;
    if (!m || !m.text) return new Response("ok");
    if (String(m.chat.id) !== String(env.ALLOWED_CHAT)) return new Response("ok");          // only the owner is obeyed
    const t = m.text.trim().toLowerCase();
    if (t === "/help" || t === "/start") {          // answered instantly, no pipeline needed
      await fetch(`https://api.telegram.org/bot${env.TG_TOKEN}/sendMessage`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ chat_id: m.chat.id, text: "Commands:\n/new <topic> - make a Short (~15-20 min, arrives here)\n/status - current Short and scores\n/list - recent Shorts\n/use <id> - switch\n/approve - approve it and get the upload pack\n/upload - upload the approved Short to YouTube (private, scheduled 19:00 IST)\nOr just describe a change: \"shorter hook\", \"re-roll image 3\".\nA daily Short is made automatically at 17:00 IST." }),
      });
      return new Response("ok");
    }
    const r = await fetch(`https://api.github.com/repos/${env.GH_REPO}/dispatches`, {
      method: "POST",
      headers: { Authorization: `Bearer ${env.GH_TOKEN}`, Accept: "application/vnd.github+json", "User-Agent": "shorts-orchestrator" },
      body: JSON.stringify({ event_type: "telegram", client_payload: { chat: String(m.chat.id), text: m.text.slice(0, 2000), id: m.message_id } }),
    });
    const ack = r.status === 204 ? "Received - queued." : `Could not start the pipeline (GitHub ${r.status}).`;
    await fetch(`https://api.telegram.org/bot${env.TG_TOKEN}/sendMessage`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chat_id: m.chat.id, text: ack }),
    });
    return new Response("ok");
  },
};
