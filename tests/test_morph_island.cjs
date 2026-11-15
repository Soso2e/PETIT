// Standalone test: node --test tests/test_morph_island.cjs
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

class FakeClassList {
  constructor() { this.set = new Set(); }
  add(name) { this.set.add(name); }
  remove(name) { this.set.delete(name); }
  contains(name) { return this.set.has(name); }
}

class FakeElement {
  constructor() {
    this.children = [];
    this.attributes = {};
    this.style = {};
    this.dataset = {};
    this.textContent = '';
    this.innerHTML = '';
    this.hidden = false;
    this.classList = new FakeClassList();
    this.listeners = new Map();
  }
  append(...nodes) { this.children.push(...nodes); }
  appendChild(node) { this.children.push(node); }
  remove() { this.removed = true; }
  setAttribute(name, value) { this.attributes[name] = value; }
  addEventListener(event, fn) { this.listeners.set(event, fn); }
  removeEventListener(event) { this.listeners.delete(event); }
  set className(value) { this._className = value; }
  get className() { return this._className; }
}

function setup(reduced = false) {
  const queue = new Map();
  let nextId = 0;
  let cancelled = 0;
  const listeners = new Map();
  const mq = {
    matches: reduced,
    addEventListener(event, callback) { listeners.set(event, callback); },
    removeEventListener(event) { listeners.delete(event); },
  };
  const window = {
    matchMedia: () => mq,
    requestAnimationFrame(callback) { const id = ++nextId; queue.set(id, callback); return id; },
    cancelAnimationFrame(id) { queue.delete(id); cancelled++; },
    addEventListener() {},
    removeEventListener() {},
  };
  const ctx = {
    window,
    Element: FakeElement,
    document: { createElement: () => new FakeElement() },
    requestAnimationFrame: window.requestAnimationFrame.bind(window),
    cancelAnimationFrame: window.cancelAnimationFrame.bind(window),
  };
  const file = path.join(__dirname, '..', 'frontend', 'components', 'morph-island.js');
  vm.runInNewContext(fs.readFileSync(file, 'utf8'), ctx);
  return {
    api: window.PetitMorphIsland, mq, queue, listeners,
    flush(max = 600) {
      let time = 0;
      for (let i = 0; i < max && queue.size; i++) {
        const jobs = [...queue.values()];
        queue.clear();
        time += 16;
        for (const cb of jobs) cb(time);
      }
    },
    cancelled: () => cancelled,
  };
}

test('uses DesignBookmark spring constants (380/24 width, 300/22 height, 520/18 press)', () => {
  const { api } = setup();
  assert.equal(api.DEFAULT_SPRING.width.stiffness, 380);
  assert.equal(api.DEFAULT_SPRING.width.damping, 24);
  assert.equal(api.DEFAULT_SPRING.height.stiffness, 300);
  assert.equal(api.DEFAULT_SPRING.height.damping, 22);
  assert.equal(api.DEFAULT_SPRING.press.stiffness, 520);
  assert.equal(api.DEFAULT_SPRING.press.damping, 18);
  assert.equal(api.DEFAULT_SPRING.maxRadius, 32);
});

test('mount, cross-fade update, and destroy without modifying other page elements', () => {
  const harness = setup();
  const host = new FakeElement();
  const other = new FakeElement();
  host.append(other);
  const island = harness.api.mount(host);
  assert.equal(host.children[0], other);
  assert.equal(host.children[1], island.element);
  assert.equal(island.getState(), 'idle');
  assert.equal(island.element.attributes.role, 'status');

  assert.equal(island.setState('develop', { label: 'Codex 開発中', detail: 'リポジトリ編集' }), true);
  assert.equal(island.getState(), 'develop');

  const content = island.element.children[0];
  const activeLayer = content.children.find((layer) => layer.classList.contains('is-on'));
  assert.ok(activeLayer);
  const labelNode = activeLayer.children[1].children[0];
  const detailNode = activeLayer.children[1].children[1];
  assert.equal(labelNode.textContent, 'Codex 開発中');
  assert.equal(detailNode.textContent, 'リポジトリ編集');

  assert.equal(island.setState('unknown'), false);
  harness.flush();
  assert.equal(island.element.style.width, '292px');
  assert.equal(island.element.style.height, '54px');
  assert.equal(island.element.style.borderRadius, '27px');

  island.destroy();
  assert.equal(island.element.removed, true);
  assert.equal(harness.listeners.has('change'), false);
  assert.equal(island.setState('idle'), false);
});

