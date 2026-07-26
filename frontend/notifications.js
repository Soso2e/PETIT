"use strict";

(() => {
  const toggleButton = document.getElementById("notification-toggle");
  const panel = document.getElementById("notification-panel");
  const state = document.getElementById("notification-state");
  const enableButton = document.getElementById("notification-enable");
  const testButton = document.getElementById("notification-test");
  const disableButton = document.getElementById("notification-disable");
  const categories = document.getElementById("notification-categories");
  if (!toggleButton || !panel || !state || !enableButton || !testButton || !disableButton || !categories) return;

  let serverStatus = null;
  let registration = null;
  let subscription = null;

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

  function setBusy(busy) {
    enableButton.disabled = busy;
    testButton.disabled = busy || !subscription;
    disableButton.disabled = busy || !subscription;
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
    const permission = Notification.permission;
    const subscribed = Boolean(subscription);
    toggleButton.textContent = subscribed ? "通知 ON" : "通知 OFF";
    toggleButton.classList.toggle("notification-toggle--on", subscribed);
    toggleButton.setAttribute("aria-pressed", String(subscribed));
    enableButton.hidden = subscribed;
    disableButton.hidden = !subscribed;
    testButton.disabled = !subscribed;

    if (!isSupported()) {
      setState("このブラウザはWeb Pushに対応していません。", true);
      setBusy(true);
      return;
    }
    if (!serverStatus?.configured) {
      setState("サーバー側のVAPID設定が未設定です。", true);
      return;
    }
    if (!serverStatus?.dependency_available) {
      setState("サーバーにpywebpushがインストールされていません。", true);
      return;
    }
    if (permission === "denied") {
      setState("通知がブラウザ設定で拒否されています。設定から許可してください。", true);
      return;
    }
    if (subscribed) {
      setState("この端末は通知を受け取れます。必要な種類だけONにしてください。");
      return;
    }
    if (/iPhone|iPad|iPod/.test(navigator.userAgent) && !isStandalone()) {
      setState("iPhoneではPETITをホーム画面に追加してから通知を有効にしてください。");
      return;
    }
    setState("通知はまだ有効になっていません。");
  }

  async function loadStatus() {
    if (!isSupported()) {
      renderStatus();
      return;
    }
    registration = await navigator.serviceWorker.register("/service-worker.js", { scope: "/" });
    await navigator.serviceWorker.ready;
    subscription = await registration.pushManager.getSubscription();
    serverStatus = await fetchJson("/api/notifications/status");
    renderCategories(serverStatus);
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
      setState("通知を有効にしました。テスト通知で確認できます。");
    } catch (error) {
      setState(`通知を有効にできませんでした: ${error.message}`, true);
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
      setState("この端末の通知を解除しました。");
    } catch (error) {
      setState(`通知を解除できませんでした: ${error.message}`, true);
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
      setState("通知する種類を保存しました。");
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
    } catch (error) {
      setState(`テスト通知に失敗しました: ${error.message}`, true);
    } finally {
      setBusy(false);
      renderStatus();
    }
  }

  toggleButton.addEventListener("click", () => {
    panel.hidden = !panel.hidden;
    toggleButton.setAttribute("aria-expanded", String(!panel.hidden));
  });
  enableButton.addEventListener("click", enableNotifications);
  disableButton.addEventListener("click", disableNotifications);
  testButton.addEventListener("click", sendTestNotification);

  loadStatus().catch((error) => {
    setState(`通知状態を取得できませんでした: ${error.message}`, true);
    renderStatus();
  });
})();
