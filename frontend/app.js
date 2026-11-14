const $ = (s) => document.querySelector(s);
const BASE = (window.API_BASE || "").replace(/\/$/, "");
const MANDATORY = ["email","college","degree","branch","graduation_year","cgpa","preferred_location","available_from","internship_duration_months"];
const LABEL = { email:"Email", college:"College", degree:"Degree", branch:"Branch", graduation_year:"Grad year", cgpa:"CGPA", preferred_location:"Location", available_from:"Start date", internship_duration_months:"Duration" };
const SHOW = ["full_name","email","college","degree","branch","graduation_year","cgpa","preferred_location","available_from","internship_duration_months","linkedin_url","github_url","skills","collection_status","attempt_count","last_contacted_at","notes"];
let token = null, busy = false, idleTimer = null, selected = null, last = null;
const IDLE_MS = 5 * 60 * 1000;

async function api(path, body) {
  let r;
  try { r = await fetch(BASE + "/api/" + path, { method: body ? "POST" : "GET", headers: { "content-type": "application/json" }, body: body ? JSON.stringify(body) : undefined }); }
  catch (e) { throw new Error("Can't reach the server. Check your connection."); }
  const j = await r.json().catch(() => ({ error: "Bad response from server" }));
  if (!r.ok) throw new Error(j.error || r.statusText);
  return j;
}
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const fmt = (v) => (v === null || v === undefined || v === "" ? "—" : typeof v === "object" ? JSON.stringify(v) : String(v));
function toast(t) { const e = $("#toast"); e.textContent = t; e.hidden = false; clearTimeout(toast.t); toast.t = setTimeout(() => (e.hidden = true), 3200); }

/* theme */
const root = document.documentElement;
try { root.dataset.theme = localStorage.getItem("theme") || (matchMedia("(prefers-color-scheme:dark)").matches ? "dark" : "light"); } catch { }
$("#theme").onclick = () => { root.dataset.theme = root.dataset.theme === "dark" ? "light" : "dark"; try { localStorage.setItem("theme", root.dataset.theme); } catch { } };

async function health() {
  const el = $("#health");
  try {
    const h = await api("health");
    const ok = h.llm.configured && h.candidate_api_auth === "ok";
    el.textContent = ok ? `● Ready · ${h.llm.model.split("/").pop()}` : !h.llm.configured ? "LLM key missing" : "Candidate API: " + h.candidate_api_auth;
    el.className = "pill " + (ok ? "ok" : "bad");
  } catch (e) { el.textContent = "Server unreachable"; el.className = "pill bad"; }
}
async function loadQueue() {
  try {
    const q = await api("queue"), f = q.funnel;
    $("#funnel").innerHTML = `<div class="fn"><b>${q.completion_rate}%</b><span>complete</span></div>` + ["completed","in_progress","pending","no_answer","refused","needs_human"].filter((k) => f[k]).map((k) => `<span class="chip ${k}">${f[k]} ${k.replace("_", " ")}</span>`).join("");
    $("#queue").innerHTML = q.queue.slice(0, 5).map((i) => `<button class="qi ${i.lane}" data-id="${esc(i.id)}"><div class="r"><b>${esc(i.name)}</b><span class="act">${esc(i.action)}</span></div><small>${esc(i.reason)}</small></button>`).join("") || '<p class="muted pad">Nothing to do. Pipeline is clear.</p>';
  } catch (e) { $("#queue").innerHTML = ""; }
}
async function loadCands() {
  const box = $("#cands");
  try {
    const { candidates } = await api("candidates");
    box.innerHTML = candidates.map((c) => {
      const pct = Math.round(((9 - Math.min(9, c.todo.filter((f) => MANDATORY.includes(f)).length)) / 9) * 100);
      return `<button class="cand ${c.id === selected ? "sel" : ""}" data-id="${esc(c.id)}">
      <div class="r"><b>${esc(c.name)}</b><span class="chip ${esc(c.status)}">${esc(c.status.replace("_", " "))}</span></div>
      <div class="bar"><i style="width:${pct}%"></i></div>
      <small>${esc(c.id)} · ${c.todo.length ? c.todo.length + " to collect" : "complete"} · attempts ${c.attempts ?? 0}</small></button>`;
    }).join("") || '<p class="muted pad">No candidates</p>';
  } catch (e) { box.innerHTML = `<p class="muted pad">${esc(e.message)}</p>`; }
}

