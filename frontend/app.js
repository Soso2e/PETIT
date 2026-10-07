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
let activeRequestId = null;
let agentOperationActive = false;
let jobsPollInFlight = false;
const desktopChatState = window.PetitDesktopChatState;
const draftStateEl = document.getElementById('draft-state');
const waitStopEl = document.getElementById('chat-wait-stop');
let healthInFlight = false;
let desktopBackground = false;
async function chatJson(url, options) {
  if (desktopChatState) return desktopChatState.request(url, options);
  const response = await fetch(url, options);
  return response.json();
}
function saveDraft(pending = false, text = inputEl.value) {
  if (!desktopChatState) return;
  desktopChatState.save(text, pending);
  if (draftStateEl) draftStateEl.textContent = text && !pending ? '下書きをこの端末に保存' : '';
}
if (desktopChatState) {
  const saved = desktopChatState.read();
  if (saved?.text) {
    inputEl.value = saved.text;
    if (draftStateEl) draftStateEl.textContent = saved.pending ? '応答が未確認です。履歴と操作結果を確認してから送信してください。' : '下書きを復元しました';
  }
  inputEl.addEventListener('input', () => saveDraft());
  if (waitStopEl) waitStopEl.onclick = () => desktopChatState.stop();
}

function freshnessLabel(status, label) {
  if (!status || !status.configured) return `${label}: 未使用`;
  if (status.error) return `${label}: ${status.stale ? "古いキャッシュ" : "同期失敗"}`;
  return `${label}: ${status.stale ? "古いキャッシュ" : "最新"}`;
}

function addMessage(role, text, { tools, error, actions, modelRoute, silent = false } = {}) {
  const wrap = document.createElement("div");
  wrap.className = `msg msg--${role}`;
  if (silent) wrap.dataset.voiceSilent = "1";

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
    } else if (actions[0].name === "complete_task") {
      const args = actions[0].arguments || {};
      const preview = document.createElement("dl");
      preview.className = "action-preview";
      const term = document.createElement("dt");
      const detail = document.createElement("dd");
      term.textContent = "完了にするタスク";
      detail.textContent = args.title_query || `ID: ${args.task_id}`;
      preview.append(term, detail);
      controls.appendChild(preview);
    }
    const approve = document.createElement("button");
    approve.type = "button";
    approve.textContent = actions[0].name === "complete_task" ? "完了にする" : "実行する";
    const cancel = document.createElement("button");
    cancel.type = "button";
    cancel.textContent = actions[0].name === "complete_task" ? "やめる" : "キャンセル";
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
  agentOperationActive = approved;
  if (approved) setTyping(true, "確認された内容を実行してるよ…");
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
  } finally {
    agentOperationActive = false;
    setTyping(false);
  }
}

function setTyping(on, text = "考え中…") {
  let el = document.getElementById("typing");
  if (on) {
    if (!el) {
      el = document.createElement("div");
      el.id = "typing";
      el.className = "msg msg--assistant";
      const bubble = document.createElement("div");
      bubble.className = "bubble typing";
      el.appendChild(bubble);
      messagesEl.appendChild(el);
    }
    const bubble = el.querySelector(".bubble");
    if (bubble) bubble.textContent = text || "考え中…";
    messagesEl.scrollTop = messagesEl.scrollHeight;
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
    void checkHealth();
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
  if (desktopChatState && (desktopBackground || document.hidden)) return;
  if (jobsPollInFlight) return;
  jobsPollInFlight = true;
  try {
    const data = await chatJson(`/api/jobs?limit=20&session_id=${encodeURIComponent(sessionId)}`);
    const delivered = [];
    for (const job of data.jobs || []) {
      if (job.type === "agent_progress") {
        delivered.push(job.id);
        const belongsToActiveRequest = activeRequestId && job.request_id === activeRequestId;
        if (!belongsToActiveRequest && !agentOperationActive) continue;
        try {
          const progress = JSON.parse(job.result_text || "{}");
          if (progress.text) setTyping(true, progress.text + "…");
        } catch (e) {
          // Invalid progress events are transient and can be discarded safely.
        }
        continue;
      }
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
  } finally {
    jobsPollInFlight = false;
  }
}

async function checkHealth() {
  if (healthInFlight || (desktopChatState && (desktopBackground || document.hidden))) return;
  healthInFlight = true;
  try {
    const data = await chatJson("/api/health", { cache: "no-store" });
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
  } finally { healthInFlight = false; }
}

async function sendMessage(text) {
  const voiceTurn = window.PetitVoiceConversation?.beginTurn();
  let voiceResult = null;
  const requestId = crypto.randomUUID();
  activeRequestId = requestId;
  addMessage("user", text);

  setTyping(true);
  sendEl.disabled = true;
  if (waitStopEl) waitStopEl.hidden = false;
  if (desktopChatState) saveDraft(true, text);

  try {
    const data = await chatJson("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, history, request_id: requestId, session_id: sessionId,
        conversation_mode: window.PetitVoiceConversation?.active() ? "voice" : "text" }),
    });
    setTyping(false);

    if (data.request_id !== requestId) {
      throw new Error("応答のrequest IDが一致しません");
    }
    if (data.error) {
      addMessage("assistant", "⚠️ " + data.error, { error: true });
      if (desktopChatState && !inputEl.value) { inputEl.value = text; saveDraft(); }
    } else {
      desktopChatState?.complete(text);
      voiceResult = data;
      history.push({ role: "user", content: text });
      if (data.reply) {
        addMessage("assistant", data.reply, { tools: data.used_tools, actions: data.pending_actions, modelRoute: data.model_route });
        history.push({ role: "assistant", content: data.reply });
      }
    }
  } catch (e) {
    setTyping(false);
    const warning = desktopChatState ? '待機を終了しました。サーバー側で処理が続いている可能性があります。履歴と操作結果を確認してから送信してください。' : '通信に失敗しました: ' + e.message;
    addMessage("assistant", "⚠️ " + warning, { error: true });
    if (desktopChatState && !inputEl.value) {
      inputEl.value = text;
      saveDraft(true, text);
      if (draftStateEl) draftStateEl.textContent = '入力を復元しました。実行結果は未確認です。';
    }
  } finally {
    if (activeRequestId === requestId) activeRequestId = null;
    sendEl.disabled = false;
    if (waitStopEl) waitStopEl.hidden = true;
    window.PetitVoiceConversation?.finishChat(voiceTurn, voiceResult);
    inputEl.focus();
  }
}

