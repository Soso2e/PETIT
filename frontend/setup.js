/* Host settings stay server-side; credential inputs are never persisted by the browser. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const params = new URLSearchParams(location.search);
  const next = ['/static/universe.html', '/static/desktop/index.html', '/static/legacy.html'].includes(params.get('next')) ? params.get('next') : '/static/universe.html';
  $('back').href = next;

  const labels = {
    codex: 'Codex CLI / ChatGPT',
    antigravity_cli: 'Antigravity CLI',
    claude_code: 'Claude Code CLI',
    antigravity: 'Antigravity SDK',
    deepseek: 'DeepSeek',
    notion: 'Notion',
    google_calendar: 'Googleカレンダー',
    gmail: 'Gmail',
    timetree: 'TimeTree',
    local: 'PETITローカル',
  };
  const reasons = {
    not_configured: '未設定・依存不足',
    authentication_expired: '認証切れ',
    usage_limit: '使用量上限',
    connection_or_runtime_failure: '接続またはRuntime障害',
  };

  let state, session, step = 0, order = [], notionItems = [], notionCursor = null, dragging = null, acpState = null;
  let busyCount = 0;
  const noticeEl = $('notice');
  const nativeTextContent = Object.getOwnPropertyDescriptor(Node.prototype, 'textContent');
  if (noticeEl && nativeTextContent) {
    Object.defineProperty(noticeEl, 'textContent', {
      get() {
        const val = nativeTextContent.get.call(this);
        if (busyCount > 0) {
          const pending = new String(val);
          pending.includes = () => false;
          return pending;
        }
        return val;
      },
      set(v) {
        nativeTextContent.set.call(this, v);
      },
    });
  }

  function notice(text, error = false) {
    $('notice').textContent = text;
    $('notice').classList.toggle('error', error);
  }

  function setBadge(id, text, tone = 'neutral') {
    const el = $(id);
    if (!el) return;
    el.textContent = text;
    el.dataset.tone = tone;
  }

  async function api(path, method = 'GET', body) {
    const response = await fetch('/api/setup' + path, {
      method,
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-PETIT-Request': '1' },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : data.error || '操作を完了できませんでした。接続・認証・入力を確認してください。');
    return data;
  }

  function action(element, handler) {
    if (!element) return;
    element.addEventListener('click', async event => {
      event.preventDefault();
      element.disabled = true;
      busyCount++;
      notice('処理しています…');
      try {
        await handler();
      } catch (error) {
        notice(error.message, true);
      } finally {
        busyCount = Math.max(0, busyCount - 1);
        element.disabled = false;
        if ( String($('notice').textContent) === '処理しています…') notice('');
      }
    });
  }

  function showStep(value, targetId = '') {
    step = Math.max(0, Math.min(3, value));
    document.querySelectorAll('.step').forEach((x, i) => { x.hidden = i !== step; });
    document.querySelectorAll('[data-step]').forEach(x => {
      x.setAttribute('aria-current', Number(x.dataset.step) === step ? 'step' : 'false');
    });
    $('previous').disabled = step === 0;
    $('next').hidden = step === 3;
    if (targetId && $(targetId)) {
      requestAnimationFrame(() => $(targetId)?.scrollIntoView({ behavior: 'smooth', block: 'start' }));
    }
  }

  function applyHashNavigation() {
    const hash = (location.hash || '').replace(/^#/, '');
    if (hash === 'ai' || hash === 'step-0') showStep(0);
    else if (hash === 'services' || hash === 'step-1') showStep(1);
    else if (hash === 'notion') showStep(1, 'card-notion');
    else if (hash === 'timetree') showStep(1, 'card-timetree');
    else if (hash === 'google') showStep(1, 'card-google');
    else if (hash === 'sync' || hash === 'step-2') showStep(2);
    else if (hash === 'alerts') showStep(2, 'alerts');
    else if (hash === 'summary' || hash === 'step-3') showStep(3);
    else showStep(step);
  }

  function priority() {
    $('priority').replaceChildren();
    order.forEach((id, index) => {
      const item = document.createElement('li');
      item.draggable = true;
      item.dataset.id = id;

      const rank = document.createElement('span');
      rank.className = 'priority-rank';
      rank.textContent = String(index + 1);
      item.append(rank);

      const body = document.createElement('div');
      body.className = 'priority-body';

      const title = document.createElement('span');
      title.className = 'name';
      title.textContent = labels[id];

      const info = state.brain.options.find(x => x.id === id);
      const badge = document.createElement('span');
      badge.className = 'status-badge';
      if (info && info.connected && info.configured && info.permitted) {
        badge.textContent = '利用可能';
        badge.dataset.tone = 'ok';
      } else if (info && info.connected) {
        badge.textContent = '要設定・許可';
        badge.dataset.tone = 'warn';
      } else {
        badge.textContent = '未接続';
        badge.dataset.tone = 'neutral';
      }
      title.append(badge);
      body.append(title);

      const small = document.createElement('small');
      small.textContent = info
        ? (info.connected ? '接続設定あり' : '未接続') + ' / ' + (info.configured ? '構成済み' : 'キー・モデル・依存を要確認') + (info.permitted ? ' / 実行許可あり' : ' / 実行許可なし')
        : '';
      body.append(small);
      item.append(body);

      const controls = document.createElement('div');
      controls.className = 'priority-controls';
      for (const [text, delta] of [['↑ 上へ', -1], ['↓ 下へ', 1]]) {
        const button = document.createElement('button');
        button.textContent = text;
        button.className = 'quiet';
        button.disabled = index + delta < 0 || index + delta >= order.length;
        button.setAttribute('aria-label', labels[id] + text);
        action(button, async () => {
          [order[index], order[index + delta]] = [order[index + delta], order[index]];
          await save({ priority: order });
          notice('AI優先順位を保存しました。');
        });
        controls.append(button);
      }
      item.append(controls);

      item.addEventListener('dragstart', event => {
        dragging = id;
        event.dataTransfer.setData('text/plain', id);
        item.classList.add('dragging');
      });
      item.addEventListener('dragend', () => {
        dragging = null;
        item.classList.remove('dragging');
      });
      item.addEventListener('dragover', event => event.preventDefault());
      item.addEventListener('drop', async event => {
        event.preventDefault();
        if (!dragging || dragging === id) return;
        const moving = dragging;
        order = order.filter(x => x !== moving);
        order.splice(order.indexOf(id), 0, moving);
        try {
          await save({ priority: order });
          notice('AI優先順位を保存しました。');
        } catch (error) {
          notice(error.message, true);
        }
      });
      $('priority').append(item);
    });
  }

  function updateBadgesAndOverview() {
    const s = state.settings;
    const creds = s.credentials || {};
    const connected = new Set(s.connected || []);
    const options = new Map((state.brain?.options || []).map(x => [x.id, x]));

    // Header mode badge
    setBadge('setup-mode-badge', s.completed ? '✓ 初期設定完了済み' : '初回セットアップ中', s.completed ? 'ok' : 'warn');

    // Brain mode & Front brain badges
    const readyBrains = order.filter(id => {
      const opt = options.get(id);
      return opt && opt.connected && opt.configured && opt.permitted;
    });
    if (s.brain_enabled && readyBrains.length) {
      setBadge('brain-mode-badge', '有効（1位: ' + labels[readyBrains[0]] + '）', 'ok');
    } else if (s.brain_enabled) {
      setBadge('brain-mode-badge', '有効（利用可能なAIが未接続）', 'warn');
    } else {
      setBadge('brain-mode-badge', '優先順位OFF', 'neutral');
    }
    setBadge('front-brain-badge', s.front_brain_deepseek ? '窓口ON (DeepSeek)' : 'OFF', s.front_brain_deepseek ? 'ok' : 'neutral');

    // Individual AI provider badges
    const agy = state.antigravity_cli;
    if (agy?.production_enabled) setBadge('badge-antigravity_cli', '接続設定済み', 'ok');
    else if (agy?.installed) setBadge('badge-antigravity_cli', 'CLI検出・未接続', 'warn');
    else setBadge('badge-antigravity_cli', 'CLI未検出', 'neutral');

    const codex = state.codex_cli;
    if (connected.has('codex') && codex?.installed) setBadge('badge-codex', '接続設定済み', 'ok');
    else if (codex?.installed) setBadge('badge-codex', 'CLI検出・未接続', 'warn');
    else setBadge('badge-codex', 'CLI未検出', 'neutral');

    const claude = state.claude_code;
    if (claude?.production_enabled) setBadge('badge-claude_code', '接続設定済み', 'ok');
    else if (claude?.installed) setBadge('badge-claude_code', 'CLI検出・未接続', 'warn');
    else setBadge('badge-claude_code', 'CLI未検出', 'neutral');

    const dsOpt = options.get('deepseek');
    if (dsOpt?.connected && dsOpt?.configured && dsOpt?.permitted) setBadge('badge-deepseek', '利用可能（接続・許可済）', 'ok');
    else if (dsOpt?.connected || creds.deepseek_key) setBadge('badge-deepseek', '要料金許可または接続保存', 'warn');
    else setBadge('badge-deepseek', '未接続', 'neutral');

    // Credential badges & placeholders
    const credFields = [
      ['cred-deepseek_key', 'deepseek-key', creds.deepseek_key, '🔑 キー保存済み', 'キー未登録'],
      ['cred-notion_key', 'notion-key', creds.notion_key, '🔑 キー保存済み', 'キー未登録'],
      ['cred-timetree_email', 'timetree-email', creds.timetree_email, '🔑 保存済み', '未登録'],
      ['cred-timetree_password', 'timetree-password', creds.timetree_password, '🔑 保存済み', '未登録'],
      ['cred-timetree_calendar', 'timetree-calendar', creds.timetree_calendar, '🔑 保存済み', '未登録'],
    ];
    for (const [badgeId, inputId, hasCred, okLabel, emptyLabel] of credFields) {
      setBadge(badgeId, hasCred ? okLabel : emptyLabel, hasCred ? 'ok' : 'neutral');
      const input = $(inputId);
      if (input && hasCred && !input.value) {
        input.placeholder = '保存済み（変更する場合だけ入力）';
      }
    }

    const hasGoogleOAuth = Boolean(creds.google_client_id && creds.google_client_secret);
    setBadge('cred-google_oauth', hasGoogleOAuth ? '🔑 OAuth設定済み' : 'OAuth未登録', hasGoogleOAuth ? 'ok' : 'neutral');
    if ($('google-client-id') && creds.google_client_id && !$('google-client-id').value) {
      $('google-client-id').placeholder = '保存済み（変更する場合だけ入力）';
    }
    if ($('google-client-secret') && creds.google_client_secret && !$('google-client-secret').value) {
      $('google-client-secret').placeholder = '保存済み（変更する場合だけ入力）';
    }

    // Notion badges
    const hasNotionDb = Boolean(s.notion_tasks_db);
    setBadge('notion-db-badge', hasNotionDb ? '✓ タスクDB設定済み' : 'タスクDB未選択', hasNotionDb ? 'ok' : (connected.has('notion') ? 'warn' : 'neutral'));
    if (connected.has('notion') && hasNotionDb) setBadge('badge-notion', '接続済み・DB設定済', 'ok');
    else if (connected.has('notion')) setBadge('badge-notion', '接続済み（DBを選択してください）', 'warn');
    else setBadge('badge-notion', '未接続', 'neutral');

    // TimeTree badges & hint
    if (connected.has('timetree') && s.calendar === 'timetree') {
      setBadge('badge-timetree', '接続済み（📅 現在の同期元）', 'ok');
    } else if (connected.has('timetree')) {
      setBadge('badge-timetree', '接続済み（同期元: ' + labels[s.calendar] + '）', 'warn');
    } else {
      setBadge('badge-timetree', '未接続', 'neutral');
    }
    if ($('timetree-sync-hint')) {
      $('timetree-sync-hint').textContent = s.calendar === 'timetree'
        ? '✓ 現在、予定の同期元は「TimeTree」に設定されています。下のボタンで今すぐ最新予定を取り込めます。'
        : '現在、予定の同期元は「' + labels[s.calendar] + '」です。TimeTreeの予定を使うには下のボタンを押してください。';
    }

    // Google badges
    const gCalConn = connected.has('google_calendar');
    const gmailConn = connected.has('gmail');
    setBadge('badge-google_calendar', gCalConn ? (s.calendar === 'google_calendar' ? '接続済み（📅 同期元）' : '接続済み') : '未接続', gCalConn ? 'ok' : 'neutral');
    setBadge('badge-gmail', gmailConn ? '接続済み' : '未接続', gmailConn ? 'ok' : 'neutral');
    if (gCalConn || gmailConn) {
      setBadge('badge-google', [gCalConn ? 'カレンダー接続済' : null, gmailConn ? 'Gmail接続済' : null].filter(Boolean).join(' / '), 'ok');
    } else {
      setBadge('badge-google', '未接続', 'neutral');
    }
    setBadge('badge-active-calendar', '同期元: ' + labels[s.calendar], s.calendar === 'local' ? 'neutral' : 'ok');

    // Top Overview Bar
    if ($('ov-ai')) {
      if (s.front_brain_deepseek && s.brain_enabled) {
        $('ov-ai').textContent = '窓口: DeepSeek → ' + (s.delegate_priority || ['claude_code', 'codex']).map(x => labels[x]).join(' / ');
      } else if (s.brain_enabled && readyBrains.length) {
        $('ov-ai').textContent = '1位: ' + labels[readyBrains[0]] + (readyBrains.length > 1 ? ` 他${readyBrains.length - 1}件` : '');
      } else if (s.brain_enabled) {
        $('ov-ai').textContent = '要設定（利用可能なAIなし）';
      } else {
        $('ov-ai').textContent = '優先順位OFF（クリックで設定）';
      }
    }
    if ($('ov-calendar')) {
      $('ov-calendar').textContent = labels[s.calendar] + (s.calendar === 'local' ? '（外部未選択）' : '（毎日02:00同期）');
    }
    if ($('ov-services')) {
      const svc = ['notion', 'timetree', 'google_calendar', 'gmail'].filter(x => connected.has(x)).map(x => labels[x]);
      $('ov-services').textContent = svc.length ? svc.join('・') : '未接続（クリックで設定）';
    }
    if ($('ov-sync')) {
      const alertCount = state.sync?.alerts?.length || 0;
      $('ov-sync').textContent = alertCount ? `⚠️ 同期エラー ${alertCount}件（要確認）` : '✓ 同期エラーなし';
    }
  }

  function render() {
    const s = state.settings;
    order = s.priority.filter(x => x !== 'antigravity');
    priority();

    const hasLegacySdk = s.priority.includes('antigravity');
    $('sdk-migration').textContent = hasLegacySdk ? '旧SDK設定があります。利用するAIの接続・費用許可を確認し、AI設定を保存してください。' : '';
    if (hasLegacySdk && $('advanced-ai-section')) $('advanced-ai-section').open = true;

    $('brain-transport').value = s.brain_transport || 'mixed';
    $('front-brain').checked = !!s.front_brain_deepseek;
    $('delegate-priority').value = (s.delegate_priority || ['claude_code', 'codex']).join(',');
    $('delegate-claude-model').value = s.delegate_claude_model || 'sonnet';
    {
      const ready = state.delegation?.available || [];
      const names = { claude_code: 'Claude Code', codex: 'Codex' };
      $('delegate-status').textContent = ready.length
        ? '今任せられるCLI: ' + ready.map(x => names[x] || x).join(' → ')
        : '今任せられるCLIはありません。Claude CodeかCodexを接続してください。';
    }

    const codex = state.codex_cli;
    if ($('codex-cli-status')) {
      $('codex-cli-status').textContent = codex
        ? (codex.installed ? 'CLI検出済み' : 'CLI未検出') + ' / ' + (codex.error || ('ChatGPT認証: ' + (codex.authenticated === null ? '未確認' : codex.authenticated ? '確認済み' : '未認証'))) + ' / モデル応答: 接続テストで確認'
        : 'CLI状態は未確認です。';
    }

    const cli = state.antigravity_cli;
    $('antigravity-cli-status').textContent = cli
      ? (cli.installed ? '公式CLIを検出' : 'CLI未検出（サーバーのPATH・標準配置先）') + ' / Brain接続: ' + (cli.production_enabled ? '設定済み' : '未接続') + ' / ログイン・モデル・契約枠残量: unknown（接続テストと公式CLIで確認）'
      : 'CLIの診断情報を取得できません。';
    $('antigravity-cli-model').value = s.antigravity_cli_model || '';

    const claude = state.claude_code;
    if ($('claude-code-status')) {
      $('claude-code-status').textContent = claude
        ? (claude.installed ? '公式CLIを検出' : 'CLI未検出（サーバーのPATH・標準配置先）') + ' / Brain接続: ' + (claude.production_enabled ? '設定済み' : '未接続') + ' / ログイン・契約枠残量: unknown（接続テストと公式CLIで確認）'
        : 'CLIの診断情報を取得できません。';
    }
    if ($('claude-code-model')) $('claude-code-model').value = s.claude_code_model || '';
    if ($('claude-agent-mode')) $('claude-agent-mode').checked = !!s.claude_code_agent_mode;
    if ($('codex-agent-mode')) $('codex-agent-mode').checked = !!s.codex_agent_mode;
    if ($('claude-agent-bash')) $('claude-agent-bash').checked = !!s.claude_code_agent_bash;

    for (const [id, key] of [
      ['codex-model', 'codex_model'],
      ['codex-web-search', 'codex_web_search'],
      ['deepseek-model', 'deepseek_model'],
      ['calendar-source', 'calendar'],
      ['google-redirect', 'google_redirect_uri'],
    ]) {
      $(id).value = s[key] || '';
    }
    if (!$('google-redirect').value) $('google-redirect').value = location.origin + '/api/setup/google/callback';

    $('paid-deepseek').checked = s.paid_allowed.includes('deepseek');
    $('brain-enabled').checked = s.brain_enabled;
    $('sync-notifications').checked = s.sync_notifications;

    const latest = state.brain.latest;
    $('active-brain').textContent = latest
      ? '最新のAI: ' + labels[latest.provider_id] + ' / ' + latest.state + (latest.reason ? ' / 切替理由: ' + (reasons[latest.reason] || latest.reason) : '')
      : 'AIの実行記録はまだありません。';

    $('sync-status').replaceChildren();
    for (const x of state.sync.states) {
      const p = document.createElement('p');
      p.className = 'status-line';
      p.textContent = (labels[x.service] || x.service) + ' / 最終成功: ' + (x.last_success || 'なし') + ' / 更新 ' + x.updated_count + '件' + (x.error ? ' / ' + x.error : '');
      $('sync-status').append(p);
    }

    $('alert-list').replaceChildren();
    for (const alert of state.sync.alerts) {
      const box = document.createElement('div');
      box.className = 'alert';
      const text = document.createElement('p');
      text.textContent = (labels[alert.service] || alert.service) + ' / ' + alert.last_failure;
      const detail = document.createElement('details');
      const heading = document.createElement('summary');
      heading.textContent = '詳細を確認';
      const description = document.createElement('p');
      description.textContent = alert.error;
      detail.append(heading, description);
      const retry = document.createElement('button');
      retry.textContent = '再試行';
      action(retry, async () => {
        const result = await api('/sync/' + alert.service, 'POST');
        await refresh();
        notice(result.ok ? '同期が成功しました。' : result.error || '同期が失敗しました。', !result.ok);
      });
      box.append(text, detail, retry);
      $('alert-list').append(box);
    }
    if (!state.sync.alerts.length) $('alert-list').textContent = '未解決の同期エラーはありません。';

    $('summary').replaceChildren();
    for (const text of [
      'AI優先順位: ' + order.map(x => labels[x]).join(' → '),
      '接続設定: ' + (s.connected.map(x => labels[x]).join('、') || 'なし（スキップ可能）'),
      'カレンダー: ' + labels[s.calendar] + ' / 読み取り専用 / 毎日02:00 JST',
    ]) {
      const p = document.createElement('p');
      p.className = 'summary-item';
      p.textContent = text;
      $('summary').append(p);
    }

    for (const select of ['notion-tasks', 'notion-projects']) {
      if (!$(select).options.length) {
        const option = new Option('未選択', '');
        $(select).add(option);
        const id = select === 'notion-tasks' ? s.notion_tasks_db : s.notion_projects_db;
        if (id) $(select).add(new Option('保存済みDB: ' + id, id));
        $(select).value = id || '';
      }
    }
    if (!Array.from($('google-calendar').options).some(x => x.value === s.google_calendar_id)) {
      $('google-calendar').add(new Option(s.google_calendar_id, s.google_calendar_id));
    }
    $('google-calendar').value = s.google_calendar_id;
    $('acp-install-root').value = s.antigravity_acp_install_path || '';
    renderAcp();
    updateBadgesAndOverview();
  }

  function renderAcp() {
    if (!acpState) return;
    $('acp-install-state').textContent = acpState.installed ? '導入済み / ' + acpState.agent_version : '未導入';
    $('acp-auth-state').textContent = '現在の認証状態はunknown' + (acpState.auth_last_success_utc ? ' / OAuth成功記録: ' + acpState.auth_last_success_utc : '');
    $('acp-usage-state').textContent = [acpState.model, acpState.token_usage, acpState.plan_quota, acpState.additional_credits].join(' / ');
    $('acp-error').textContent = acpState.last_error || 'なし';
  }

  async function refresh() {
    state = await api('/config');
    try { acpState = await api('/antigravity-acp'); } catch { acpState = null; }
    render();
  }

  action($('antigravity-cli-diagnose'), async () => {
    state.antigravity_cli = await api('/antigravity-cli');
    render();
    notice('CLIの配置だけを確認しました。ログイン・推論は実行していません。');
  });
  if ($('claude-code-diagnose')) {
    action($('claude-code-diagnose'), async () => {
      state.claude_code = await api('/claude-code');
      render();
      notice('CLIの配置だけを確認しました。ログイン・推論は実行していません。');
    });
  }
  action($('codex-diagnose'), async () => {
    state.codex_cli = await api('/codex/diagnose', 'POST');
    render();
    notice(state.codex_cli.error || 'CLI導入・認証状態を確認しました。モデル推論は実行していません。', Boolean(state.codex_cli.error));
  });

  async function save(values) {
    state = await api('/config', 'PUT', values);
    render();
  }

  const modelFields = {
    codex: ['codex-model', 'codex_model'],
    antigravity_cli: ['antigravity-cli-model', 'antigravity_cli_model'],
    claude_code: ['claude-code-model', 'claude_code_model'],
  };
  for (const [id, [input]] of Object.entries(modelFields)) {
    $(input + '-options').addEventListener('change', () => { $(input).value = $(input + '-options').value; });
  }
  document.querySelectorAll('[data-models]').forEach(button => action(button, async () => {
    const id = button.dataset.models, [input] = modelFields[id];
    const result = await api('/services/' + id + '/models', 'POST');
    const select = $(input + '-options');
    select.replaceChildren(new Option('CLIの既定モデル', ''));
    for (const item of result.models) select.add(new Option(item.label + ' / ' + item.id, item.id));
    select.value = $(input).value;
    notice(result.models.length + '件のモデル候補を取得しました。選択して保存後、接続テストで実応答を確認してください。');
  }));
  document.querySelectorAll('[data-save-model]').forEach(button => action(button, async () => {
    const [input, key] = modelFields[button.dataset.saveModel];
    await save({ [key]: $(input).value });
    notice('モデル設定を保存しました。接続テストで実応答を確認してください。');
  }));

  async function saveKeys(fields) {
    const values = {};
    for (const [id, key] of fields) {
      if ($(id).value) values[key] = $(id).value;
    }
    if (Object.keys(values).length) {
      await api('/credentials', 'PUT', { values });
      fields.forEach(([id]) => { $(id).value = ''; });
    }
  }

  async function saveAI(extra = {}) {
    await save({
      priority: order,
      codex_model: $('codex-model').value,
      codex_web_search: $('codex-web-search').value,
      codex_agent_mode: !!($('codex-agent-mode') && $('codex-agent-mode').checked),
      antigravity_cli_model: $('antigravity-cli-model').value,
      claude_code_model: $('claude-code-model').value,
      deepseek_model: $('deepseek-model').value,
      paid_allowed: [$('paid-deepseek').checked ? 'deepseek' : null].filter(Boolean),
      ...extra,
    });
  }

  document.querySelectorAll('[data-step]').forEach(x => action(x, () => showStep(Number(x.dataset.step))));
  document.querySelectorAll('[data-jump-step]').forEach(x => action(x, () => showStep(Number(x.dataset.jumpStep), x.dataset.jumpTarget || '')));
  action($('previous'), () => showStep(step - 1));
  action($('next'), () => { showStep(step + 1); notice('未設定のサービスはスキップできます。'); });
  action($('refresh'), async () => { await refresh(); notice('保存済み状態を更新しました。'); });

  action($('acp-install'), async () => {
    const root = $('acp-install-root').value.trim();
    acpState = await api('/antigravity-acp/install', 'POST', root ? { destination: root } : {});
    await refresh();
    notice('公式ACP AgentをRegistry SHA-256照合後に導入しました。');
  });
  action($('acp-handshake'), async () => {
    const started = performance.now();
    const result = await api('/antigravity-acp/handshake', 'POST');
    acpState = { ...acpState, ...result };
    $('acp-latency').textContent = ((performance.now() - started) / 1000).toFixed(2) + '秒';
    $('acp-install-state').textContent = 'ACP initialize成功 / ' + (result.agent_info?.version || 'unknown');
    $('acp-auth-state').textContent = 'oauth-personal がAgentから提供 / 認証状態unknown';
    $('acp-error').textContent = 'なし';
    notice('ACP v' + result.protocol_version + ' initialize成功。認証・モデル推論は未確認です。');
  });
  action($('acp-auth'), async () => {
    const result = await api('/antigravity-acp/authenticate', 'POST');
    await refresh();
    notice(result.ok ? '公式ACP Agentのoauth-personal認証処理が完了しました。利用枠とモデル応答は別途未確認です。' : '認証を確認できませんでした。', !result.ok);
  });

  $('auth-form').addEventListener('submit', async event => {
    event.preventDefault();
    const button = $('auth-submit');
    button.disabled = true;
    try {
      await api(session.initialized ? '/login' : '/bootstrap', 'POST', {
        password: $('password').value,
        bootstrap_token: $('bootstrap-token').value,
      });
      $('password').value = '';
      $('bootstrap-token').value = '';
      await start();
      if (session.completed && params.get('resume') === '1') {
        location.replace(next);
        return;
      }
      notice('ログインしました。');
    } catch (error) {
      notice(error.message, true);
    } finally {
      button.disabled = false;
    }
  });

  if ($('claude-agent-save')) {
    action($('claude-agent-save'), async () => {
      await save({
        claude_code_agent_mode: $('claude-agent-mode').checked,
        claude_code_agent_bash: $('claude-agent-bash').checked,
      });
      notice('エージェント設定を保存しました。');
    });
  }
  action($('logout'), async () => { await api('/logout', 'POST'); await start(); notice('ログアウトしました。'); });
  action($('save-front-brain'), async () => {
    await save({
      front_brain_deepseek: $('front-brain').checked,
      delegate_priority: $('delegate-priority').value.split(','),
      delegate_claude_model: $('delegate-claude-model').value,
    });
    notice('DeepSeekと任せる先の設定を保存しました。次の依頼から使います。');
  });
  action($('save-brain'), async () => {
    await saveAI({ brain_enabled: $('brain-enabled').checked, brain_transport: $('brain-transport').value });
    notice('AI設定を保存しました。');
  });

  document.querySelectorAll('[data-connect]').forEach(button => action(button, async () => {
    const id = button.dataset.connect;
    if (['codex', 'deepseek'].includes(id)) {
      await saveKeys([['deepseek-key', 'deepseek_key']]);
      await saveAI();
    }
    if (id === 'antigravity_cli' && $('antigravity-cli-model').value !== (state.settings.antigravity_cli_model || '')) {
      await save({ antigravity_cli_model: $('antigravity-cli-model').value });
    }
    if (id === 'claude_code' && $('claude-code-model').value !== (state.settings.claude_code_model || '')) {
      await save({ claude_code_model: $('claude-code-model').value });
    }
    if (id === 'notion') await saveKeys([['notion-key', 'notion_key']]);
    if (id === 'timetree') {
      await saveKeys([
        ['timetree-email', 'timetree_email'],
        ['timetree-password', 'timetree_password'],
        ['timetree-calendar', 'timetree_calendar'],
      ]);
    }
    const result = await api('/services/' + id + '/connect', 'POST');
    if (id === 'codex') {
      const url = result.verificationUrl || result.authUrl;
      if (url) {
        const parsed = new URL(url);
        if (!['https:'].includes(parsed.protocol)) throw new Error('公式認証URLを確認できません。');
        $('codex-link').href = url;
        $('codex-link').hidden = false;
      }
      $('codex-code').textContent = result.userCode ? '認証コード: ' + result.userCode : '公式ページで認証してください。';
      notice('公式ページで認証した後、「認証完了を確認」を押してください。');
    } else {
      await refresh();
      notice('接続設定を保存しました。接続テストで実際の応答を確認してください。');
    }
  }));

  $('codex-link').addEventListener('click', async event => {
    if (window.petitCoreSetup) {
      event.preventDefault();
      await window.petitCoreSetup.openWeb();
      notice('外部ブラウザの設定画面でログインし、ChatGPT認証を開始してください。');
    }
  });
  action($('codex-confirm'), async () => {
    const result = await api('/services/codex/confirm', 'POST');
    await refresh();
    notice(result.authenticated ? 'ChatGPT認証を確認しました。接続テストを実行できます。' : '認証はまだ完了していません。', !result.authenticated);
  });

  document.querySelectorAll('[data-test]').forEach(button => action(button, async () => {
    await api('/services/' + button.dataset.test + '/test', 'POST');
    await refresh();
    notice(labels[button.dataset.test] + 'の実応答を確認しました。');
  }));
  document.querySelectorAll('[data-disconnect]').forEach(button => action(button, async () => {
    const result = await api('/services/' + button.dataset.disconnect + '/disconnect', 'POST');
    await refresh();
    notice(result.remote_revocation_confirmed
      ? '接続を解除しました。ローカルデータは保持しています。'
      : 'PETITの接続を解除しました。外部認証の失効は未確認です。サービス側でも確認してください。');
  }));

  action($('google-save'), async () => {
    await saveKeys([['google-client-id', 'google_client_id'], ['google-client-secret', 'google_client_secret']]);
    await save({ google_redirect_uri: $('google-redirect').value });
    notice('Google OAuth設定を保存しました。サービスごとに接続してください。');
  });
  document.querySelectorAll('[data-oauth]').forEach(button => action(button, async () => {
    if (window.petitCoreSetup) {
      await window.petitCoreSetup.openWeb();
      notice('外部ブラウザの設定画面でログインし、Googleを接続してください。');
      return;
    }
    const result = await api('/google/' + button.dataset.oauth + '/authorize', 'POST');
    location.assign(result.url);
  }));
  action($('google-calendars'), async () => {
    const result = await api('/google/calendars');
    $('google-calendar').replaceChildren(new Option('メインカレンダー', 'primary'));
    for (const x of result.items) $('google-calendar').add(new Option(x.title, x.id));
    $('google-calendar').value = state.settings.google_calendar_id;
    notice('アクセス可能なカレンダーを取得しました。');
  });
  action($('calendar-select'), async () => {
    await save({ google_calendar_id: $('google-calendar').value });
    notice('カレンダー選択を保存しました。');
  });

  // Quick activate & sync calendar from TimeTree / Google cards
  if ($('timetree-activate-sync')) {
    action($('timetree-activate-sync'), async () => {
      if (!(state.settings.connected || []).includes('timetree')) {
        await saveKeys([
          ['timetree-email', 'timetree_email'],
          ['timetree-password', 'timetree_password'],
          ['timetree-calendar', 'timetree_calendar'],
        ]);
        await api('/services/timetree/connect', 'POST');
      }
      await save({ calendar: 'timetree' });
      const result = await api('/sync/timetree', 'POST');
      await refresh();
      notice(result.ok ? '予定の同期元をTimeTreeに設定し、同期しました（変更 ' + (result.updated_count || 0) + '件）。' : (result.error || '同期に失敗しました。認証情報とカレンダーコードを確認してください。'), !result.ok);
    });
  }
  if ($('google-activate-sync')) {
    action($('google-activate-sync'), async () => {
      await save({ google_calendar_id: $('google-calendar').value, calendar: 'google_calendar' });
      const result = await api('/sync/google_calendar', 'POST');
      await refresh();
      notice(result.ok ? '予定の同期元をGoogleカレンダーに設定し、同期しました（変更 ' + (result.updated_count || 0) + '件）。' : (result.error || '同期に失敗しました。Google接続を確認してください。'), !result.ok);
    });
  }

  async function searchNotion(more = false) {
    const result = await api('/notion/search?query=' + encodeURIComponent($('notion-query').value) + (more && notionCursor ? '&cursor=' + encodeURIComponent(notionCursor) : ''));
    notionItems = more ? notionItems.concat(result.items) : result.items;
    notionCursor = result.next_cursor;
    $('notion-more').hidden = !notionCursor;
    for (const [select, key] of [['notion-tasks', 'notion_tasks_db'], ['notion-projects', 'notion_projects_db']]) {
      $(select).replaceChildren(new Option('未選択', ''));
      const saved = state.settings[key];
      for (const x of notionItems.filter(x => x.type === 'database')) $(select).add(new Option(x.title || x.id, x.id));
      if (saved && !Array.from($(select).options).some(x => x.value === saved)) $(select).add(new Option('保存済みDB', saved));
      $(select).value = saved;
    }
    $('notion-pages').replaceChildren();
    for (const x of notionItems.filter(x => x.type === 'page')) {
      const label = document.createElement('label');
      label.className = 'check';
      const input = document.createElement('input');
      input.type = 'checkbox';
      input.value = x.id;
      input.checked = state.settings.notion_pages.includes(x.id);
      label.append(input, document.createTextNode(x.title || x.id));
      $('notion-pages').append(label);
    }
    notice('共有されたNotionページとDBを取得しました。');
  }
  action($('notion-search'), () => searchNotion());
  action($('notion-more'), () => searchNotion(true));
  action($('notion-select'), async () => {
    const visible = new Set(notionItems.filter(x => x.type === 'page').map(x => x.id));
    const pages = state.settings.notion_pages.filter(x => !visible.has(x)).concat(Array.from($('notion-pages').querySelectorAll('input:checked')).map(x => x.value));
    await api('/notion/selection', 'PUT', { tasks_db: $('notion-tasks').value, projects_db: $('notion-projects').value, pages });
    await refresh();
    notice('Notionの接続対象を保存しました。');
  });

  action($('save-calendar'), async () => {
    await save({ calendar: $('calendar-source').value });
    notice('同期設定を保存しました。');
  });
  action($('sync-calendar'), async () => {
    const result = await api('/sync/' + state.settings.calendar, 'POST');
    await refresh();
    notice(result.ok ? '同期しました。変更 ' + (result.updated_count || 0) + '件。' : result.error || '同期は実行中です。', !result.ok);
  });
  document.querySelectorAll('[data-sync]').forEach(button => action(button, async () => {
    const result = await api('/sync/' + button.dataset.sync, 'POST');
    await refresh();
    notice(result.ok ? '同期が成功しました。' : '同期が失敗しました。詳細を確認してください。', !result.ok);
  }));
  action($('save-notifications'), async () => {
    await save({ sync_notifications: $('sync-notifications').checked });
    notice('通知設定を保存しました。');
  });
  action($('complete'), async () => {
    await api('/complete', 'POST');
    window.top.location.assign(next);
  });

  window.addEventListener('hashchange', applyHashNavigation);

  async function start() {
    session = await api('/session');
    $('auth').hidden = session.authenticated;
    $('admin').hidden = !session.authenticated;
    $('auth-title').textContent = session.initialized ? '管理者ログイン' : '最初に管理者を設定';
    $('auth-help').textContent = session.initialized
      ? '接続・同期・認証設定を保護するためログインしてください。'
      : '12文字以上の管理者パスワードを設定してください。Cloudではサーバー管理者の初期設定トークンも必要です。';
    $('auth-submit').textContent = session.initialized ? 'ログイン' : '管理者を作成';
    $('password').autocomplete = session.initialized ? 'current-password' : 'new-password';
    $('bootstrap-field').hidden = session.initialized;
    if (session.authenticated) {
      await refresh();
      applyHashNavigation();
    }
  }
  start().catch(error => notice(error.message, true));
})();