test('reduced motion jumps directly to target without scheduling frames', () => {
  const h = setup(true);
  const island = h.api.mount(new FakeElement());
  island.setState('listening');
  assert.equal(island.element.style.width, '228px');
  assert.equal(h.queue.size, 0);
  island.destroy();
});

test('destroy cancels any pending spring update', () => {
  const h = setup();
  const island = h.api.mount(new FakeElement());
  island.setState('session', { trailing: '04:59' });
  assert.ok(h.queue.size > 0);
  island.destroy();
  assert.equal(h.queue.size, 0);
  assert.ok(h.cancelled() >= 1);
});

test('rejects an invalid host', () => {
  const h = setup();
  assert.throws(() => h.api.mount(null), /container Element/);
});

test('petit-island-status prioritizes ephemeral chat/voice, coding jobs, notifications, and active work session', async () => {
  const docListeners = new Map();
  const body = new FakeElement();
  const navCalls = [];
  const mockFetchData = {
    '/api/work-sessions/active': { session: { status: 'active', task_title: '設計レビュー', started_at: new Date(Date.now() - 65000).toISOString(), paused_total_seconds: 0 } },
    '/api/coding/activity?limit=10': { jobs: [] },
    '/api/notifications/events?state=pending&limit=10': { events: [] },
  };
  const window = {
    matchMedia: () => ({ matches: true, addEventListener() {}, removeEventListener() {} }),
    requestAnimationFrame: () => 1,
    cancelAnimationFrame() {},
    addEventListener() {},
    removeEventListener() {},
    PetitAppShell: { activateView: (view) => navCalls.push(view) },
  };
  const document = {
    readyState: 'complete',
    hidden: false,
    body,
    createElement: () => new FakeElement(),
    querySelector: (sel) => (sel === '.universe-shell' ? new FakeElement() : null),
    addEventListener: (ev, fn) => docListeners.set(ev, fn),
    removeEventListener: (ev) => docListeners.delete(ev),
  };
  const ctx = {
    window,
    document,
    Element: FakeElement,
    AbortSignal: { timeout: () => undefined },
    fetch: async (url) => ({ ok: true, json: async () => mockFetchData[url] || {} }),
    setInterval: () => 1,
    clearInterval() {},
    setTimeout,
    clearTimeout,
    requestAnimationFrame: window.requestAnimationFrame,
    cancelAnimationFrame: window.cancelAnimationFrame,
  };
  ctx.window.document = document;
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '..', 'frontend', 'components', 'morph-island.js'), 'utf8'), ctx);
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '..', 'frontend', 'components', 'petit-island-status.js'), 'utf8'), ctx);

  await new Promise((r) => setTimeout(r, 20));
  const dock = body.children[0];
  const islandEl = dock.children[0];
  assert.equal(islandEl.dataset.state, 'session');

  mockFetchData['/api/coding/activity?limit=10'] = {
    jobs: [{ id: 'job1', provider: 'Codex', status: 'running', summary: 'UI実装中' }],
  };
  await ctx.window.PetitIslandStatus.refresh();
  assert.equal(islandEl.dataset.state, 'develop');

  docListeners.get('petit:mascot')({ detail: { state: 'thinking' } });
  assert.equal(islandEl.dataset.state, 'working');

  docListeners.get('petit:mascot')({ detail: { state: 'idle' } });
  assert.equal(islandEl.dataset.state, 'develop');

  islandEl.listeners.get('click')({});
  assert.deepEqual(navCalls, ['development']);

  ctx.window.PetitIslandStatus.destroy();
});
