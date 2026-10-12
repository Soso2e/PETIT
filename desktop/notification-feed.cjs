'use strict';
// Main-process delivery survives hidden Renderers. No Web Push credentials.
function notificationFeed({ fetchJson, show, loadCursor, saveCursor, now = Date.now }) {
  let busy = false;
  async function poll(origin, enabled, current = () => true) {
    if (busy || !enabled) return;
    busy = true;
    try {
      let cursor = loadCursor(origin);
      if (cursor == null) {
        const data = await fetchJson(`${origin}/api/notifications/events?state=all&limit=100`);
        if (!current()) return;
        saveCursor(origin, Math.max(0, ...(data.events || []).map((event) => Number(event.id) || 0)));
        return;
      }
      const status = await fetchJson(`${origin}/api/notifications/status`);
      for (let page = 0; page < 5; page++) {
        const data = await fetchJson(`${origin}/api/notifications/events?state=all&limit=100&after_id=${cursor}`);
        if (!current()) return;
        const events = (data.events || []).filter((event) => Number.isSafeInteger(event.id) && event.id > cursor).sort((a, b) => a.id - b.id);
        for (const event of events) {
          const age = now() - Date.parse(event.created_at);
          if (!event.read && !event.resolved && age >= 0 && age < 120000 && status.preferences?.[event.category]) show(event);
          cursor = event.id; saveCursor(origin, cursor);
        }
        if (events.length < 100) break;
      }
    } finally { busy = false; }
  }
  return { poll };
}
module.exports = { notificationFeed };
