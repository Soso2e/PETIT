// PETIT chat frontend — talks to the FastAPI backend at /api/chat.

const messagesEl = document.getElementById("messages");
const formEl = document.getElementById("chat-form");
const inputEl = document.getElementById("input");
const sendEl = document.getElementById("send");
const statusEl = document.getElementById("status");

// In-memory conversation history sent back to the model for context.
const history = [];

function addMessage(role, text, { tools, error } = {}) {
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

  messagesEl.appendChild(wrap);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return bubble;
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
    if (data.lm_studio && data.lm_studio.ok) {
      const models = data.lm_studio.models || [];
      statusEl.textContent = "LM Studio 接続OK" + (models.length ? ` (${models[0]})` : "");
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
  addMessage("user", text);
  history.push({ role: "user", content: text });

  setTyping(true);
  sendEl.disabled = true;

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, history: history.slice(0, -1) }),
    });
    const data = await res.json();
    setTyping(false);

    if (data.error) {
      addMessage("assistant", "⚠️ " + data.error, { error: true });
    } else {
      addMessage("assistant", data.reply, { tools: data.used_tools });
      history.push({ role: "assistant", content: data.reply });
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
setInterval(checkHealth, 15000);
setInterval(pollJobs, 3000);
loadOpener();
inputEl.focus();

