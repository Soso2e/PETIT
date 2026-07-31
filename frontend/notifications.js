"use strict";

(() => {
  const toggleButton = document.getElementById("notification-toggle");
  const panel = document.getElementById("notification-panel");
  const state = document.getElementById("notification-state");
  const enableButton = document.getElementById("notification-enable");
  const testButton = document.getElementById("notification-test");
  const disableButton = document.getElementById("notification-disable");
  const categories = document.getElementById("notification-categories");
  const refreshButton = document.getElementById("notification-refresh");
  const unreadBadge = document.getElementById("notification-unread");
  const eventList = document.getElementById("notification-list");
  const eventEmpty = document.getElementById("notification-empty");
  const taskPanel = document.getElementById("task-panel");
  const taskClose = document.getElementById("task-close");
  const taskForm = document.getElementById("task-form");
  const taskState = document.getElementById("task-state");
  const taskComplete = document.getElementById("task-complete");
  if (
    !toggleButton || !panel || !state || !enableButton || !testButton || !disableButton ||
    !categories || !refreshButton || !unreadBadge || !eventList || !eventEmpty ||
    !taskPanel || !taskClose || !taskForm || !taskState || !taskComplete
  ) return;

  let serverStatus = null;
  let registration = null;
  let subscription = null;
  let unreadCount = 0;
  let eventState = "open";
  let activeTaskId = null;
  let activeNotificationId = null;
  let activeTask = null;

  function isSupported() {
    return "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
  }

  function isStandalone() {
    return window.matchMedia("(display-mode: standalone)").matches || window.navigator.standalone === true;
  }

  function setState(message, error = false) {
    state.textContent = message;
    state.classList.toggle("notification-panel__state--error", error);
  }

  function setTaskState(message, error = false) {
    taskState.textContent = message;
    taskState.classList.toggle("task-panel__state--error", error);
  }

  function setBusy(busy) {
    enableButton.disabled = busy;
    testButton.disabled = busy || !subscription;
    disableButton.disabled = busy || !subscription;
    refreshButton.disabled = busy;
    for (const input of categories.querySelectorAll("input")) input.disabled = busy;
  }

  function urlBase64ToUint8Array(value) {
    const padding = "=".repeat((4 - value.length % 4) % 4);
    const base64 = (value + padding).replace(/-/g, "+").replace(/_/g, "/");
    const raw = atob(base64);
    return Uint8Array.from([...raw].map((character) => character.charCodeAt(0)));
  }

  async function fetchJson(url, options = {}) {
    const response = await fetch(url, { cache: "no-store", ...options });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.error) throw new Error(data.error || `HTTP ${response.status}`);
    return data;
  }

  function renderCategories(status) {
    categories.replaceChildren();
    const preferences = status.preferences || {};
    for (const item of status.categories || []) {
      const label = document.createElement("label");
      label.className = "notification-category";
      const input = document.createElement("input");
      input.type = "checkbox";
      input.dataset.category = item.id;
      input.checked = Boolean(preferences[item.id]);
      const text = document.createElement("span");
      text.textContent = item.label;
      label.append(input, text);
      categories.appendChild(label);
      input.addEventListener("change", savePreferences);
    }
  }

  function renderStatus() {
    const supported = isSupported();
    const subscribed = Boolean(subscription);
    toggleButton.textContent = unreadCount > 0 ? `通知 ${unreadCount}` : (subscribed ? "通知 ON" : "通知");
    toggleButton.classList.toggle("notification-toggle--on", subscribed || unreadCount > 0);
    toggleButton.setAttribute("aria-pressed", String(subscribed));
    unreadBadge.textContent = unreadCount > 0 ? `${unreadCount}件未読` : "未読なし";
    unreadBadge.classList.toggle("notification-panel__badge--active", unreadCount > 0);
    enableButton.hidden = subscribed;
    disableButton.hidden = !subscribed;
    testButton.disabled = !subscribed;

    if (!supported) {
      setState("このブラウザはWeb Pushに対応していません。通知履歴は利用できます。", true);
      enableButton.disabled = true;
      return;
    }

    const permission = Notification.permission;
    if (!serverStatus?.configured) {
      setState("通知履歴は利用できます。Push配信にはサーバー側のVAPID設定が必要です。");
      enableButton.disabled = true;
      return;
    }
    if (!serverStatus?.dependency_available) {
      setState("通知履歴は利用できます。Push配信にはpywebpushが必要です。", true);
      enableButton.disabled = true;
      return;
    }
    if (permission === "denied") {
      setState("Push通知がブラウザ設定で拒否されています。通知履歴は利用できます。", true);
      enableButton.disabled = true;
      return;
    }
    if (subscribed) {
      setState("この端末はPush通知を受け取れます。必要な種類だけONにしてください。");
      return;
    }
    if (/iPhone|iPad|iPod/.test(navigator.userAgent) && !isStandalone()) {
      setState("iPhoneでPush通知を使う場合はPETITをホーム画面に追加してください。");
      return;
    }
    setState("Push通知は未設定です。通知履歴はこの画面に残ります。");
  }

  function formatTimestamp(value) {
    if (!value) return "";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return new Intl.DateTimeFormat("ja-JP", {
      month: "numeric",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    }).format(date);
  }

  function renderEvents(events) {
    eventList.replaceChildren();
    eventEmpty.hidden = events.length > 0;
    for (const item of events) {
      const article = document.createElement("article");
      article.className = "notification-item";
      article.classList.toggle("notification-item--unread", !item.read);

      const open = document.createElement("button");
      open.type = "button";
      open.className = "notification-item__open";
      const heading = document.createElement("strong");
      heading.textContent = item.title;
      const body = document.createElement("span");
      body.textContent = item.body;
      const meta = document.createElement("small");
      meta.textContent = `${formatTimestamp(item.created_at)}${item.delivery_status ? ` · ${item.delivery_status}` : ""}`;
      open.append(heading, body, meta);
      open.addEventListener("click", () => openEvent(item));

      const resolve = document.createElement("button");
      resolve.type = "button";
      resolve.className = "notification-item__resolve";
      resolve.textContent = item.resolved ? "未解決に戻す" : "解決";
      resolve.addEventListener("click", async () => {
        resolve.disabled = true;
        try {
          await patchEvent(item.id, { resolved: !item.resolved });
          await loadEvents();
        } catch (error) {
          setState(`通知を解決済みにできませんでした: ${error.message}`, true);
        }
      });

      article.append(open, resolve);
      eventList.appendChild(article);
    }
  }

  async function loadEvents() {
    const data = await fetchJson(`/api/notifications/events?state=${encodeURIComponent(eventState)}&limit=50`);
    unreadCount = Number(data.unread_count || 0);
    renderEvents(data.events || []);
    renderStatus();
  }

  async function patchEvent(eventId, changes) {
    return fetchJson(`/api/notifications/events/${encodeURIComponent(eventId)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(changes),
    });
  }

  async function openEvent(item) {
    if (!item.read) {
      await patchEvent(item.id, { read: true }).catch(() => undefined);
    }
    if (item.entity_type === "task" && /^\d+$/.test(String(item.entity_id || ""))) {
      await openTask(Number(item.entity_id), item.id);
      await loadEvents();
      return;
    }
    if (item.action_url && item.action_url !== "/" && item.action_url !== window.location.pathname) {
      window.location.href = item.action_url;
      return;
    }
    await loadEvents();
  }

  function setField(name, value) {
    const field = taskForm.elements.namedItem(name);
    if (!field) return;
    field.value = value == null ? "" : String(value);
  }

  function ensureSelectValue(name, value) {
    const field = taskForm.elements.namedItem(name);
    if (!(field instanceof HTMLSelectElement) || !value) return;
    if (![...field.options].some((option) => option.value === value)) {
      field.add(new Option(value, value));
    }
    field.value = value;
  }

  function renderTask(task) {
    activeTask = task;
    document.getElementById("task-panel-title").textContent = task.title || "タスク詳細";
    setField("title", task.title);
    ensureSelectValue("status", task.status);
    setField("due_date", task.due_date ? String(task.due_date).slice(0, 10) : "");
    ensureSelectValue("priority", task.priority || "Mid");
    ensureSelectValue("area", task.area || "");
    setField("reason", task.reason || "");
    const source = task.source === "notion" ? "Notion" : "ローカル";
    const sync = task.sync_status || "synced";
    setTaskState(`${source} · 同期状態: ${sync}${task.sync_error ? ` · ${task.sync_error}` : ""}`, sync === "failed" || sync === "conflict");
    taskComplete.disabled = task.status === "Done";
  }

  async function openTask(taskId, notificationId = null) {
    activeTaskId = Number(taskId);
    activeNotificationId = notificationId == null ? null : Number(notificationId);
    taskPanel.hidden = false;
    taskPanel.setAttribute("aria-hidden", "false");
    setTaskState("タスクを取得中…");
    try {
      const data = await fetchJson(`/api/notifications/tasks/${encodeURIComponent(activeTaskId)}`);
      renderTask(data.task);
      const url = new URL(window.location.href);
      url.searchParams.set("task", String(activeTaskId));
      if (activeNotificationId != null) url.searchParams.set("notification", String(activeNotificationId));
      history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
    } catch (error) {
      setTaskState(`タスクを開けませんでした: ${error.message}`, true);
    }
  }

  function closeTask() {
    activeTaskId = null;
    activeNotificationId = null;
    activeTask = null;
    taskPanel.hidden = true;
    taskPanel.setAttribute("aria-hidden", "true");
    const url = new URL(window.location.href);
    url.searchParams.delete("task");
    url.searchParams.delete("notification");
    history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
  }

  function taskPayload() {
    const data = new FormData(taskForm);
    const payload = {
      title: String(data.get("title") || "").trim(),
      status: String(data.get("status") || "").trim(),
      priority: String(data.get("priority") || "").trim(),
      reason: String(data.get("reason") || "").trim(),
      notification_id: activeNotificationId,
      resolve_notification: true,
    };
    const area = String(data.get("area") || "").trim();
    if (area) payload.area = area;
    const dueDate = String(data.get("due_date") || "").trim();
    if (dueDate || !activeTask?.due_date) payload.due_date = dueDate;
    return payload;
  }

  async function saveTask(event) {
    event.preventDefault();
    if (activeTaskId == null) return;
    const submit = taskForm.querySelector('button[type="submit"]');
    submit.disabled = true;
    setTaskState("更新中…");
    try {
      const result = await fetchJson(`/api/notifications/tasks/${encodeURIComponent(activeTaskId)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(taskPayload()),
      });
      renderTask(result.task || activeTask);
      activeNotificationId = null;
      setTaskState(`更新しました。同期状態: ${result.sync_status || result.task?.sync_status || "synced"}`);
      await loadEvents();
    } catch (error) {
      setTaskState(`更新できませんでした: ${error.message}`, true);
    } finally {
      submit.disabled = false;
    }
  }

  async function completeTask() {
    if (activeTaskId == null) return;
    taskComplete.disabled = true;
    setTaskState("完了にしています…");
    try {
      const result = await fetchJson(`/api/notifications/tasks/${encodeURIComponent(activeTaskId)}/complete`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          notification_id: activeNotificationId,
          resolve_notification: true,
        }),
      });
      renderTask(result.task || activeTask);
      activeNotificationId = null;
      setTaskState(`完了にしました。同期状態: ${result.sync_status || result.task?.sync_status || "synced"}`);
      await loadEvents();
    } catch (error) {
      taskComplete.disabled = false;
      setTaskState(`完了にできませんでした: ${error.message}`, true);
    }
  }

  async function loadStatus() {
    if (isSupported()) {
      try {
        registration = await navigator.serviceWorker.register("/service-worker.js", { scope: "/" });
        await navigator.serviceWorker.ready;
        subscription = await registration.pushManager.getSubscription();
      } catch (error) {
        registration = null;
        subscription = null;
      }
    }
    serverStatus = await fetchJson("/api/notifications/status");
    renderCategories(serverStatus);
    await loadEvents();
    renderStatus();
  }

  async function enableNotifications() {
    setBusy(true);
    try {
      if (!serverStatus?.configured) throw new Error("VAPID設定が未設定です");
      const permission = await Notification.requestPermission();
      if (permission !== "granted") throw new Error("通知が許可されませんでした");
      subscription = await registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(serverStatus.public_key),
      });
      await fetchJson("/api/notifications/subscriptions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(subscription.toJSON()),
      });
      setState("Push通知を有効にしました。テスト通知で確認できます。");
    } catch (error) {
      setState(`Push通知を有効にできませんでした: ${error.message}`, true);
    } finally {
      setBusy(false);
      renderStatus();
    }
  }

  async function disableNotifications() {
    if (!subscription) return;
    setBusy(true);
    try {
      const endpoint = subscription.endpoint;
      await fetchJson("/api/notifications/subscriptions", {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ endpoint }),
      });
      await subscription.unsubscribe();
      subscription = null;
      setState("この端末のPush通知を解除しました。通知履歴は残ります。");
    } catch (error) {
      setState(`Push通知を解除できませんでした: ${error.message}`, true);
    } finally {
      setBusy(false);
      renderStatus();
    }
  }

  async function savePreferences() {
    const preferences = {};
    for (const input of categories.querySelectorAll("input[data-category]")) {
      preferences[input.dataset.category] = input.checked;
    }
    setBusy(true);
    try {
      const data = await fetchJson("/api/notifications/preferences", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ preferences }),
      });
      serverStatus.preferences = data.preferences;
      setState("Push通知する種類を保存しました。");
    } catch (error) {
      setState(`通知設定を保存できませんでした: ${error.message}`, true);
    } finally {
      setBusy(false);
      renderStatus();
    }
  }

  async function sendTestNotification() {
    setBusy(true);
    try {
      const result = await fetchJson("/api/notifications/test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      setState(`テスト通知を${result.sent}件送信しました。`);
      await loadEvents();
    } catch (error) {
      setState(`テスト通知に失敗しました: ${error.message}`, true);
      await loadEvents().catch(() => undefined);
    } finally {
      setBusy(false);
      renderStatus();
    }
  }

  toggleButton.addEventListener("click", () => {
    panel.hidden = !panel.hidden;
    toggleButton.setAttribute("aria-expanded", String(!panel.hidden));
    if (!panel.hidden) loadEvents().catch((error) => setState(error.message, true));
  });
  enableButton.addEventListener("click", enableNotifications);
  disableButton.addEventListener("click", disableNotifications);
  testButton.addEventListener("click", sendTestNotification);
  refreshButton.addEventListener("click", () => loadEvents().catch((error) => setState(error.message, true)));
  for (const button of panel.querySelectorAll("[data-notification-state]")) {
    button.addEventListener("click", () => {
      eventState = button.dataset.notificationState || "open";
      for (const item of panel.querySelectorAll("[data-notification-state]")) {
        item.classList.toggle("notification-filter--active", item === button);
      }
      loadEvents().catch((error) => setState(error.message, true));
    });
  }
  taskClose.addEventListener("click", closeTask);
  taskPanel.querySelector("[data-task-close]")?.addEventListener("click", closeTask);
  taskForm.addEventListener("submit", saveTask);
  taskComplete.addEventListener("click", completeTask);

  loadStatus().then(async () => {
    const params = new URLSearchParams(window.location.search);
    const notificationId = params.get("notification");
    if (notificationId && /^\d+$/.test(notificationId)) {
      await patchEvent(Number(notificationId), { read: true }).catch(() => undefined);
    }
    const taskId = params.get("task");
    if (taskId && /^\d+$/.test(taskId)) {
      await openTask(Number(taskId), notificationId && /^\d+$/.test(notificationId) ? Number(notificationId) : null);
    }
    await loadEvents();
  }).catch((error) => {
    setState(`通知状態を取得できませんでした: ${error.message}`, true);
    renderStatus();
  });
})();
