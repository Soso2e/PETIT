"use strict";

(() => {
  const listEl = document.getElementById("reminder-list");
  if (!listEl) return;

  const countEl = document.getElementById("reminder-count");
  const statusEl = document.getElementById("reminder-status");
  const refreshEl = document.getElementById("refresh-reminders");
  const filterButtons = Array.from(document.querySelectorAll("[data-reminder-filter]"));
  const state = { scope: "upcoming", loading: false, items: [], timezone: "Asia/Tokyo" };

  const statusLabels = {
    scheduled: "予定",
    snoozed: "延期済み",
    dispatching: "通知中",
    fired: "通知済み",
    failed: "通知失敗",
    completed: "完了",
    cancelled: "取消",
  };

  const requestJson = async (url, options = {}) => {
    const response = await fetch(url, { cache: "no-store", ...options });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.error) throw new Error(data.error || `HTTP ${response.status}`);
    return data;
  };

  const localDate = (value) => {
    const date = new Date(value);
    if (!Number.isFinite(date.getTime())) return String(value || "日時未設定");
    return new Intl.DateTimeFormat("ja-JP", {
      month: "short",
      day: "numeric",
      weekday: "short",
      hour: "2-digit",
      minute: "2-digit",
    }).format(date);
  };

  const relativeLabel = (value) => {
    const target = new Date(value).getTime();
    if (!Number.isFinite(target)) return "";
    const minutes = Math.round((target - Date.now()) / 60000);
    if (Math.abs(minutes) < 1) return "まもなく";
    if (minutes > 0 && minutes < 60) return `${minutes}分後`;
    if (minutes < 0 && minutes > -60) return `${Math.abs(minutes)}分前`;
    const hours = Math.round(minutes / 60);
    if (hours > 0 && hours < 24) return `${hours}時間後`;
    if (hours < 0 && hours > -24) return `${Math.abs(hours)}時間前`;
    return "";
  };

  const setStatus = (message, tone = "") => {
    if (!statusEl) return;
    statusEl.textContent = message;
    statusEl.dataset.tone = tone;
  };

  const actionButton = (label, action, reminder, className = "") => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = label;
    button.className = className;
    button.addEventListener("click", () => updateReminder(reminder, action));
    return button;
  };

  const renderEmpty = () => {
    listEl.replaceChildren();
    const empty = document.createElement("div");
    empty.className = "reminder-empty";
    const title = document.createElement("strong");
    title.textContent = state.scope === "history" ? "履歴はまだありません" : "リマインダーはまだありません";
    const copy = document.createElement("p");
    copy.textContent = "Chatで『30分後にカフェへ行く時間だと知らせて』のように話しかけると追加できます。";
    empty.append(title, copy);
    listEl.append(empty);
  };

  const render = () => {
    if (countEl) countEl.textContent = `${state.items.length}件`;
    if (!state.items.length) {
      renderEmpty();
      return;
    }

    listEl.replaceChildren();
    const highlighted = new URLSearchParams(location.search).get("reminder");
    state.items.forEach((reminder) => {
      const card = document.createElement("article");
      card.className = `reminder-card reminder-card--${reminder.status || "scheduled"}`;
      card.dataset.reminderId = String(reminder.id);
      if (highlighted === String(reminder.id)) card.classList.add("is-highlighted");

      const meta = document.createElement("div");
      meta.className = "reminder-card__meta";
      const time = document.createElement("time");
      time.dateTime = reminder.trigger_at;
      time.textContent = localDate(reminder.trigger_at);
      const relative = document.createElement("span");
      relative.textContent = relativeLabel(reminder.trigger_at);
      const badge = document.createElement("span");
      badge.className = "reminder-status-badge";
      badge.textContent = statusLabels[reminder.status] || reminder.status;
      meta.append(time, relative, badge);

      const heading = document.createElement("h2");
      heading.textContent = reminder.title || "名称未設定";
      const body = document.createElement("p");
      body.textContent = reminder.message || "";

      const footer = document.createElement("div");
      footer.className = "reminder-card__footer";
      const detail = document.createElement("small");
      const delivery = reminder.delivery_status ? `配信: ${reminder.delivery_status}` : "通知待ち";
      detail.textContent = reminder.last_error ? `${delivery} / ${reminder.last_error}` : delivery;
      footer.append(detail);

      const actions = document.createElement("div");
      actions.className = "reminder-card__actions";
      if (!["completed", "cancelled"].includes(reminder.status)) {
        actions.append(
          actionButton("完了", "complete", reminder, "is-primary"),
          actionButton("10分後", "snooze", reminder),
          actionButton("取消", "cancel", reminder, "is-danger"),
        );
      }
      footer.append(actions);
      card.append(meta, heading, body, footer);
      listEl.append(card);
    });
  };

  const load = async () => {
    if (state.loading) return;
    state.loading = true;
    refreshEl?.setAttribute("aria-busy", "true");
    setStatus("読み込み中");
    try {
      const data = await requestJson(`/api/notifications/reminders?scope=${encodeURIComponent(state.scope)}&limit=200`);
      state.items = Array.isArray(data.items) ? data.items : [];
      state.timezone = data.timezone || state.timezone;
      render();
      setStatus(`最終更新 ${new Date().toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit" })}`, "ok");
    } catch (error) {
      state.items = [];
      render();
      setStatus(`取得できませんでした: ${error.message}`, "error");
    } finally {
      state.loading = false;
      refreshEl?.removeAttribute("aria-busy");
    }
  };

  const updateReminder = async (reminder, action) => {
    const endpoint = `/api/notifications/reminders/${encodeURIComponent(reminder.id)}/${action}`;
    const body = action === "snooze" ? JSON.stringify({ minutes: 10 }) : undefined;
    setStatus("更新中");
    try {
      await requestJson(endpoint, {
        method: "POST",
        headers: body ? { "Content-Type": "application/json" } : undefined,
        body,
      });
      await load();
    } catch (error) {
      setStatus(`更新できませんでした: ${error.message}`, "error");
    }
  };

  filterButtons.forEach((button) => {
    button.addEventListener("click", () => {
      state.scope = button.dataset.reminderFilter || "upcoming";
      filterButtons.forEach((candidate) => candidate.classList.toggle("is-active", candidate === button));
      load();
    });
  });
  refreshEl?.addEventListener("click", load);

  const query = new URLSearchParams(location.search);
  if (query.get("view") === "reminders" || query.has("reminder")) {
    document.querySelector('[data-view="reminders"]')?.click();
  }

  load();
  window.setInterval(() => {
    const panel = document.querySelector('[data-view-panel="reminders"]');
    if (panel && !panel.hidden) load();
  }, 30_000);
})();
