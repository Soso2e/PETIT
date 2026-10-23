// Explicit, stable conversation identity shared by Web and Desktop.
(() => {
  const key = 'petit_session_id';
  const params = new URLSearchParams(window.location.search);
  const requested = params.get('thread');
  const id = requested || localStorage.getItem(key) || crypto.randomUUID();
  localStorage.setItem(key, id);
  let stopped = false;
  const pendingKey = () => 'petit_pending_turn:' + location.origin + ':' + id;
  const readPending = () => { try { return JSON.parse(localStorage.getItem(pendingKey()) || 'null'); } catch { return null; } };
  const remember = (value) => { if (value) localStorage.setItem(pendingKey(), JSON.stringify(value)); else localStorage.removeItem(pendingKey()); };
  const markActive = () => {};
  const sleep = () => new Promise(resolve => setTimeout(resolve, 700));
  const json = async (url, options) => {
    const response = await fetch(url, options);
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'HTTP ' + response.status);
    return data;
  };
  async function waitFor(requestId, transport) {
    const deadline = Date.now() + 120000;
    while (!stopped && Date.now() < deadline) {
      const data = await transport('/api/turns/' + encodeURIComponent(requestId));
      if (!['queued', 'running'].includes(data.status)) {
        remember(null);
        return data;
      }
      await sleep();
    }
    throw new Error('応答の待機を終了しました。依頼はCoreに残っています。結果を再取得できます。');
  }
  async function send(payload, transport = json) {
    stopped = false;
    // The legacy adapter also uses the same durable ledger, including images.
    // The pending input is kept only on this client until a result is known.
    const previous = readPending();
    if (previous) throw new Error('前の依頼の結果を先に再取得してください。重複送信を防いでいます。');
    const request = { ...payload, session_id: id, source: window.petitDesktop ? 'desktop' : 'web' };
    remember(request);
    try {
      const data = await transport('/api/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(request) });
      if (['queued', 'running'].includes(data.status)) return await waitFor(request.request_id, transport);
      remember(null);
      return data;
    } catch (error) {
      document.dispatchEvent(new Event("petit:turn-pending"));
      // An HTTP response may be lost after commit. Keep the same request ID.
      throw error;
    }
  }
  async function restore() {
    const request = readPending();
    if (!request) return;
    stopped = false;
    // Resubmit the exact request; Core either accepts it once or returns its receipt.
    const data = await json('/api/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(request) });
    if (['queued', 'running'].includes(data.status)) await waitFor(request.request_id, json);
    remember(null);
    location.reload();
  }
  function open(threadId) {
    localStorage.setItem(key, threadId);
    const url = new URL(location.href); url.searchParams.set('thread', threadId); location.assign(url);
  }
  function install() {
    const form = document.getElementById('chat-form');
    if (!form) return;
    const controls = document.createElement('div');
    controls.className = 'petit-thread-controls';
    controls.style.cssText = 'display:flex;gap:6px;flex-wrap:wrap;padding:6px 0;font-size:12px;align-items:center';
    const select = document.createElement('select'); select.setAttribute('aria-label', '会話スレッド');
    select.style.maxWidth = '200px';
    const current = document.createElement('option'); current.value = id; current.textContent = '現在の会話'; select.append(current);
    select.onchange = () => open(select.value);
    const refresh = document.createElement('button'); refresh.type = 'button'; refresh.textContent = '会話一覧';
    const status = document.createElement('span'); status.setAttribute('role', 'status');
    const showError = e => { status.textContent = e.message; };
    refresh.onclick = async () => {
      try {
        const data = await json('/api/threads');
        select.replaceChildren(current);
        for (const thread of data.threads) {
          if (thread.id === id) continue;
          const option = document.createElement('option'); option.value = thread.id;
          option.textContent = (thread.title || thread.created_at.slice(0, 16)) + ' / ' + thread.source;
          select.append(option);
        }
      } catch (e) { showError(e); }
    };
    const create = document.createElement('button'); create.type = 'button'; create.textContent = '新しい会話';
    const local = document.createElement('input'); local.type = 'checkbox'; local.id = 'petit-local-thread';
    const label = document.createElement('label'); label.htmlFor = local.id; label.append(local, 'ローカル専用');
    create.onclick = async () => {
      try {
        const thread = await json('/api/threads', { method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ source: window.petitDesktop ? 'desktop' : 'web', privacy: local.checked ? 'local_only' : 'standard' }) });
        open(thread.id);
      } catch (e) { showError(e); }
    };
    controls.append(select, refresh, create, label);
    if (readPending()) {
      const restoreButton = document.createElement('button'); restoreButton.type = 'button'; restoreButton.textContent = '依頼の結果を再取得';
      restoreButton.onclick = () => restore().catch(showError); controls.append(restoreButton);
    }
    controls.append(status); form.before(controls);
    document.addEventListener('petit:turn-pending', () => {
      if (controls.querySelector('[data-restore]')) return;
      const button = document.createElement('button'); button.type = 'button'; button.dataset.restore = 'true'; button.textContent = '依頼の結果を再取得';
      button.onclick = () => restore().catch(showError); controls.append(button);
    });
  }
  window.PETIT_SESSION = { id, label: '現在の会話', created: !requested && !localStorage.getItem('petit_session_started_at'),
    internalPrefix: '[PETIT_INTERNAL_EVENT]', markActive, idleSplitMs: null, send,
    pending: readPending, restore, stopWaiting() { stopped = true; } };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', install); else install();
})();
