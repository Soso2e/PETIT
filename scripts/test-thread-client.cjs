const { test } = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../frontend/session.js'), 'utf8');

function client(initial = {}, search = '') {
  const values = new Map(Object.entries(initial));
  const calls = [];
  let reloaded = false;
  const location = { origin: 'http://core', search, href: 'http://core/static/universe.html',
    reload() { reloaded = true; }, assign() {} };
  const context = { URL, URLSearchParams, Map, JSON, Date, Promise, Event,
    crypto: { randomUUID: () => 'generated-thread' },
    localStorage: { getItem: k => values.get(k) || null, setItem: (k,v) => values.set(k,v), removeItem: k => values.delete(k) },
    document: { readyState: 'complete', getElementById: () => null, dispatchEvent() {} },
    location, setTimeout: callback => callback(),
    fetch: async (url, options) => {
      calls.push({ url, request: options?.body && JSON.parse(options.body) });
      return { ok: true, json: async () => ({ status: 'completed', reply: 'saved', request_id: 'r' }) };
    },
  };
  context.window = context;
  vm.runInNewContext(source, context);
  return { session: context.PETIT_SESSION, values, calls, reloaded: () => reloaded };
}

test('idle and missing activity timestamps never split an existing thread', () => {
  const { session } = client({ petit_session_id: 'existing', petit_session_last_active_at: '1' });
  assert.equal(session.id, 'existing');
  assert.equal(session.idleSplitMs, null);
});
test('explicitly opening another thread keeps its ID', () => {
  const { session } = client({ petit_session_id: 'old' }, '?thread=chosen');
  assert.equal(session.id, 'chosen');
});
test('lost response keeps the exact input and blocks a second submission', async () => {
  const { session } = client({ petit_session_id: 'a' });
  await assert.rejects(session.send({ message: '始めよう', request_id: 'r' }, async () => { throw Error('lost'); }));
  assert.equal(session.pending().request_id, 'r');
  await assert.rejects(session.send({ message: '別の入力', request_id: 'second' }));
});
test('recovery reuses the original request ID instead of running another write', async () => {
  const app = client({ petit_session_id: 'a' });
  await assert.rejects(app.session.send({ message: '取り掛かろう', request_id: 'r' }, async () => { throw Error('lost'); }));
  await app.session.restore();
  assert.equal(app.calls[0].request.request_id, 'r');
  assert.equal(app.calls[0].request.message, '取り掛かろう');
  assert.equal(app.session.pending(), null);
  assert.equal(app.reloaded(), true);
});
