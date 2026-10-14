const { test } = require('node:test');
const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const { nativeNotifications, deliveryMessage } = require('../native-notifications.cjs');
function fixture(action = 'show') {
  const created = []; let opened = 0;
  class Notification extends EventEmitter {
    static isSupported() { return true; }
    constructor(options) { super(); this.options = options; created.push(this); }
    show() { if (action === 'throw') throw new Error('private detail'); if (action) this.emit(action); }
  }
  const api = nativeNotifications({ Notification, open: () => opened++, timeoutMs: 10 });
  return { api, created, opened: () => opened };
}
test('quiet default and explicit sound opt-in reach native API; click opens workspace', async () => {
  const f = fixture();
  assert.equal((await f.api.deliver({ title: 'test' })).delivery, 'shown');
  assert.equal(f.created[0].options.silent, true);
  await f.api.deliver({ title: 'test' }, true);
  assert.equal(f.created[1].options.silent, false);
  f.created[1].emit('click'); assert.equal(f.opened(), 1);
  assert.match(deliveryMessage(f.api.read()), /実際の受信は端末で確認/);
});
test('failed event and synchronous failure are surfaced without native private details', async () => {
  for (const action of ['failed', 'throw']) {
    const f = fixture(action), result = await f.api.deliver({ title: 'test' });
    assert.equal(result.delivery, 'failed'); assert.match(result.error, /署名/);
    assert.doesNotMatch(result.error, /private detail/); assert.deepEqual(f.api.read(), result);
  }
});
test('no event remains unconfirmed and a later failure appears on refresh', async () => {
  const f = fixture(null), result = await f.api.deliver({ title: 'test' });
  assert.equal(result.delivery, 'requested'); assert.match(deliveryMessage(result), /未確認/);
  f.created[0].emit('failed'); assert.equal(f.api.read().delivery, 'failed');
  f.api.reset(); assert.equal(f.api.read().delivery, 'idle');
});