function addMsg(role, text, ts) {
  const d = document.createElement("div");
  d.className = "m " + role;
  const t = ts ? new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "";
  d.innerHTML = esc(text) + (t ? `<time>${t}</time>` : "");
  $("#msgs").appendChild(d);
  $("#msgs").scrollTop = 1e9;
}
function typing(on) {
  document.querySelector(".typing")?.remove();
  if (on) { const d = document.createElement("div"); d.className = "typing"; d.innerHTML = "<i></i><i></i><i></i>"; $("#msgs").appendChild(d); $("#msgs").scrollTop = 1e9; }
}
function setRing(done, total) {
  const pct = total ? (done / total) * 100 : 0;
  $("#ringfg").setAttribute("stroke-dasharray", `${pct} 100`); $("#ringfg").setAttribute("pathLength", "100");
  $("#ringtxt").textContent = `${done}/${total}`; $("#ring").classList.toggle("done", done === total);
}
function renderQuality(v) {
  const q = v.quality, el = $("#qbar");
  el.hidden = false;
  const vb = Object.entries(v.verifications || {}).map(([f, d]) => `<span class="vb ${esc(d.status)}" title="${esc(d.reason)}">${d.status === "verified" ? "✓ verified" : d.status === "bad" ? "✗ failed check" : "⚠ unverified"} · ${esc(f.replace("_url", ""))}</span>`).join("");
  el.innerHTML = `<span class="qs">Quality <b>${q.score}</b>/100 <span class="g ${q.grade}">${q.grade}</span></span>${vb}`;
}
function renderChips(v) {
  const todo = new Set(v.progress.todo);
  $("#chips").hidden = false;
  $("#chips").innerHTML = MANDATORY.map((f) => `<span class="fc ${todo.has(f) ? "" : "ok"}">${LABEL[f]}</span>`).join("");
  setRing(v.progress.done - 2 < 0 ? 0 : v.progress.done - 2, 9);   // full_name + phone are always present
}
function render(v) {
  token = v.token; last = v;
  $("#msgs").innerHTML = "";
  v.transcript.forEach((m) => addMsg(m.role, m.text, m.ts));
  $("#ch-name").textContent = v.record.full_name;
  $("#ch-sub").textContent = `${v.candidate_id} · ${v.ended ? "chat ended" : "online"}${v.stalls ? " · re-anchoring (" + v.stalls + ")" : ""}`;
  $("#leave").hidden = v.ended;
  $("#text").disabled = $("#composer button").disabled = v.ended;
  renderChips(v); renderQuality(v);
  const b = $("#banner");
  if (v.ended) {
    const o = v.outcome, fu = v.brief?.follow_up_at;
    b.hidden = false;
    b.className = "banner " + (o === "completed" ? "completed" : o === "needs_human" || o === "refused" ? "bad" : "warn");
    b.innerHTML = `<b>Outcome: ${esc(o.replace("_", " "))}</b>` + (fu ? ` · follow-up scheduled ${esc(new Date(fu).toLocaleString())}` : "") + (v.final_write_ok === false ? " · ⚠ final database write failed" : "");
  } else b.hidden = true;
  renderTrace(v.trace); renderRecord(v); renderPlan(v.plan); renderBrief(v);
  clearTimeout(idleTimer);
  if (!v.ended) idleTimer = setTimeout(() => leave("no reply / idle timeout"), IDLE_MS);
}
function renderTrace(tr) {
  const out = [];
  for (const e of tr) {
    if (e.t === "tool") {
      const rs = (e.result && e.result.results) || [];
      const bad = e.result && (e.result.ok === false || rs.some((r) => r.status !== "ok" && r.status !== "unchanged"));
      out.push(`<div class="ev tool ${bad ? "warn" : ""}"><b>TOOL · ${esc(e.name)}${bad ? " · rejected or partial" : ""}</b><pre>${esc(JSON.stringify(e.args, null, 1))}\n→ ${esc(JSON.stringify(e.result, null, 1))}</pre></div>`);
    } else if (e.t === "db") {
      if (e.method === "GET" && !e.attempt && e.status === 200) out.push(`<div class="ev db"><b>DB · GET ${esc(e.path)} → ${e.status} · ${e.ms}ms</b></div>`);
      else out.push(`<div class="ev db ${e.status >= 400 || e.status === 0 ? "bad" : ""}"><b>DB · ${esc(e.method)} ${esc(e.path)} → ${e.status} · ${e.ms}ms</b>${e.request ? `<pre>${esc(JSON.stringify(e.request, null, 1))}</pre>` : ""}</div>`);
    } else if (e.t === "guardrail_reply_blocked") out.push(`<div class="ev warn"><b>GUARDRAIL · reply blocked & regenerated</b>${esc(e.reason)}</div>`);
    else if (e.t === "fallback_reply_used") out.push(`<div class="ev warn"><b>GUARDRAIL · safe fallback message used</b>${esc(e.reason)}</div>`);
    else if (e.t === "verification") out.push(`<div class="ev ${e.status === "verified" ? "db" : "warn"}"><b>VERIFY · ${esc(e.field)} · ${esc(e.status)}</b>${esc(e.reason)}</div>`);
    else if (e.t === "conflict_resolved") out.push(`<div class="ev warn"><b>409 conflict · re-read & merged</b>${esc(JSON.stringify(e.dropped))}</div>`);
    else if (e.t === "llm") { if (e.model) out.push(`<div class="ev"><b>LLM · ${esc(e.model)}</b>${e.tool_calls?.length ? "→ " + esc(e.tool_calls.join(", ")) : "reply"}${e.usage?.total_tokens ? " · " + e.usage.total_tokens + " tok" : ""}</div>`); }
    else if (e.t === "llm_error" || e.t === "tool_format_error") out.push(`<div class="ev bad"><b>${esc(e.t)}</b>${esc(e.error || e.failed || "")}</div>`);
    else if (e.t === "abandoned") out.push(`<div class="ev warn"><b>CHAT ABANDONED → ${esc(e.outcome)}</b>${esc(e.reason)}</div>`);
  }
  const box = $("#t-act"); box.innerHTML = out.join("") || '<p class="muted pad">No activity yet.</p>'; box.scrollTop = 1e9;
}
function renderRecord(v) {
  const rows = SHOW.map((f) => {
    const a = v.initial[f], b = v.record[f], changed = JSON.stringify(a) !== JSON.stringify(b);
    const miss = (b === null || b === "") && MANDATORY.includes(f);
    const ev = v.saved?.[f]?.evidence;
    return `<div class="row ${changed ? "chg" : miss ? "miss" : ""}"><div class="k"><span>${f}</span>${changed ? "<span>written ✓</span>" : ""}</div><div class="v">${changed ? `<s>${esc(fmt(a))}</s> → ` : ""}${esc(fmt(b))}</div>${ev ? `<q>${esc(ev)}</q>` : ""}</div>`;
  });
  $("#t-rec").innerHTML = `<div class="rec">${rows.join("")}</div><p class="muted pad">Green = written this chat, with the candidate's own words as proof. Red = still missing.</p>`;
}
function renderPlan(p) {
  const li = (a) => a.length ? a.map((x) => `<li>${esc(typeof x === "string" ? x : `${x.field}: ${x.value} — ${x.reason}`)}</li>`).join("") : "<li class='muted'>none</li>";
  $("#t-plan").innerHTML = `<h4>Missing</h4><ul>${li(p.missing)}</ul><h4>Existing data that looks wrong</h4><ul>${li(p.invalid)}</ul><h4>Needs confirmation</h4><ul>${li(p.confirm)}</ul><h4>Auto-normalised (no question needed)</h4><ul>${li(Object.entries(p.autofix).map(([k, v]) => `${k} → ${v}`))}</ul><h4>Optional, ask once</h4><ul>${li(p.optional_missing)}</ul>`;
}
function qualityHtml(q) {
  const parts = Object.entries(q.parts).map(([k, n]) => `<div class="k"><span>${k}</span><span>${n}</span></div>`).join("");
  return `<h4>Application quality: ${q.score}/100 (${q.grade})</h4><div class="bar-s"><i style="width:${q.score}%"></i></div><div class="row">${parts}</div>` + (q.risk.length ? `<h4>Risk flags for a human</h4><ul>${q.risk.map((r) => `<li>${esc(r)}</li>`).join("")}</ul>` : '<p class="muted pad">No risk flags.</p>');
}
function renderBrief(v) {
  const b = v.brief;
  if (!b) { $("#t-brief").innerHTML = qualityHtml(v.quality) + '<p class="muted pad">The full recruiter hand-off brief appears when the chat ends.</p>'; return; }
  $("#t-brief").innerHTML = qualityHtml(v.quality) + `<dl class="kv"><dt>Outcome</dt><dd><span class="chip ${esc(b.outcome)}">${esc(b.outcome)}</span></dd><dt>Collected</dt><dd>${esc(b.collected.join(", ") || "nothing")}</dd><dt>Still needed</dt><dd>${esc(b.still_needed.join(", ") || "nothing")}</dd><dt>Follow-up</dt><dd>${b.follow_up_at ? esc(new Date(b.follow_up_at).toLocaleString()) : "—"}</dd><dt>Attempts</dt><dd>${esc(b.attempt_count)}</dd><dt>Turns</dt><dd>${esc(b.turns)}</dd></dl><h4>Note written to the database</h4><div class="row"><div class="v">${esc(b.notes_tail)}</div></div><h4>Models used</h4><div class="row"><div class="v">${esc(Object.entries(v.models || {}).map(([m, n]) => `${m}: ${n} calls`).join(" · ") || "—")}</div></div>`;
}

