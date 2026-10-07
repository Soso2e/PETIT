const { test } = require('node:test');
const assert = require('node:assert/strict');
const { create } = require('../../frontend/desktop/chat-state.js');
function store() { const map = new Map(); return { getItem: (key) => map.get(key), setItem: (key, value) => map.set(key, value), removeItem: (key) => map.delete(key) }; }
test('pending text survives restart; successful response never erases a newer draft', () => {
  const storage = store(); const state = create({ storage });
  state.save('送信中の文章', true);
  assert.deepEqual(create({ storage }).read(), { text: '送信中の文章', pending: true });
  state.save('次の下書き'); state.complete('送信中の文章');
  assert.equal(state.read().text, '次の下書き');
  state.save('送信中の文章', true); state.complete('送信中の文章');
  assert.equal(state.read(), null);
});
test('timeout and manual stop abort waiting, without retrying a write', async () => {
  for (const manual of [true, false]) {
    let timer, calls = 0;
    const state = create({ storage: store(), schedule: (fn) => { timer = fn; }, cancelTimer() {},
      fetcher: (_url, { signal }) => { calls++; return new Promise((_resolve, reject) => signal.addEventListener('abort', () => reject(new Error('aborted')))); } });
    const pending = state.request('/api/chat', { method: 'POST' });
    if (manual) state.stop(); else timer();
    await assert.rejects(pending, /aborted/); assert.equal(calls, 1);
  }
});
test('timeout also covers JSON body; HTTP failures are not treated as success', async () => {
  let timer;
  const state = create({ storage: store(), schedule: (fn) => { timer = fn; }, cancelTimer() {},
    fetcher: async (_url, { signal }) => ({ ok: true, json: () => new Promise((_resolve, reject) => signal.addEventListener('abort', () => reject(new Error('body aborted')))) }) });
  const pending = state.request('/api/chat'); await Promise.resolve(); timer();
  await assert.rejects(pending, /body aborted/);
  const failed = create({ storage: store(), fetcher: async () => ({ ok: false, status: 503, json: async () => ({}) }) });
  await assert.rejects(failed.request('/api/health'), /HTTP 503/);
});
test('unavailable or corrupted storage does not break text entry', () => {
  const state = create({ storage: { getItem() { throw new Error(); }, setItem() { throw new Error(); }, removeItem() { throw new Error(); } } });
  assert.equal(state.read(), null); assert.doesNotThrow(() => state.save('下書き'));
});
