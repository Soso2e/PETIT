"use strict";

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
    icon: payload.icon || "/static/icon-192.jpg",
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
