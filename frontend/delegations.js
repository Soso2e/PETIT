// Shows work handed to a CLI: what is running now, and each report as it arrives (#411).
(() => {
  const STATUS = { queued: "順番待ち", running: "作業中", waiting_approval: "確認待ち" };
  const POLL_MS = 5000;
  let context = null;
  let timer = null;
  let primed = false;
  const seen = new Set();

  const strip = () => {
    let element = document.getElementById("delegation-strip");
    const messages = document.getElementById("messages");
    if (!element && messages?.parentNode) {
      element = document.createElement("div");
      element.id = "delegation-strip";
      element.className = "delegation-strip";
      element.setAttribute("role", "status");
      element.hidden = true;
      messages.parentNode.insertBefore(element, messages);
    }
    return element;
  };

  const elapsed = (iso) => {
    const started = Date.parse(iso);
    if (Number.isNaN(started)) return "";
    const minutes = Math.max(0, Math.floor((Date.now() - started) / 60000));
    return minutes < 1 ? "1分未満" : `${minutes}分`;
  };

  const render = (items) => {
    const element = strip();
    if (!element) return;
    element.replaceChildren();
    element.hidden = items.length === 0;
    for (const item of items) {
      const row = document.createElement("div");
      row.className = "delegation-strip__row";
      const text = document.createElement("span");
      text.className = "delegation-strip__text";
      text.textContent = `${item.provider_label}に任せています: ${STATUS[item.status]}（${elapsed(item.created_at)}）`;
      text.title = item.goal;
      const stop = document.createElement("button");
      stop.type = "button";
      stop.className = "delegation-strip__stop";
      stop.textContent = "止める";
      stop.addEventListener("click", async () => {
        stop.disabled = true;
        try {
          await fetch(`/api/delegations/${encodeURIComponent(item.delegation_id)}/cancel`, { method: "POST" });
        } finally {
          void refresh();
        }
      });
      row.append(text, stop);
      element.appendChild(row);
    }
  };

  async function refresh() {
    if (!context) return;
    clearTimeout(timer);
    timer = null;
    let items = null;
    try {
      const response = await fetch(`/api/delegations?thread_id=${encodeURIComponent(context.threadId())}`);
      if (response.ok) items = (await response.json()).delegations || [];
    } catch (_error) {
      items = null;
    }
    if (items === null) {
      // Not signed in, or the server is unreachable: show nothing rather than a stale state.
      render([]);
      return;
    }
    for (const item of [...items].reverse()) {
      if (!item.reported_status) continue;
      const key = `${item.delegation_id}:${item.reported_status}`;
      if (seen.has(key)) continue;
      seen.add(key);
      // Reports written before this page opened are already in the restored history.
      if (primed && item.report) context.append(item.report, item.pending_actions || []);
    }
    primed = true;
    const active = items.filter((item) => STATUS[item.status]);
    render(active);
    if (active.length && !document.hidden) timer = setTimeout(refresh, POLL_MS);
  }

  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) void refresh();
  });

  window.PetitDelegations = {
    attach(value) {
      context = value;
      return refresh();
    },
    refresh,
  };
})();
