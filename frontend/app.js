// PETIT chat frontend — talks to the FastAPI backend at /api/chat.

const messagesEl = document.getElementById("messages");
const formEl = document.getElementById("chat-form");
const inputEl = document.getElementById("input");
const sendEl = document.getElementById("send");
const statusEl = document.getElementById("status");
const chatModelSelectEl = document.getElementById("chat-model-select");
const agentModelSelectEl = document.getElementById("agent-model-select");
const modelRoutingStateEl = document.getElementById("model-routing-state");

// Conversation history restored from SQLite and sent back to the model.
const history = [];
const sessionId = localStorage.getItem("petit_session_id") || crypto.randomUUID();
localStorage.setItem("petit_session_id", sessionId);
let modelRoutingSnapshot = null;

function freshnessLabel(status, label) {
  if (!status || !status.configured) return `${label}: 未使用`;
  if (status.error) return `${label}: ${status.stale ? "古いキャッシュ" : "同期失敗"}`;
  return `${label}: ${status.stale ? "古いキャッシュ" : "最新"}`;
}

function addMessage(role, text, { tools, error, actions, modelRoute } = {}) {
  const wrap = document.createElement("div");
  wrap.className = `msg msg--${role}`;

  const bubble = document.createElement("div");
  bubble.className = "bubble" + (error ? " bubble--error" : "");
  bubble.textContent = text;
  wrap.appendChild(bubble);

  if (tools && tools.length) {
    const t = document.createElement("div");
    t.className = "tools";
    t.textContent = "🔧 " + tools.map((x) => x.name).join(", ");
    bubble.appendChild(t);
  }

  if (actions && actions.length) {
    const controls = document.createElement("div");
    controls.className = "action-confirm";
    if (actions[0].name === "add_schedule") {
      const args = actions[0].arguments || {};
      const preview = document.createElement("dl");
      preview.className = "action-preview";
      const fields = [
        ["予定タイトル", args.title],
        ["開始日時", args.start_time],
        ["終了日時", args.end_time || "未指定"],
        ["場所", args.location || "未指定"],
        ["説明", args.description || "未指定"],
        ["保存先", "PETITローカル予定"],
      ];
      for (const [label, value] of fields) {
        const term = document.createElement("dt");
        const detail = document.createElement("dd");
        term.textContent = label;
        detail.textContent = value;
        preview.append(term, detail);
      }
      controls.appendChild(preview);
    }
    const approve = document.createElement("button");
    approve.type = "button";
    approve.textContent = "実行する";
    const cancel = document.createElement("button");
    cancel.type = "button";
    cancel.textContent = "キャンセル";
    controls.append(approve, cancel);
    bubble.appendChild(controls);
    approve.addEventListener("click", () => decideAction(actions[0].approval_id, true, controls));
    cancel.addEventListener("click", () => decideAction(actions[0].approval_id, false, controls));
  }

  if (modelRoute && modelRoute.observability) {
    const o = modelRoute.observability;
    const details = document.createElement("details");
    details.className = "turn-details";
    const summary = document.createElement("summary");
    const fallback = o.fallback ? " · Agentフォールバック" : "";
    summary.textContent = `詳細 · ${o.actual_route || "instant"}${fallback}`;
    const body = document.createElement("div");
    body.textContent = [
      `経路: ${o.actual_route || "instant"}`,
      `モデル: ${o.model || "LLM未使用"}`,
      `プロファイル: ${o.profile || "なし"}`,
      `Provider: ${o.provider || "なし"}`,
      `ツール: ${(o.tools || []).join(", ") || "なし"}`,
      freshnessLabel(o.notion_sync, "Notion"),
      freshnessLabel(o.calendar_sync, "Calendar"),
      `BRAIN: ${o.brain_references || 0}件`,
      `Memory: ${o.memory_references || 0}件`,
      `LLM: ${o.llm_calls || 0}回 / Embedding: ${o.embedding_calls || 0}回`,
      `処理時間: ${((o.elapsed_ms || 0) / 1000).toFixed(1)}秒`,
    ].join("\n");
    details.append(summary, body);
    bubble.appendChild(details);
  }

  messagesEl.appendChild(wrap);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return bubble;
}

