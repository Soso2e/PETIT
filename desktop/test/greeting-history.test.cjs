'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
// Test actual chat history logic, with a small deterministic DOM fixture.
const file = fs.readFileSync(path.join(__dirname, '../../frontend/app.js'), 'utf8');
const start = file.indexOf('function removeStaticGreeting() {');
const end = file.indexOf('\nfunction initialize()', start);
assert.ok(start >= 0 && end > start);
const implementation = file.slice(start, end);
async function restore({ rows = [], pending = [], fail = false } = {}) {
  let exists = true;
  const bubble = { textContent: 'default' };
  const greeting = { remove() { exists = false; }, querySelector() { return bubble; } };
  const messages = [], calls = [], history = [];
  const env = {
    window: {}, sessionId: 'test-session', desktopChatState: true, history,
    document: { getElementById(id) { return id === 'greeting' && exists ? greeting : null; } },
    addMessage(role, text, options) { messages.push({ role, text, options }); },
    async chatJson(url) {
      calls.push(url);
      if (url.startsWith('/api/conversations')) {
        if (fail) throw new Error('offline');
        return { conversations: rows };
      }
      if (url.startsWith('/api/threads/')) return { pending_actions: pending };
      if (url.startsWith('/api/proactive')) return { message: '挨拶を取得できた' };
      throw new Error('Unexpected fixture URL');
    },
  };
  vm.createContext(env);
  await vm.runInContext(implementation + '\nrestoreConversationOrOpener()', env);
  return { exists, text: bubble.textContent, messages, calls };
}
test('empty history retains greeting and proactive opener updates it', async () => {
  const result = await restore();
  assert.equal(result.exists, true);
  assert.equal(result.text, '挨拶を取得できた');
  assert.ok(result.calls.some(url => url.startsWith('/api/proactive')));
});
test('restored messages replace the initial greeting', async () => {
  const result = await restore({ rows: [{ user_text: '前', assistant_text: '後' }] });
  assert.equal(result.exists, false);
  assert.deepEqual(result.messages.map(x => x.role), ['user','assistant']);
  assert.equal(result.calls.some(url => url.startsWith('/api/proactive')), false);
});
test('pending approval replaces the greeting even without messages', async () => {
  const result = await restore({ pending: [{ approval_id: 'id', name: 'add_schedule' }] });
  assert.equal(result.exists, false);
  assert.equal(result.messages[0].options.actions.length, 1);
  assert.equal(result.calls.some(url => url.startsWith('/api/proactive')), false);
});
test('history fetch failure replaces welcome with explicit error', async () => {
  const result = await restore({ fail: true });
  assert.equal(result.exists, false);
  assert.equal(result.messages[0].options.error, true);
});
