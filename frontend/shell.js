"use strict";

(() => {
  const views = new Map(
    [...document.querySelectorAll("[data-app-view]")].map((element) => [element.dataset.appView, element])
  );
  const navButtons = [...document.querySelectorAll("[data-app-nav]")];
  const title = document.getElementById("view-title");
  const eyebrow = document.getElementById("view-eyebrow");
  const input = document.getElementById("input");
  const messages = document.getElementById("messages");
  const dateLabel = document.getElementById("today-date");

  if (!views.size || !navButtons.length || !title || !eyebrow) return;

  // app.js historically names its conversation array `history`. Give the older
  // notification UI a browser-history-compatible method until that global is renamed.
  if (Array.isArray(history) && typeof history.replaceState !== "function") {
    Object.defineProperty(history, "replaceState", {
      configurable: true,
      value: window.history.replaceState.bind(window.history),
    });
  }

  const metadata = {
    today: { title: "今日", eyebrow: "TODAY" },
    chat: { title: "チャット", eyebrow: "ASSISTANT" },
    notifications: { title: "通知", eyebrow: "INBOX" },
    settings: { title: "設定", eyebrow: "SETTINGS" },
  };

  let activeView = "today";

  function updateUrl(view) {
    const url = new URL(window.location.href);
    if (view === "today") url.searchParams.delete("view");
    else url.searchParams.set("view", view);
    window.history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
  }

  function navigate(view, options = {}) {
    const target = views.has(view) ? view : "today";
    activeView = target;

    for (const [name, element] of views.entries()) {
      const selected = name === target;
      element.hidden = !selected;
      element.setAttribute("aria-hidden", String(!selected));
    }

    for (const button of navButtons) {
      const selected = button.dataset.appNav === target;
      button.setAttribute("aria-selected", String(selected));
      if (button.id === "notification-toggle") {
        button.setAttribute("aria-expanded", String(selected));
      }
    }

    const copy = metadata[target] || metadata.today;
    title.textContent = copy.title;
    eyebrow.textContent = copy.eyebrow;
    document.body.dataset.view = target;
    localStorage.setItem("petit_active_view", target);

    if (options.updateUrl !== false) updateUrl(target);

    if (target === "chat") {
      requestAnimationFrame(() => {
        if (messages) messages.scrollTop = messages.scrollHeight;
        if (options.focus !== false) input?.focus({ preventScroll: true });
      });
    }

    document.dispatchEvent(new CustomEvent("petit:viewchange", { detail: { view: target } }));
  }

  for (const button of navButtons) {
    button.addEventListener("click", () => navigate(button.dataset.appNav || "today"));
  }

  for (const button of document.querySelectorAll("[data-chat-prompt]")) {
    button.addEventListener("click", () => {
      if (input) {
        input.value = button.dataset.chatPrompt || "";
        input.dispatchEvent(new Event("input", { bubbles: true }));
      }
      navigate("chat");
    });
  }

  if (dateLabel) {
    const now = new Date();
    dateLabel.textContent = new Intl.DateTimeFormat("ja-JP", {
      month: "long",
      day: "numeric",
      weekday: "long",
    }).format(now);
  }

  const params = new URLSearchParams(window.location.search);
  const deepLinkView = params.has("task") || params.has("notification") ? "notifications" : null;
  const requested = deepLinkView || params.get("view") || localStorage.getItem("petit_active_view") || "today";
  navigate(requested, { updateUrl: false, focus: false });

  window.PETITShell = {
    navigate,
    currentView: () => activeView,
  };
})();
