const CACHE_NAME = "petit-shell-v2";
const SHELL = [
  "/",
  "/static/style.css",
  "/static/companion.css",
  "/static/session.js",
  "/static/app.js",
  "/static/action_confirm.js",
  "/static/mobile_audio_unlock.js",
  "/static/voice.js",
  "/static/companion.js",
  "/static/manifest.webmanifest",
  "/static/favicon-64.png",
  "/static/apple-touch-icon.png",
  "/static/icon-192.jpg",
  "/static/icon-512.jpg"
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
