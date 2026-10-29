// Cloudflare Worker (free): Telegram webhook -> GitHub repository_dispatch. Deploy in the Cloudflare dashboard (Workers -> Create -> paste).
// Secrets/vars to set on the Worker: TG_SECRET, TG_TOKEN, ALLOWED_CHAT, GH_TOKEN, GH_REPO ("owner/repo")
// Claude is the first layer: every message goes to the chat job (chat.yml). The Worker posts Claude's progress message at once (the job edits it
// live) and turns button taps (inline keyboards) into the same kind of job.
const CONTROLS = /^\/(model|effort|settings|claude|reset|changes|merge|discard)(@\w+)?(\s|$)/i;

async function tg(env, method, body) {
  return fetch(`https://api.telegram.org/bot${env.TG_TOKEN}/${method}`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
}

async function dispatch(env, payload) {
  const r = await fetch(`https://api.github.com/repos/${env.GH_REPO}/dispatches`, {
    method: "POST",
    headers: { Authorization: `Bearer ${env.GH_TOKEN}`, Accept: "application/vnd.github+json", "User-Agent": "shorts-orchestrator" },
    body: JSON.stringify({ event_type: "chat", client_payload: payload }),
  });
  return r.status === 204;
}

export default {
  async fetch(req, env) {
    if (req.method !== "POST") return new Response("ok");
    if (req.headers.get("X-Telegram-Bot-Api-Secret-Token") !== env.TG_SECRET) return new Response("forbidden", { status: 401 });
    const u = await req.json();

    // a tap on an inline button: "cmd:/model opus" runs a control, "say:<text>" sends that text to Claude as the owner's answer
    if (u.callback_query) {
      const q = u.callback_query, chat = q.message && q.message.chat.id, data = q.data || "";
      if (String(chat) !== String(env.ALLOWED_CHAT)) return new Response("ok");
      const text = data.startsWith("cmd:") ? data.slice(4) : data.startsWith("say:") ? data.slice(4) : "";
      if (!text) return new Response("ok");
      const ok = await dispatch(env, { chat: String(chat), text, edit: String(q.message.message_id), tap: data.startsWith("cmd:") ? "cmd" : "say" });
      await tg(env, "answerCallbackQuery", { callback_query_id: q.id, text: ok ? `→ ${text.slice(0, 60)}` : "Could not reach the system" });
      return new Response("ok");
    }

    const m = u.message || u.edited_message;
    if (!m || !m.text) return new Response("ok");
    if (String(m.chat.id) !== String(env.ALLOWED_CHAT)) return new Response("ok");          // only the owner is obeyed
    const t = m.text.trim().toLowerCase();
    if (t === "/help" || t === "/start") {          // answered instantly, no job needed
      await tg(env, "sendMessage", { chat_id: m.chat.id, text: "Just write to me: questions, ideas, changes, or ask me to make, approve or upload a Short. I am Claude and I run the system for you.\n\n/model, /effort, /settings - choose how I think (buttons)\n/changes - my proposed code changes (merge or discard with a tap)\n/reset - forget our conversation\n\nOne Short a day is made and posted automatically." });
      return new Response("ok");
    }
    let status = "";
    if (!CONTROLS.test(m.text.trim())) {             // Claude's progress message appears at once; the job edits it as Claude works
      const r = await tg(env, "sendMessage", { chat_id: m.chat.id, text: "🤖 Claude · reading your message…" });
      try { status = String((await r.json()).result.message_id); } catch (e) { status = ""; }
    }
    const ok = await dispatch(env, { chat: String(m.chat.id), text: m.text.slice(0, 3500), id: m.message_id, status });
    if (!ok) await tg(env, "sendMessage", { chat_id: m.chat.id, text: "Could not reach Claude (GitHub refused the job)." });
    return new Response("ok");
  },
};