async function start(id) {
  if (busy || !id) return;
  busy = true; selected = id; token = null;
  $("#msgs").innerHTML = ""; typing(true); $("#banner").hidden = true; $("#chips").hidden = true;
  setPanel("p-chat");
  try {
    const v = await api("start", { candidate_id: id });
    typing(false);
    if (v.no_action) {
      $("#msgs").innerHTML = `<div class="empty"><div class="big">✅</div><b>${esc(v.record.full_name)}</b> already has a complete, valid record.<p>No conversation was started and nobody was contacted. Status set to <b>completed</b>.</p></div>`;
      $("#ch-name").textContent = v.record.full_name; $("#ch-sub").textContent = id + " · nothing to collect";
      setRing(9, 9); renderTrace(v.trace); renderRecord(v); renderPlan(v.plan);
      $("#text").disabled = true; $("#leave").hidden = true;
    } else { render(v); $("#text").focus(); }
  } catch (e) { typing(false); $("#msgs").innerHTML = `<div class="empty"><div class="big">⚠️</div>${esc(e.message)}</div>`; }
  busy = false; loadCands(); loadQueue();
}
async function send(text) {
  if (busy || !token) return;
  busy = true; addMsg("candidate", text, new Date()); typing(true);
  $("#text").value = ""; $("#text").disabled = true;
  try { render(await api("message", { token, text })); }
  catch (e) { typing(false); addMsg("sys", "⚠ " + e.message); $("#text").disabled = false; }
  busy = false;
  if (last && !last.ended) $("#text").focus();
  loadCands();
}
async function leave(reason) {
  if (!token) return;
  try { render(await api("leave", { token, reason })); loadCands(); } catch (e) { toast(e.message); }
}
function setPanel(id) {
  document.querySelectorAll(".panel").forEach((p) => p.classList.toggle("show", p.id === id));
  document.querySelectorAll("#mtabs button").forEach((b) => b.classList.toggle("on", b.dataset.p === id));
}

