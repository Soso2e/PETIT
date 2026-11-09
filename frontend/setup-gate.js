(() => {
  'use strict';

  const LABELS = {
    codex: 'Codex CLI',
    antigravity_cli: 'Antigravity CLI',
    claude_code: 'Claude Code',
    deepseek: 'DeepSeek',
    notion: 'Notion',
    google_calendar: 'Googleカレンダー',
    gmail: 'Gmail',
    timetree: 'TimeTree',
    local: 'PETITローカル',
  };

  function ensureStyles() {
    if (document.getElementById('petit-setup-gate-style')) return;
    const style = document.createElement('style');
    style.id = 'petit-setup-gate-style';
    style.textContent = `
      body #setup-settings-card {
        grid-column: 1 / -1;
        order: -10;
        display: flex;
        flex-direction: column;
        gap: 14px;
      }
      .setup-hub-head {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        justify-content: space-between;
        gap: 10px;
        padding-bottom: 12px;
        border-bottom: 1px solid var(--ui-line, rgba(148, 163, 184, 0.2));
      }
      .setup-hub-head h2 {
        margin: 0;
        font-size: 16px;
        font-weight: 600;
      }
      .setup-hub-head p {
        margin: 4px 0 0;
        font-size: 12px;
        color: var(--ui-muted, #94a3b8);
      }
      .setup-hub-badge {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 4px 10px;
        border-radius: 999px;
        font-size: 12px;
        font-weight: 600;
        background: rgba(148, 163, 184, 0.14);
        border: 1px solid rgba(148, 163, 184, 0.3);
      }
      .setup-hub-badge[data-tone="ok"] {
        background: rgba(34, 197, 94, 0.14);
        border-color: rgba(74, 222, 128, 0.4);
        color: #4ade80;
      }
      .setup-hub-badge[data-tone="warn"] {
        background: rgba(245, 158, 11, 0.14);
        border-color: rgba(251, 191, 36, 0.4);
        color: #fbbf24;
      }
      .setup-hub-badge[data-tone="error"] {
        background: rgba(239, 68, 68, 0.15);
        border-color: rgba(248, 113, 113, 0.45);
        color: #f87171;
      }
      :root[data-petit-theme="light"] .setup-hub-badge[data-tone="ok"] { color: #15803d; }
      :root[data-petit-theme="light"] .setup-hub-badge[data-tone="warn"] { color: #b45309; }
      :root[data-petit-theme="light"] .setup-hub-badge[data-tone="error"] { color: #b91c1c; }
      .setup-hub-grid {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 12px;
      }
      .setup-hub-box {
        display: flex;
        flex-direction: column;
        justify-content: space-between;
        gap: 10px;
        padding: 14px;
        border-radius: 12px;
        background: var(--ui-bg-2, rgba(15, 23, 42, 0.45));
        border: 1px solid var(--ui-line, rgba(148, 163, 184, 0.18));
      }
      .setup-hub-box__title {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 8px;
        font-size: 13px;
        font-weight: 600;
      }
      .setup-hub-box__body {
        font-size: 12px;
        color: var(--ui-muted, #94a3b8);
        line-height: 1.55;
      }
      .setup-hub-pills {
        display: flex;
        flex-wrap: wrap;
        gap: 6px;
        margin-top: 6px;
      }
      .setup-hub-links {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        align-items: center;
      }
      .setup-hub-btn {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        padding: 7px 12px;
        min-height: 36px;
        border-radius: 8px;
        font-size: 12px;
        font-weight: 600;
        text-decoration: none;
        background: var(--ui-accent-soft, rgba(124, 179, 255, 0.18));
        border: 1px solid var(--ui-line-strong, rgba(124, 179, 255, 0.4));
        color: var(--ui-text, inherit);
        cursor: pointer;
      }
      .setup-hub-btn--secondary {
        background: transparent;
        border-color: var(--ui-line, rgba(148, 163, 184, 0.3));
        font-weight: 500;
      }
      @media (max-width: 900px) {
        .setup-hub-grid {
          grid-template-columns: 1fr;
        }
      }
    `;
    document.head.appendChild(style);
  }

  function badge(text, tone = 'neutral') {
    const span = document.createElement('span');
    span.className = 'setup-hub-badge';
    if (tone !== 'neutral') span.dataset.tone = tone;
    span.textContent = text;
    return span;
  }

  function linkBtn(href, text, secondary = false) {
    const a = document.createElement('a');
    a.href = href;
    a.className = 'setup-hub-btn' + (secondary ? ' setup-hub-btn--secondary' : '');
    a.textContent = text;
    return a;
  }

  function renderSummaryBoxes(container, data) {
    container.replaceChildren();
    const s = data.settings || {};
    const connected = new Set(s.connected || []);
    const options = new Map((data.brain?.options || []).map(x => [x.id, x]));
    const order = (s.priority || []).filter(x => x !== 'antigravity');
    const readyBrains = order.filter(id => {
      const opt = options.get(id);
      return opt && opt.connected && opt.configured && opt.permitted;
    });

    // Box 1: AI Brain
    const aiBox = document.createElement('div');
    aiBox.className = 'setup-hub-box';
    const aiTop = document.createElement('div');
    const aiTitle = document.createElement('div');
    aiTitle.className = 'setup-hub-box__title';
    aiTitle.append(
      document.createTextNode('🤖 会話AI (Brain)'),
      s.brain_enabled && readyBrains.length
        ? badge(s.front_brain_deepseek ? '窓口: DeepSeek' : '1位: ' + (LABELS[readyBrains[0]] || readyBrains[0]), 'ok')
        : badge(s.brain_enabled ? '要接続・許可' : '優先順位OFF', 'warn')
    );
    const aiBody = document.createElement('div');
    aiBody.className = 'setup-hub-box__body';
    aiBody.textContent = s.front_brain_deepseek && s.brain_enabled
      ? '普段の会話はDeepSeekが即答し、複雑な作業は ' + (s.delegate_priority || ['claude_code', 'codex']).map(x => LABELS[x] || x).join(' → ') + ' に委譲します。'
      : '優先順: ' + order.map((x, i) => `${i + 1}.${LABELS[x] || x}`).join(' → ');
    const aiPills = document.createElement('div');
    aiPills.className = 'setup-hub-pills';
    for (const id of order) {
      const opt = options.get(id);
      const ok = opt && opt.connected && opt.configured && opt.permitted;
      aiPills.append(badge((LABELS[id] || id) + (ok ? ': 利用可' : opt?.connected ? ': 要確認' : ': 未接続'), ok ? 'ok' : opt?.connected ? 'warn' : 'neutral'));
    }
    aiTop.append(aiTitle, aiBody, aiPills);
    const aiActions = document.createElement('div');
    aiActions.className = 'setup-hub-links';
    aiActions.append(linkBtn('/static/setup.html#ai', 'AI設定・優先順位を変更'));
    aiBox.append(aiTop, aiActions);

    // Box 2: Calendar (TimeTree / Google / Local)
    const calBox = document.createElement('div');
    calBox.className = 'setup-hub-box';
    const calTop = document.createElement('div');
    const calTitle = document.createElement('div');
    calTitle.className = 'setup-hub-box__title';
    const activeCal = s.calendar || 'local';
    calTitle.append(
      document.createTextNode('📅 予定・カレンダー'),
      badge('同期元: ' + (LABELS[activeCal] || activeCal), activeCal === 'local' ? 'neutral' : 'ok')
    );
    const calBody = document.createElement('div');
    calBody.className = 'setup-hub-box__body';
    calBody.textContent = activeCal === 'local'
      ? '現在はローカル予定のみを参照しています。TimeTreeまたはGoogleカレンダーを接続して同期元に設定できます。'
      : `${LABELS[activeCal]}の予定を毎日02:00（JST）に自動同期します。`;
    const calPills = document.createElement('div');
    calPills.className = 'setup-hub-pills';
    calPills.append(
      badge('TimeTree: ' + (connected.has('timetree') ? '接続済' : '未接続'), connected.has('timetree') ? 'ok' : 'neutral'),
      badge('Googleカレンダー: ' + (connected.has('google_calendar') ? '接続済' : '未接続'), connected.has('google_calendar') ? 'ok' : 'neutral')
    );
    calTop.append(calTitle, calBody, calPills);
    const calActions = document.createElement('div');
    calActions.className = 'setup-hub-links';
    calActions.append(
      linkBtn('/static/setup.html#timetree', 'TimeTree設定', activeCal !== 'timetree'),
      linkBtn('/static/setup.html#google', 'Google設定', activeCal !== 'google_calendar'),
      linkBtn('/static/setup.html#sync', '今すぐ同期', true)
    );
    calBox.append(calTop, calActions);

    // Box 3: Notion & Integrations
    const svcBox = document.createElement('div');
    svcBox.className = 'setup-hub-box';
    const svcTop = document.createElement('div');
    const svcTitle = document.createElement('div');
    svcTitle.className = 'setup-hub-box__title';
    const alerts = data.sync?.alerts || [];
    const notionReady = connected.has('notion') && Boolean(s.notion_tasks_db);
    svcTitle.append(
      document.createTextNode('🔗 Notion・メール・同期状態'),
      alerts.length
        ? badge(`同期エラー ${alerts.length}件`, 'error')
        : notionReady
          ? badge('Notion同期有効', 'ok')
          : badge(connected.has('notion') ? 'Notion DB未選択' : '未設定あり', connected.has('notion') ? 'warn' : 'neutral')
    );
    const svcBody = document.createElement('div');
    svcBody.className = 'setup-hub-box__body';
    svcBody.textContent = notionReady
      ? 'NotionタスクDBと双方向同期中です。接続診断や失敗タスクの再試行もここから開けます。'
      : 'NotionのタスクDB連携やGmail検索を設定できます。';
    const svcPills = document.createElement('div');
    svcPills.className = 'setup-hub-pills';
    svcPills.append(
      badge('Notion: ' + (notionReady ? 'DB設定済' : connected.has('notion') ? 'DB未選択' : '未接続'), notionReady ? 'ok' : connected.has('notion') ? 'warn' : 'neutral'),
      badge('Gmail: ' + (connected.has('gmail') ? '接続済' : '未接続'), connected.has('gmail') ? 'ok' : 'neutral')
    );
    svcTop.append(svcTitle, svcBody, svcPills);
    const svcActions = document.createElement('div');
    svcActions.className = 'setup-hub-links';
    const diagBtn = document.createElement('button');
    diagBtn.type = 'button';
    diagBtn.className = 'setup-hub-btn setup-hub-btn--secondary';
    diagBtn.setAttribute('data-open-connections', '');
    diagBtn.setAttribute('aria-haspopup', 'dialog');
    diagBtn.textContent = '接続ステータス診断';
    svcActions.append(
      linkBtn('/static/setup.html#notion', 'Notion設定'),
      diagBtn
    );
    svcBox.append(svcTop, svcActions);

    container.append(aiBox, calBox, svcBox);
  }

  fetch('/api/setup/session', { credentials: 'same-origin' }).then(r => r.json()).then(s => {
    if (s.initialized === false || s.completed === false) {
      location.replace('/static/setup.html?next=' + encodeURIComponent(location.pathname) + '&resume=1');
      return;
    }

    ensureStyles();

    const panel = document.querySelector('[data-view-panel="settings"] .settings-grid') || document.querySelector('#view-settings .view-content');
    let summaryGrid = null;

    if (panel && !document.getElementById('setup-settings-card')) {
      const card = document.createElement('section');
      card.id = 'setup-settings-card';
      card.className = 'settings-card';

      const head = document.createElement('div');
      head.className = 'setup-hub-head';

      const titleWrap = document.createElement('div');
      const heading = document.createElement('h2');
      heading.textContent = 'AI・サービス接続と管理者セッション';
      const text = document.createElement('p');
      titleWrap.append(heading, text);

      const actions = document.createElement('div');
      actions.className = 'setup-hub-links';

      if (s.authenticated) {
        text.textContent = '【管理者ログイン中】AI優先順位、外部同期（Notion / TimeTree / Google）、ツール実行・コード変更が有効です。';
        const link = linkBtn('/static/setup.html', '接続とAI設定を開く');
        const logoutBtn = document.createElement('button');
        logoutBtn.type = 'button';
        logoutBtn.className = 'quiet setup-hub-btn setup-hub-btn--secondary';
        logoutBtn.textContent = '管理者セッションを終了';
        logoutBtn.onclick = async () => {
          await fetch('/api/setup/logout', { method: 'POST', credentials: 'same-origin', headers: { 'X-PETIT-Request': '1' } });
          location.reload();
        };
        actions.append(badge('管理者ログイン中', 'ok'), link, logoutBtn);
      } else {
        text.textContent = '【通常会話モード】会話のみ可能です。ツール実行・コード変更・AIや外部サービスの設定変更には管理者ログインが必要です。';
        const link = linkBtn('/static/setup.html?next=' + encodeURIComponent(location.pathname), '管理者ログインを開く');
        actions.append(badge('通常会話モード', 'warn'), link);
      }

      head.append(titleWrap, actions);
      card.append(head);

      if (s.authenticated) {
        summaryGrid = document.createElement('div');
        summaryGrid.className = 'setup-hub-grid';
        card.append(summaryGrid);
      }

      panel.prepend(card);
    }

    if (s.authenticated) {
      fetch('/api/setup/config', { credentials: 'same-origin' }).then(r => r.json()).then(data => {
        if (data.settings?.brain_enabled) {
          const legacy = document.getElementById('chat-model-select')?.closest('.settings-card');
          if (legacy) legacy.hidden = true;
        }
        if (summaryGrid) renderSummaryBoxes(summaryGrid, data);
      }).catch(() => {});
    }
  }).catch(() => {});
})();
