// PETIT session lifecycle — split idle conversations and hide internal proactive prompts.
(() => {
  const SESSION_KEY = "petit_session_id";
  const SESSION_LABEL_KEY = "petit_session_label";
  const SESSION_STARTED_KEY = "petit_session_started_at";
  const LAST_ACTIVE_KEY = "petit_session_last_active_at";
  const DAILY_COUNTER_PREFIX = "petit_session_count_";
  const IDLE_SPLIT_MS = 2 * 60 * 60 * 1000;
  const INTERNAL_PREFIX = "[PETIT_INTERNAL_EVENT]";

  const localDate = (value = new Date()) => {
    const year = value.getFullYear();
    const month = String(value.getMonth() + 1).padStart(2, "0");
    const day = String(value.getDate()).padStart(2, "0");
    return `${year}-${month}-${day}`;
  };

  const createSession = () => {
    const date = localDate();
    const counterKey = `${DAILY_COUNTER_PREFIX}${date}`;
    const count = Number(localStorage.getItem(counterKey) || "0") + 1;
    localStorage.setItem(counterKey, String(count));
    const suffix = typeof crypto !== "undefined" && crypto.randomUUID
      ? crypto.randomUUID()
      : Math.random().toString(36).slice(2);
    const id = `${date}_${String(count).padStart(2, "0")}_${suffix}`;
    const label = `${date}・${count}回目`;
    const now = Date.now();
    localStorage.setItem(SESSION_KEY, id);
    localStorage.setItem(SESSION_LABEL_KEY, label);
    localStorage.setItem(SESSION_STARTED_KEY, String(now));
    localStorage.setItem(LAST_ACTIVE_KEY, String(now));
    return { id, label, created: true };
  };

  const now = Date.now();
  const existingId = localStorage.getItem(SESSION_KEY);
  const lastActiveAt = Number(localStorage.getItem(LAST_ACTIVE_KEY) || "0");
  const shouldSplit = !existingId || !lastActiveAt || now - lastActiveAt >= IDLE_SPLIT_MS;
  const session = shouldSplit
    ? createSession()
    : {
        id: existingId,
        label: localStorage.getItem(SESSION_LABEL_KEY) || "現在の会話",
        created: false,
      };

  let lastStoredActivity = 0;
  const markActive = () => {
    const timestamp = Date.now();
    if (timestamp - lastStoredActivity < 10000) return;
    lastStoredActivity = timestamp;
    localStorage.setItem(LAST_ACTIVE_KEY, String(timestamp));
  };

  for (const eventName of ["pointerdown", "touchstart", "keydown"]) {
    window.addEventListener(eventName, markActive, { passive: true, capture: true });
  }
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") markActive();
  });

  // Internal proactive prompts are stored for continuity, but should never look
  // like something the user typed when history is restored.
  const originalFetch = window.fetch.bind(window);
  window.fetch = async (...args) => {
    const response = await originalFetch(...args);
    try {
      const input = args[0];
      const url = typeof input === "string" ? input : input && input.url;
      if (!url || !url.includes("/api/conversations") || !response.ok) return response;
      const data = await response.clone().json();
      if (!Array.isArray(data.conversations)) return response;
      data.conversations = data.conversations.map((row) => {
        const next = { ...row };
        if (String(next.user_text || "").startsWith(INTERNAL_PREFIX)) next.user_text = "";
        return next;
      });
      const headers = new Headers(response.headers);
      headers.set("Content-Type", "application/json; charset=utf-8");
      headers.delete("Content-Length");
      return new Response(JSON.stringify(data), {
        status: response.status,
        statusText: response.statusText,
        headers,
      });
    } catch (_error) {
      return response;
    }
  };

  window.PETIT_SESSION = {
    id: session.id,
    label: session.label,
    created: session.created,
    internalPrefix: INTERNAL_PREFIX,
    markActive,
    idleSplitMs: IDLE_SPLIT_MS,
  };
})();