$("#queue").addEventListener("click", (e) => { const b = e.target.closest(".qi"); if (b && !b.classList.contains("human")) start(b.dataset.id); });
$("#cands").addEventListener("click", (e) => { const b = e.target.closest(".cand"); if (b) start(b.dataset.id); });
$("#manual").addEventListener("submit", (e) => { e.preventDefault(); start($("#cid").value.trim()); });
$("#composer").addEventListener("submit", (e) => { e.preventDefault(); const t = $("#text").value.trim(); if (t) send(t); });
$("#leave").onclick = () => leave("candidate left the chat");
$("#refresh").onclick = () => { loadCands(); loadQueue(); health(); };
$("#reset").onclick = async () => { if (confirm("Reset your workspace to the original data?")) { await api("reset", {}); token = null; $("#msgs").innerHTML = '<div class="empty"><div class="big">↺</div>Workspace reset.</div>'; $("#chips").hidden = true; loadCands(); toast("Workspace reset"); } };
document.querySelectorAll(".itabs button").forEach((b) => b.addEventListener("click", () => {
  document.querySelectorAll(".itabs button,.tab").forEach((x) => x.classList.remove("on")); b.classList.add("on"); $("#" + b.dataset.t).classList.add("on");
}));
document.querySelectorAll("#mtabs button").forEach((b) => b.addEventListener("click", () => setPanel(b.dataset.p)));
window.addEventListener("pagehide", () => { if (token && last && !last.ended) navigator.sendBeacon(BASE + "/api/leave", new Blob([JSON.stringify({ token, reason: "candidate closed the page" })], { type: "text/plain" })); });
if (matchMedia("(max-width:760px)").matches) setPanel("p-list");
health(); loadCands(); loadQueue();

/* voice input (Web Speech API; Chrome/Edge). Spoken numbers are understood by the agent. */
(() => {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition, mic = $("#mic");
  if (!SR) { mic.style.display = "none"; return; }
  let rec = null;
  mic.onclick = () => {
    if (rec) { rec.stop(); return; }
    rec = new SR(); rec.lang = "en-IN"; rec.interimResults = true;
    rec.onresult = (e) => { $("#text").value = [...e.results].map((r) => r[0].transcript).join(" "); };
    rec.onend = () => { mic.classList.remove("rec"); rec = null; if ($("#text").value.trim() && !$("#text").disabled) $("#composer").requestSubmit(); };
    rec.onerror = () => { mic.classList.remove("rec"); rec = null; toast("Couldn't hear that. Try again."); };
    mic.classList.add("rec"); rec.start();
  };
})();
