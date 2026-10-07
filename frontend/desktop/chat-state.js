(function (root) {
  'use strict';
  function create({ storage, fetcher, timeout = 120000, schedule = setTimeout, cancelTimer = clearTimeout }) {
    const key = 'petit_desktop_draft';
    let active;
    const read = () => { try { return JSON.parse(storage.getItem(key) || 'null'); } catch { return null; } };
    const save = (text, pending = false) => {
      try { if (text) storage.setItem(key, JSON.stringify({ text, pending })); else storage.removeItem(key); } catch { /* Storage unavailable: text entry still works. */ }
    };
    return {
      read, save,
      complete(text) { const draft = read(); if (draft?.pending && draft.text === text) save(''); },
      stop() { active?.abort(); },
      async request(url, options = {}) {
        const controller = new AbortController();
        const chat = url === '/api/chat';
        if (chat) active = controller;
        const timer = schedule(() => controller.abort(), chat ? timeout : 15000);
        try {
          const response = await fetcher(url, { ...options, signal: controller.signal });
          const data = await response.json();
          if (!response.ok) throw new Error(data.error || `接続先がエラーを返しました（HTTP ${response.status}）`);
          return data;
        } finally { cancelTimer(timer); if (active === controller) active = null; }
      },
    };
  }
  if (typeof module !== 'undefined') module.exports = { create };
  if (root.petitDesktop) root.PetitDesktopChatState = create({ storage: root.localStorage, fetcher: (...args) => root.fetch(...args) });
})(typeof window === 'undefined' ? globalThis : window);
