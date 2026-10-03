const { test } = require('node:test');
const assert = require('node:assert/strict');
const Conversation = require('../../frontend/desktop/conversation.js');
function harness() {
  let listens = 0;
  const pending = [];
  const conversation = new Conversation({ listen: () => listens++, changed() {}, schedule: fn => pending.push(fn) });
  conversation.start();
  return { conversation, pending, get listens() { return listens; } };
}
for (const first of ['chat', 'audio']) test(`next microphone waits for both completions (${first} first)`, () => {
  const h = harness(), c = h.conversation, token = c.beginTurn();
  const chat = () => c.finishChat(token, { reply: 'こんにちは' });
  const audio = () => c.finishAudio(token, true);
  (first === 'chat' ? chat : audio)();
  assert.equal(h.pending.length, 0);
  (first === 'chat' ? audio : chat)();
  assert.equal(h.pending.length, 1);
  h.pending.shift()();
  assert.equal(h.listens, 2);
});
test('hide or stop cancels scheduled microphone and ignores stale playback', () => {
  const h = harness(), c = h.conversation, token = c.beginTurn();
  c.finishChat(token, { reply: 'こんにちは' }); c.finishAudio(token, true);
  c.stop(); h.pending.shift()(); c.finishAudio(token, true);
  assert.equal(h.listens, 1); assert.equal(c.active, false);
});
test('new turn invalidates old chat and playback callbacks', () => {
  const h = harness(), c = h.conversation, token = c.beginTurn();
  c.beginTurn(); c.finishChat(token, { reply: '古い返答' }); c.finishAudio(token, true);
  assert.equal(h.pending.length, 0);
});
for (const result of [null, { error: 'offline' }, { reply: '' }, { reply: '確認', pending_actions: [{}] }]) {
  test(`chat failure or approval stops automatic listening: ${JSON.stringify(result)}`, () => {
    const h = harness(), c = h.conversation, token = c.beginTurn();
    c.finishChat(token, result); c.finishAudio(token, true);
    assert.equal(c.active, false); assert.equal(h.pending.length, 0);
  });
}
test('audio failure stops automatic listening', () => {
  const h = harness(), c = h.conversation, token = c.beginTurn();
  c.finishChat(token, { reply: 'こんにちは' }); c.finishAudio(token, false);
  assert.equal(c.active, false); assert.equal(h.pending.length, 0);
});
