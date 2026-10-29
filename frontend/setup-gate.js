(() => {
  'use strict';
  fetch('/api/setup/session', { credentials: 'same-origin' }).then(r => r.json()).then(s => {
    if (!s.initialized || !s.completed) {
      location.replace('/static/setup.html?next=' + encodeURIComponent(location.pathname) + '&resume=1');
      return;
    }
    if (s.authenticated) {
      fetch('/api/setup/config').then(r => r.json()).then(data => {
        if (data.settings?.brain_enabled) {
          const legacy = document.getElementById('chat-model-select')?.closest('.settings-card');
          if (legacy) legacy.hidden = true;
        }
      }).catch(() => {});
    }
    const panel = document.querySelector('[data-view-panel="settings"] .settings-grid');
    if (panel && !document.getElementById('setup-settings-card')) {
      const card = document.createElement('section');
      card.id = 'setup-settings-card';
      card.className = 'settings-card';
      const heading = document.createElement('h2');
      heading.textContent = 'AI・サービス接続と管理者セッション';
      const text = document.createElement('p');
      const actions = document.createElement('div');
      actions.style.cssText = 'display:flex;gap:8px;align-items:center;margin-top:8px;';
      if (s.authenticated) {
        text.textContent = '【管理者ログイン中】AI優先順位、外部同期、ツール実行・コード変更が有効です。';
        const link = document.createElement('a');
        link.href = '/static/setup.html';
        link.textContent = '接続とAI設定を開く';
        const logoutBtn = document.createElement('button');
        logoutBtn.type = 'button';
        logoutBtn.className = 'quiet';
        logoutBtn.textContent = '管理者セッションを終了';
        logoutBtn.onclick = async () => {
          await fetch('/api/setup/logout', { method: 'POST', credentials: 'same-origin', headers: { 'X-PETIT-Request': '1' } });
          location.reload();
        };
        actions.append(link, logoutBtn);
      } else {
        text.textContent = '【通常会話モード】会話のみ可能です。ツール実行・コード変更・設定変更には管理者ログインが必要です。';
        const link = document.createElement('a');
        link.href = '/static/setup.html?next=' + encodeURIComponent(location.pathname);
        link.textContent = '管理者ログインを開く';
        actions.append(link);
      }
      card.append(heading, text, actions);
      panel.prepend(card);
    }
  }).catch(() => {});
})();
