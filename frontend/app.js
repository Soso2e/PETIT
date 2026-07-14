// PETIT chat frontend — talks to the FastAPI backend at /api/chat.

const messagesEl = document.getElementById("messages");
const formEl = document.getElementById("chat-form");
const inputEl = document.getElementById("input");
const sendEl = document.getElementById("send");
const statusEl = document.getElementById("status");

// In-memory conversation history sent back to the model for context.
const history = [];
const sessionId = localStorage.getItem("petit_session_id") || crypto.randomUUID();
localStorage.setItem("petit_session_id", sessionId);

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


async function pollJobs() {
  try {
    const res = await fetch("/api/jobs?limit=10&mark_delivered=true");
    const data = await res.json();
    for (const job of data.jobs || []) {
      if (job.status === "done") {
        const text = job.result_text || "調べ終わったけど、結果が空でした。";
        addMessage("assistant", "調べ終わったよ。\n" + text);
        history.push({ role: "assistant", content: text });
      } else if (job.status === "failed") {
        const text = "調べものが失敗しました: " + (job.error || "unknown error");
        addMessage("assistant", text, { error: true });
        history.push({ role: "assistant", content: text });
      }
    }
  } catch (e) {
    // Background job polling should not interrupt chat.
  }
}
async function checkHealth() {
  try {
    const res = await fetch("/api/health");
    const data = await res.json();
    if (data.chat_model && data.chat_model.server_ok) {
      const fallback = data.agent_model && !data.agent_model.server_ok ? " / Agentフォールバック可" : "";
      statusEl.textContent = "Chat 接続OK" + fallback;
      statusEl.className = "status status--ok";
    } else {
      statusEl.textContent = "LM Studio 未接続";
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

// On load, let PETIT speak first — fetch a proactive opener from the backend.
async function loadOpener() {
  try {
    const res = await fetch("/api/proactive");
    const data = await res.json();
    if (data && data.message) {
      const greeting = document.getElementById("greeting");
      const bubble = greeting && greeting.querySelector(".bubble");
      if (bubble) bubble.textContent = data.message;
      // Seed history so the model has continuity with its own opener.
      history.push({ role: "assistant", content: data.message });
    }
  } catch (e) {
    // Keep the static greeting if the opener can't be fetched.
  }
}

checkHealth();
setInterval(checkHealth, 60000);
setInterval(pollJobs, 3000);
loadOpener();
inputEl.focus();