formEl.addEventListener("submit", (e) => {
  e.preventDefault();
  if (sendEl.disabled) return;
  const text = inputEl.value.trim();
  if (!text) return;
  inputEl.value = "";
  inputEl.style.height = "auto";
  sendMessage(text);
});

let appComposing = false;
let appComposeTimer = null;
inputEl.addEventListener("compositionstart", () => {
  appComposing = true;
  if (appComposeTimer) clearTimeout(appComposeTimer);
});
inputEl.addEventListener("compositionend", () => {
  appComposing = true;
  if (appComposeTimer) clearTimeout(appComposeTimer);
  appComposeTimer = setTimeout(() => {
    appComposing = false;
  }, 50);
});

// Enter to send after IME conversion, Shift+Enter for newline. IME confirmation must not submit.
inputEl.addEventListener("keydown", (e) => {
  if (e.key !== "Enter") return;
  if (e.shiftKey) return;
  const isComposing = e.isComposing || e.keyCode === 229 || appComposing;
  if (!isComposing) {
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
    const data = await chatJson(`/api/conversations?limit=10&session_id=${encodeURIComponent(sessionId)}`);
    const rows = data.conversations || [];
    if (!rows.length) return false;
    removeStaticGreeting();
    for (const row of rows) {
      if (row.user_text) {
        addMessage("user", row.user_text, { silent: true });
        history.push({ role: "user", content: row.user_text });
      }
      if (row.assistant_text) {
        addMessage("assistant", row.assistant_text, { silent: true });
        history.push({ role: "assistant", content: row.assistant_text });
      }
    }
    return true;
  } catch (e) {
    if (desktopChatState) {
      addMessage('assistant', '会話履歴を取得できませんでした。接続を確認して画面を開き直してください。', { error: true, silent: true });
      return null;
    }
    return false;
  }
}

// On a new session, let PETIT speak first. Existing sessions restore SQLite history.
async function loadOpener() {
  try {
    const data = await chatJson(`/api/proactive?session_id=${encodeURIComponent(sessionId)}`);
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

async function restoreConversationOrOpener() {
  const restored = await restoreHistory();
  if (restored === null) return;
  if (!restored) await loadOpener();
}

function initialize() {
  // The input is usable immediately. Slow integrations must never block startup.
  inputEl.focus();
  void loadModelRouting();
  void checkHealth();
  void restoreConversationOrOpener();

  // Job polling is intentionally deferred so the first paint and history restore
  // are not competing with background delivery requests.
  window.setTimeout(() => {
    void pollJobs();
    window.setInterval(pollJobs, 2000);
  }, 1500);
}

window.setInterval(checkHealth, 60000);
if (desktopChatState) document.addEventListener('visibilitychange', () => {
  if (!document.hidden) { void checkHealth(); void pollJobs(); }
});
if (desktopChatState) {
  document.addEventListener('petit:desktop-deactivate', () => { desktopBackground = true; });
  document.addEventListener('petit:desktop-activate', () => {
    desktopBackground = false; void checkHealth(); void pollJobs();
  });
}
initialize();
