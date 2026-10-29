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
        body: JSON.stringify({ chat_id: m.chat.id, text: "Commands:\n/new <topic> - make a Short (~15-20 min, arrives here)\n/status - current Short and scores\n/target - progress towards 1,000,000 views and monetisation\n/list - recent Shorts\n/use <id> - switch\n/approve - approve the Short: it is uploaded to YouTube automatically (public)\n/upload - retry that upload if it failed\n\nTalk to Claude: just write a message (questions, ideas, changes to the system).\n/model opus|sonnet|haiku, /effort low|medium|high|xhigh|max, /settings, /reset\n/changes - Claude's proposed code changes, /merge - make one live, /discard - drop it\n\nOne Short a day is made and posted automatically." }),
      });
      return new Response("ok");
    }
    // pipeline commands go to the orchestrator; plain messages and the chat controls go to Claude (chat.yml)
    const pipeline = /^\/(new|status|target|list|use|approve|upload)(@\w+)?(\s|$)/i.test(m.text.trim());
    const r = await fetch(`https://api.github.com/repos/${env.GH_REPO}/dispatches`, {
      method: "POST",
      headers: { Authorization: `Bearer ${env.GH_TOKEN}`, Accept: "application/vnd.github+json", "User-Agent": "shorts-orchestrator" },
      body: JSON.stringify({ event_type: pipeline ? "telegram" : "chat", client_payload: { chat: String(m.chat.id), text: m.text.slice(0, 3500), id: m.message_id } }),
    });
    const ack = r.status === 204 ? (pipeline ? "Received - queued." : "Got it - passing it to Claude.") : `Could not start (GitHub ${r.status}).`;
    await fetch(`https://api.telegram.org/bot${env.TG_TOKEN}/sendMessage`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chat_id: m.chat.id, text: ack }),
    });
    return new Response("ok");
  },
};