async function decideAction(approvalId, approved, controls) {
  for (const button of controls.querySelectorAll("button")) button.disabled = true;
  try {
    const res = await fetch(`/api/actions/${approvalId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ approved }),
    });
    const data = await res.json();
    if (data.error) {
      addMessage("assistant", "⚠️ " + data.error, { error: true });
      return;
    }
    addMessage("assistant", data.reply, { tools: data.used_tools });
    history.push({ role: "assistant", content: data.reply });
  } catch (e) {
    addMessage("assistant", "⚠️ 確認操作に失敗しました: " + e.message, { error: true });
  }
}

function setTyping(on) {
  let el = document.getElementById("typing");
  if (on) {
    if (!el) {
      el = document.createElement("div");
      el.id = "typing";
      el.className = "msg msg--assistant";
      el.innerHTML = '<div class="bubble typing">考え中…</div>';
      messagesEl.appendChild(el);
      messagesEl.scrollTop = messagesEl.scrollHeight;
    }
  } else if (el) {
    el.remove();
  }
}

function setModelRoutingBusy(on) {
  if (chatModelSelectEl) chatModelSelectEl.disabled = on;
  if (agentModelSelectEl) agentModelSelectEl.disabled = on;
}

function optionLabel(option) {
  if (option.configured) return option.label;
  return `${option.label}（未設定）`;
}

function renderRouteSelect(route, selectEl, snapshot) {
  if (!selectEl) return;
  const routeState = snapshot.routes && snapshot.routes[route];
  if (!routeState) return;
  selectEl.replaceChildren();
  for (const option of routeState.options || []) {
    const element = document.createElement("option");
    element.value = option.profile;
    element.textContent = optionLabel(option);
    element.disabled = !option.configured;
    selectEl.appendChild(element);
  }
  selectEl.value = routeState.selected;
  selectEl.title = routeState.active && routeState.active.external
    ? "外部APIへ会話内容が送信されます"
    : "ローカルPC内で処理します";
}

function renderModelRouting(snapshot) {
  modelRoutingSnapshot = snapshot;
  renderRouteSelect("chat", chatModelSelectEl, snapshot);
  renderRouteSelect("agent", agentModelSelectEl, snapshot);
}

async function loadModelRouting() {
  if (!chatModelSelectEl || !agentModelSelectEl) return;
  setModelRoutingBusy(true);
  try {
    const res = await fetch("/api/model-routing", { cache: "no-store" });
    const data = await res.json();
    if (!res.ok || data.error) throw new Error(data.error || `HTTP ${res.status}`);
    renderModelRouting(data);
    modelRoutingStateEl.textContent = "";
  } catch (e) {
    modelRoutingStateEl.textContent = "モデル設定を取得できません";
    modelRoutingStateEl.className = "model-routing__state model-routing__state--error";
  } finally {
    setModelRoutingBusy(false);
  }
}

async function updateModelRouting(route, profile) {
  const previous = modelRoutingSnapshot && modelRoutingSnapshot.selections
    ? modelRoutingSnapshot.selections[route]
    : "local";
  setModelRoutingBusy(true);
  modelRoutingStateEl.textContent = "切り替え中…";
  modelRoutingStateEl.className = "model-routing__state";
  try {
    const res = await fetch("/api/model-routing", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ [route]: profile }),
    });
    const data = await res.json();
    if (!res.ok || data.error) throw new Error(data.error || `HTTP ${res.status}`);
    renderModelRouting(data);
    const active = data.routes[route].active;
    modelRoutingStateEl.textContent = `${route === "chat" ? "Chat" : "Agent"}を${active.label}へ切替済み`;
    await checkHealth();
  } catch (e) {
    const selectEl = route === "chat" ? chatModelSelectEl : agentModelSelectEl;
    if (selectEl) selectEl.value = previous;
    modelRoutingStateEl.textContent = "⚠️ " + e.message;
    modelRoutingStateEl.className = "model-routing__state model-routing__state--error";
  } finally {
    setModelRoutingBusy(false);
  }
}

if (chatModelSelectEl) {
  chatModelSelectEl.addEventListener("change", () => updateModelRouting("chat", chatModelSelectEl.value));
}
if (agentModelSelectEl) {
  agentModelSelectEl.addEventListener("change", () => updateModelRouting("agent", agentModelSelectEl.value));
}

async function acknowledgeJobs(ids) {
  if (!ids.length) return;
  await fetch("/api/jobs/ack", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ job_ids: ids, session_id: sessionId }),
  });
}

async function pollJobs() {
  try {
    const res = await fetch(`/api/jobs?limit=10&session_id=${encodeURIComponent(sessionId)}`);
    const data = await res.json();
    const delivered = [];
    for (const job of data.jobs || []) {
      if (job.status === "done") {
        const text = job.result_text || "調べ終わったけど、結果が空でした。";
        addMessage("assistant", "調べ終わったよ。\n" + text);
        history.push({ role: "assistant", content: text });
        delivered.push(job.id);
      } else if (job.status === "failed") {
        const text = "調べものが失敗しました: " + (job.error || "unknown error");
        addMessage("assistant", text, { error: true });
        history.push({ role: "assistant", content: text });
        delivered.push(job.id);
      }
    }
    await acknowledgeJobs(delivered);
  } catch (e) {
    // Background job polling should not interrupt chat.
  }
}

async function checkHealth() {
  try {
    const res = await fetch("/api/health", { cache: "no-store" });
    const data = await res.json();
    const chat = data.chat_model || {};
    const agent = data.agent_model || {};
    if (chat.server_ok && agent.server_ok) {
      statusEl.textContent = `Chat: ${chat.label || chat.model} / Agent: ${agent.label || agent.model}`;
      statusEl.className = "status status--ok";
    } else if (chat.server_ok) {
      statusEl.textContent = "Chat接続OK / Agent未接続";
      statusEl.className = "status status--unknown";
    } else {
      statusEl.textContent = `Chat未接続${chat.label ? ` (${chat.label})` : ""}`;
      statusEl.className = "status status--bad";
    }
  } catch (e) {
    statusEl.textContent = "サーバー未接続";
    statusEl.className = "status status--bad";
  }
}

async function sendMessage(text) {
  const requestId = crypto.randomUUID();
  addMessage("user", text);

  setTyping(true);
  sendEl.disabled = true;

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, history, request_id: requestId, session_id: sessionId }),
    });
    const data = await res.json();
    setTyping(false);

    if (data.request_id !== requestId) {
      throw new Error("応答のrequest IDが一致しません");
    }
    if (data.error) {
      addMessage("assistant", "⚠️ " + data.error, { error: true });
    } else {
      history.push({ role: "user", content: text });
      if (data.reply) {
        addMessage("assistant", data.reply, { tools: data.used_tools, actions: data.pending_actions, modelRoute: data.model_route });
        history.push({ role: "assistant", content: data.reply });
      }
    }
  } catch (e) {
    setTyping(false);
    addMessage("assistant", "⚠️ 通信に失敗しました: " + e.message, { error: true });
  } finally {
    sendEl.disabled = false;
    inputEl.focus();
  }
}

formEl.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = inputEl.value.trim();
  if (!text) return;
  inputEl.value = "";
  inputEl.style.height = "auto";
  sendMessage(text);
});

// Enter to send, Shift+Enter for newline.
inputEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    formEl.requestSubmit();
  }
});

// Auto-grow the textarea.
inputEl.addEventListener("input", () => {
  inputEl.style.height = "auto";
  inputEl.style.height = Math.min(inputEl.scrollHeight, 160) + "px";
});

function removeStaticGreeting() {
  const greeting = document.getElementById("greeting");
  if (greeting) greeting.remove();
}

async function restoreHistory() {
  try {
    const res = await fetch(`/api/conversations?limit=10&session_id=${encodeURIComponent(sessionId)}`);
    const data = await res.json();
    const rows = data.conversations || [];
    if (!rows.length) return false;
    removeStaticGreeting();
    for (const row of rows) {
      if (row.user_text) {
        addMessage("user", row.user_text);
        history.push({ role: "user", content: row.user_text });
      }
      if (row.assistant_text) {
        addMessage("assistant", row.assistant_text);
        history.push({ role: "assistant", content: row.assistant_text });
      }
    }
    return true;
  } catch (e) {
    return false;
  }
}

// On a new session, let PETIT speak first. Existing sessions restore SQLite history.
async function loadOpener() {
  try {
    const res = await fetch("/api/proactive");
    const data = await res.json();
    if (data && data.message) {
      const greeting = document.getElementById("greeting");
      const bubble = greeting && greeting.querySelector(".bubble");
      if (bubble) bubble.textContent = data.message;
      history.push({ role: "assistant", content: data.message });
    }
  } catch (e) {
    // Keep the static greeting if the opener can't be fetched.
  }
}

async function initialize() {
  await loadModelRouting();
  await checkHealth();
  const restored = await restoreHistory();
  if (!restored) await loadOpener();
  await pollJobs();
  inputEl.focus();
}

setInterval(checkHealth, 60000);
setInterval(pollJobs, 3000);
initialize();
