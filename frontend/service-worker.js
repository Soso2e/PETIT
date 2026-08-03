"use strict";

const CACHE_NAME = "petit-shell-v0.9.0";
const ACTIVE_CACHE_NAME = `${CACHE_NAME}-universe-v0.9.0`;
const SHELL = [
  "/",
  "/static/universe.html",
  "/static/universe.css",
  "/static/universe-actions.css",
  "/static/universe-next.css",
  "/static/life-map.css",
  "/static/life-transition.css",
  "/static/task-flow.css",
  "/static/today.css",
  "/static/reminders.css",
  "/static/petit-ui-system.css",
  "/static/petit-motion.css",
  "/static/petit-galaxy.css",
  "/static/universe-app.js",
  "/static/universe-next.js",
  "/static/life-map.js",
  "/static/task-flow.js",
  "/static/today.js",
  "/static/app_shell.js",
  "/static/chat_input.js",
  "/static/petit-ui-system.js",
  "/static/petit-motion.js",
  "/static/petit-version.js",
  "/static/reminders.js",
  "/static/legacy.html",
  "/static/style.css",
  "/static/companion.css",
  "/static/notifications.css",
  "/static/session.js",
  "/static/version.js",
  "/static/version.json",
  "/static/app.js",
  "/static/notifications.js",
  "/static/action_confirm.js",
  "/static/mobile_audio_unlock.js",
  "/static/voice.js",
  "/static/companion.js",
  "/static/shell.js",
  "/static/manifest.webmanifest",
  "/static/favicon-64.png",
  "/static/apple-touch-icon.png",
  "/static/icon-desktop.svg",
  "/static/icon-192.png",
  "/static/icon-512.png",
  "/static/icon-maskable-192.png",
  "/static/icon-maskable-512.png",
  "/static/branding/icon_logo.png",
  "/static/branding/name_logo.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(ACTIVE_CACHE_NAME)
      .then((cache) => cache.addAll(SHELL))
      .catch(() => undefined)
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(keys.filter((key) => key !== ACTIVE_CACHE_NAME).map((key) => caches.delete(key)))
      )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin || url.pathname.startsWith("/api/")) return;

  event.respondWith(
    fetch(request)
      .then((response) => {
        if (response.status === 200) {
          const copy = response.clone();
          caches.open(ACTIVE_CACHE_NAME).then((cache) => cache.put(request, copy)).catch(() => undefined);
        }
        return response;
      })
      .catch(() => caches.match(request).then((cached) => cached || caches.match("/")))
  );
});

self.addEventListener("push", (event) => {
  let payload = {};
  if (event.data) {
    try {
      payload = event.data.json();
    } catch (error) {
      payload = { body: event.data.text() };
    }
  }

  const title = payload.title || "PETIT Assistant";
  const targetUrl = payload.url || "/";
  const options = {
    body: payload.body || "PETITからの通知メッセージです。",
    icon: payload.icon || "/static/icon-192.png",
    badge: payload.badge || "/static/favicon-64.png",
    tag: payload.tag ? `${payload.tag}-${targetUrl}` : `petit-notif-${Date.now()}`,
    renotify: true,
    vibrate: [200, 100, 200],
    data: {
      url: targetUrl,
      category: payload.category || "general",
    },
  };

  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const targetUrl = new URL(event.notification.data?.url || "/", self.location.origin).href;

  event.waitUntil(
    (async () => {
      const windows = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
      for (const client of windows) {
        if (new URL(client.url).origin !== self.location.origin) continue;
        if ("navigate" in client && client.url !== targetUrl) await client.navigate(targetUrl);
        return client.focus();
      }
      return self.clients.openWindow(targetUrl);
    })()
  );
});
