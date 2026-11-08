// AIDO Lead Copilot - the UI layer (Hebrew, right to left). It displays what the backend sends; it remembers nothing itself.
(() => {
  const $ = (id) => document.getElementById(id);
  const state = { user: null, conversations: [], current: null, image: null, streaming: false };
  const TOOL_HE = { leads_query: "שאילתת לידים", lookup_business: "בדיקת עסק", log_lead: "רישום ליד", calculate_stage: "חישוב שלב" };
  const STATUS_HE = { new: "חדש", contacted: "נוצר קשר", meeting: "נקבעה פגישה", diagnosed: "אבחון בוצע", proposal: "הצעה נשלחה", won: "נסגר", lost: "אבד" };
  const RECORD_HE = { logged: "נרשם", needs_a_look: "צריך בדיקה" };

  // ---------- helpers ----------
  async function api(path, options = {}) {
    const res = await fetch(path, { headers: { "Content-Type": "application/json" }, credentials: "same-origin", ...options });
    if (res.status === 401 && path !== "/api/login") { showLogin(); throw new Error("צריך להתחבר."); }
    if (!res.ok) {
      let detail = res.statusText;
      try { detail = (await res.json()).detail || detail; } catch (_) {}
      throw new Error(detail);
    }
    return res.status === 204 ? null : res.json();
  }
  function render(md) {
    if (window.marked) { try { return marked.parse(md, { breaks: true }); } catch (_) {} }
    const div = document.createElement("div"); div.textContent = md; return div.innerHTML.replace(/\n/g, "<br>");
  }
  function escapeHtml(s) { const d = document.createElement("div"); d.textContent = s; return d.innerHTML; }
  function setStatus(text) { $("status").textContent = text || ""; }
  function scrollDown() { const m = $("messages"); m.scrollTop = m.scrollHeight; }

  // ---------- auth ----------
  function showLogin() { $("login").classList.remove("hidden"); $("app").classList.add("hidden"); }
  function showApp() { $("login").classList.add("hidden"); $("app").classList.remove("hidden"); $("who").textContent = state.user ? `מחובר/ת: ${state.user.name}` : ""; }

  $("login-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    $("login-error").textContent = "";
    try {
      state.user = await api("/api/login", { method: "POST", body: JSON.stringify({ name: $("login-name").value.trim(), password: $("login-password").value }) });
      $("login-password").value = "";
      showApp();
      await loadConversations();
    } catch (err) { $("login-error").textContent = err.message; }
  });
  $("logout").addEventListener("click", async () => { await api("/api/logout", { method: "POST" }).catch(() => {}); state.user = null; state.current = null; showLogin(); });

  // ---------- conversations ----------
  async function loadConversations() {
    state.conversations = await api("/api/conversations");
    renderConversations();
    if (state.current) await openConversation(state.current); else renderEmpty();
  }
  function renderConversations() {
    const nav = $("conversations"); nav.innerHTML = "";
    for (const c of state.conversations) {
      const b = document.createElement("button");
      b.textContent = c.title; b.title = c.title;
      if (c.id === state.current) b.classList.add("active");
      b.addEventListener("click", () => openConversation(c.id));
      nav.appendChild(b);
    }
  }
  async function openConversation(id) {
    state.current = id;
    const conv = state.conversations.find((c) => c.id === id);
    $("conv-title").textContent = conv ? conv.title : "שיחה";
    renderConversations();
    const messages = await api(`/api/conversations/${id}/messages`);
    const box = $("messages"); box.innerHTML = "";
    for (const m of messages) addBubble(m.role, m.content, { hasImage: m.has_image, time: m.created_at });
    if (!messages.length) renderEmpty();
    scrollDown();
  }
  function renderEmpty() {
    $("messages").innerHTML = `<div class="empty"><p>במה אפשר לעזור?</p>
      <small>שאלה על הלידים, בדיקה אם עסק כבר קיים, או רישום ליד מסיכום פגישה.</small><br>
      <span class="hint" data-q="כמה לידים יש בכל שלב?">כמה לידים יש בכל שלב?</span>
      <span class="hint" data-q="אילו לידים חמים מחכים לטיפול?">לידים חמים שמחכים</span>
      <span class="hint" data-q="מה השלב של עסק עם ציון 41?">שלב לציון 41</span>
      <span class="hint" data-q="מה התעשייה עם הכי הרבה לידים חמים?">התעשייה הכי חמה</span></div>`;
    $("messages").querySelectorAll(".hint").forEach((h) => {
      h.tabIndex = 0; h.setAttribute("role", "button");
      const use = () => { $("input").value = h.dataset.q; $("input").focus(); };
      h.addEventListener("click", use);
      h.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); use(); } });
    });
  }
  $("new-chat").addEventListener("click", () => { state.current = null; $("conv-title").textContent = "שיחה חדשה"; renderConversations(); renderEmpty(); $("input").focus(); });

  // ---------- messages ----------
  function addBubble(role, text, { hasImage = false, imageDataUrl = null, time = null } = {}) {
    const div = document.createElement("div");
    div.className = `msg ${role}`;
    const who = role === "user" ? (state.user ? state.user.name : "את/ה") : "Lead Copilot";
    const initial = role === "user" ? who.trim().charAt(0).toUpperCase() : "A";
    const when = time ? new Date(time) : new Date();
    const stamp = when.toLocaleTimeString("he-IL", { hour: "2-digit", minute: "2-digit" });
    let inner = "";
    if (imageDataUrl) inner += `<img class="img" src="${imageDataUrl}" alt="צילום מצורף של סיכום פגישה">`;
    else if (hasImage) inner += `<span class="chip">📎 תמונה</span><br>`;
    inner += role === "user" ? `<p>${escapeHtml(text).replace(/\n/g, "<br>")}</p>` : render(text);
    div.innerHTML = `<div class="avatar ${role}">${initial}</div><div class="msg-body"><div class="msg-head"><span class="author">${escapeHtml(who)}</span><span class="time">${stamp}</span></div><div class="body">${inner}</div></div>`;
    $("messages").appendChild(div);
    scrollDown();
    return div;
  }

  // ---------- image attach ----------
  $("image").addEventListener("change", () => {
    const file = $("image").files[0];
    if (!file) { state.image = null; $("attachment").classList.add("hidden"); return; }
    if (file.size > 5 * 1024 * 1024) { alert("התמונה גדולה מ-5MB."); $("image").value = ""; return; }
    const reader = new FileReader();
    reader.onload = () => {
      const dataUrl = reader.result;
      state.image = { media_type: file.type, data: dataUrl.split(",")[1], dataUrl, name: file.name };
      $("attachment").textContent = `מצורף: ${file.name}`; $("attachment").classList.remove("hidden");
    };
    reader.readAsDataURL(file);
  });

  // ---------- send + stream ----------
  $("input").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("composer").requestSubmit(); } });
  $("input").addEventListener("input", () => { const t = $("input"); t.style.height = "auto"; t.style.height = Math.min(t.scrollHeight, 160) + "px"; });

  $("composer").addEventListener("submit", async (e) => {
    e.preventDefault();
    if (state.streaming) return;
    const text = $("input").value.trim();
    if (!text && !state.image) return;
    const image = state.image;
    $("input").value = ""; $("input").style.height = "auto"; state.image = null; $("image").value = ""; $("attachment").classList.add("hidden");
    if ($("messages").querySelector(".empty")) $("messages").innerHTML = "";
    addBubble("user", text || "(צילום סיכום פגישה)", { imageDataUrl: image ? image.dataUrl : null });

    const bot = addBubble("assistant", "");
    const body = bot.querySelector(".body"); body.classList.add("cursor");
    const meta = document.createElement("div"); meta.className = "meta"; bot.querySelector(".msg-body").appendChild(meta);
    state.streaming = true; $("send").disabled = true; setStatus("חושב…");
    let full = "";
    try {
      const res = await fetch("/api/chat", {
        method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ conversation_id: state.current, message: text, image: image ? { media_type: image.media_type, data: image.data } : null }),
      });
      if (!res.ok) { let d = res.statusText; try { d = (await res.json()).detail || d; } catch (_) {} throw new Error(d); }
      const reader = res.body.getReader(); const decoder = new TextDecoder(); let buffer = "";
      while (true) {
        const { value, done } = await reader.read(); if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let idx;
        while ((idx = buffer.indexOf("\n\n")) >= 0) {
          const raw = buffer.slice(0, idx); buffer = buffer.slice(idx + 2);
          const line = raw.split("\n").find((l) => l.startsWith("data: ")); if (!line) continue;
          const ev = JSON.parse(line.slice(6));
          if (ev.type === "meta") { state.current = ev.conversation_id; if (ev.title) $("conv-title").textContent = ev.title; }
          else if (ev.type === "text") { full += ev.text; body.innerHTML = render(full); scrollDown(); }
          else if (ev.type === "tool") {
            const label = TOOL_HE[ev.name] || ev.name;
            if (ev.status === "start") { setStatus(`${label}…`); }
            else { const c = document.createElement("span"); c.className = "chip tool"; c.title = ev.summary || ""; c.textContent = `✓ ${label}`; meta.appendChild(c); }
          }
          else if (ev.type === "done") { const u = ev.usage || {}; const c = document.createElement("span"); c.className = "chip"; c.textContent = `${u.input_tokens || 0} טוקנים פנימה · ${u.output_tokens || 0} החוצה · $${(ev.cost_usd || 0).toFixed(4)}`; meta.appendChild(c); }
          else if (ev.type === "error") { full += `\n\n**שגיאה:** ${ev.message}`; body.innerHTML = render(full); }
        }
      }
    } catch (err) {
      full += `\n\n**שגיאה:** ${err.message}`; body.innerHTML = render(full);
    } finally {
      body.classList.remove("cursor"); state.streaming = false; $("send").disabled = false; setStatus("");
      await loadConversationsQuiet();
    }
  });
  async function loadConversationsQuiet() { try { state.conversations = await api("/api/conversations"); renderConversations(); } catch (_) {} }

  // ---------- leads panel ----------
  function stageCell(r) {
    if (!r.stage) return '<span class="stage none">ללא אבחון</span>';
    return `<span class="stage ${r.stage}">${escapeHtml(r.stage_he)}</span><span class="score">${r.total_score}</span>`;
  }
  async function loadLeads() {
    $("lead-rows").innerHTML = `<tr><td colspan="4"><small>טוען…</small></td></tr>`;
    const rows = await api("/api/leads");
    $("lead-rows").innerHTML = rows.map((r) => `<tr>
        <td class="date">${escapeHtml(r.lead_date || "")}</td>
        <td><strong>${escapeHtml(r.business_name)}</strong><small>${escapeHtml(r.industry || "")}</small></td>
        <td>${stageCell(r)}</td>
        <td><span class="badge ${r.record_status}">${RECORD_HE[r.record_status] || r.record_status}</span>${r.hot ? '<span class="badge hot">חם</span>' : ""}<span class="pipeline">${STATUS_HE[r.pipeline_status] || ""}</span></td>
      </tr>`).join("") || `<tr><td colspan="4"><small>אין עדיין לידים.</small></td></tr>`;
  }
  $("toggle-leads").addEventListener("click", async () => { $("leads").classList.toggle("hidden"); if (!$("leads").classList.contains("hidden")) await loadLeads().catch(() => {}); });
  $("close-leads").addEventListener("click", () => $("leads").classList.add("hidden"));

  // ---------- boot ----------
  (async () => {
    try { state.user = await api("/api/me"); showApp(); await loadConversations(); }
    catch (_) { showLogin(); }
  })();
})();
