"use strict";

const CACHE_NAME = "petit-shell-v5";
const SHELL = [
  "/",
  "/static/style.css",
  "/static/companion.css",
  "/static/notifications.css",
  "/static/session.js",
  "/static/version.js",
  "/static/app.js",
  "/static/notifications.js",
  "/static/action_confirm.js",
  "/static/mobile_audio_unlock.js",
  "/static/voice.js",
  "/static/companion.js",
  "/static/manifest.webmanifest",
  "/static/favicon-64.png",
  "/static/apple-touch-icon.png",
  "/static/icon-192.png",
  "/static/icon-512.png",
  "/static/icon-maskable-192.png",
  "/static/icon-maskable-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL)).catch(() => undefined));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))))
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
        const copy = response.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(request, copy)).catch(() => undefined);
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

  const title = payload.title || "PETIT";
  const options = {
    body: payload.body || "PETITから通知があります。",
    icon: payload.icon || "/static/icon-192.png",
    badge: payload.badge || "/static/favicon-64.png",
    tag: payload.tag || "petit-notification",
    renotify: false,
    data: {
      url: payload.url || "/",
      category: payload.category || "unknown",
    },
  };

  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const targetUrl = new URL(event.notification.data?.url || "/", self.location.origin).href;

  event.waitUntil((async () => {
    const windows = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    for (const client of windows) {
      if (new URL(client.url).origin !== self.location.origin) continue;
      if ("navigate" in client && client.url !== targetUrl) await client.navigate(targetUrl);
      return client.focus();
    }
    return self.clients.openWindow(targetUrl);
  })());
});
