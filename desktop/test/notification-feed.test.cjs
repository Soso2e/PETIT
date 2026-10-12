const { test } = require('node:test');
const assert = require('node:assert/strict');
const { notificationFeed } = require('../notification-feed.cjs');
test('opt-in baselines backlog, respects categories/state/age and persists deduplication per Core origin', async () => {
  const now = Date.now(), cursors = {}, shown = [];
  let events = [{ id: 4, category: 'work_session', created_at: new Date(now).toISOString() }];
  const feed = notificationFeed({ now: () => now, fetchJson: async (url) => url.includes('/status') ? { preferences: { work_session: true } } : { events }, show: event => shown.push(event.id), loadCursor: origin => cursors[origin], saveCursor: (origin, id) => { cursors[origin] = id; } });
  await feed.poll('a', false); assert.equal(cursors.a, undefined);
  await feed.poll('a', true); assert.equal(cursors.a, 4); assert.deepEqual(shown, []);
  events = [
    { id: 5, category: 'work_session', created_at: new Date(now).toISOString() },
    { id: 6, category: 'work_session', created_at: new Date(now - 180000).toISOString() },
    { id: 7, category: 'work_session', read: true, created_at: new Date(now).toISOString() },
    { id: 8, category: 'other', created_at: new Date(now).toISOString() },
  ];
  await feed.poll('a', true); await feed.poll('a', true);
  assert.deepEqual(shown, [5]); assert.equal(cursors.a, 8);
  await feed.poll('b', true); assert.equal(cursors.b, 8); assert.deepEqual(shown, [5]);
});
test('disabling or changing Core while a fetch is pending drops the result', async () => {
  let cursor = 1, active = true, resume;
  const shown = [];
  const feed = notificationFeed({ fetchJson: async (url) => url.includes('/status') ? { preferences: { work_session: true } } : new Promise(resolve => { resume = resolve; }), show: event => shown.push(event), loadCursor: () => cursor, saveCursor: (_, id) => { cursor = id; } });
  const pending = feed.poll('a', true, () => active);
  await Promise.resolve(); active = false;
  resume({ events: [{ id: 2, category: 'work_session', created_at: new Date().toISOString() }] });
  await pending; assert.equal(cursor, 1); assert.deepEqual(shown, []);
});
