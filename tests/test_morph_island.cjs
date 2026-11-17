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
  const winListeners = new Map();
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
    addEventListener: (ev, fn) => winListeners.set(ev, fn),
    removeEventListener: (ev) => winListeners.delete(ev),
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
  const sessionLayer = islandEl.children[0].children.find((l) => l.classList.contains('is-on'));
  assert.equal(sessionLayer.children[1].children[0].textContent, '設計レビュー');
  assert.match(sessionLayer.children[2].textContent, /^01:0[4-9]$/);

  mockFetchData['/api/coding/activity?limit=10'] = {
    jobs: [
      { id: 'job1', provider: 'Codex', status: 'running', summary: 'UI実装中' },
      { id: 'job2', provider: 'Antigravity CLI', status: 'queued', summary: '' },
    ],
  };
  await ctx.window.PetitIslandStatus.refresh();
  assert.equal(islandEl.dataset.state, 'develop');
  const devLayer = islandEl.children[0].children.find((l) => l.classList.contains('is-on'));
  assert.equal(devLayer.children[1].children[0].textContent, '開発中');
  assert.equal(devLayer.children[2].hidden, true);

  mockFetchData['/api/coding/activity?limit=10'] = {
    jobs: [{ id: 'job1', provider: 'Antigravity CLI', status: 'ready_for_review', summary: '' }],
  };
  await ctx.window.PetitIslandStatus.refresh();
  const doneLayer = islandEl.children[0].children.find((l) => l.classList.contains('is-on'));
  assert.equal(doneLayer.children[1].children[0].textContent, '完了しました');

  docListeners.get('petit:mascot')({ detail: { state: 'thinking' } });
  assert.equal(islandEl.dataset.state, 'working');

  docListeners.get('petit:mascot')({ detail: { state: 'idle' } });
  assert.equal(islandEl.dataset.state, 'develop');

  islandEl.listeners.get('click')({});
  assert.deepEqual(navCalls, ['development']);

  // Going to Develop once dismisses the notice, and it stays dismissed on the next poll.
  assert.equal(islandEl.dataset.state, 'session');
  await ctx.window.PetitIslandStatus.refresh();
  assert.equal(islandEl.dataset.state, 'session');

  // A different job that finishes later is announced again, until Develop is opened by any route.
  mockFetchData['/api/coding/activity?limit=10'] = {
    jobs: [
      { id: 'job1', provider: 'Antigravity CLI', status: 'ready_for_review', summary: '' },
      { id: 'job3', provider: 'Codex', status: 'ready_for_review', summary: '' },
    ],
  };
  await ctx.window.PetitIslandStatus.refresh();
  assert.equal(islandEl.dataset.state, 'develop');
  winListeners.get('petit:area-change')({ detail: { area: 'development' } });
  assert.equal(islandEl.dataset.state, 'session');

  // Completing the review removes the job from the active list.
  mockFetchData['/api/coding/activity?limit=10'] = {
    jobs: [{ id: 'job4', provider: 'Codex', status: 'ready_for_review', summary: '' }],
  };
  await ctx.window.PetitIslandStatus.refresh();
  assert.equal(islandEl.dataset.state, 'develop');
  mockFetchData['/api/coding/activity?limit=10'] = {
    jobs: [{ id: 'job4', provider: 'Codex', status: 'completed', summary: '' }],
  };
  await ctx.window.PetitIslandStatus.refresh();
  assert.equal(islandEl.dataset.state, 'session');

  ctx.window.PetitIslandStatus.destroy();
});

// ---- Upstream parity -------------------------------------------------------
// Independent re-implementation of DesignBookmark morph-island/island.js +
// shared/motion.js (dt capped at 1/30 s, 4 substeps), used as the oracle.
// Values copied from shared/tokens.css (--island-w/-h/-radius) and island.js.
const UPSTREAM = { w: [380, 24], h: [300, 22], radius: 32, press: [520, 18] };
function upstreamSim(start) {
  const S = (x, k, c) => ({ x, v: 0, t: x, k, c });
  const step = (s, dt) => { const a = -s.k * (s.x - s.t) - s.c * s.v; s.v += a * dt; s.x += s.v * dt; };
  const W = S(start[0], ...UPSTREAM.w), H = S(start[1], ...UPSTREAM.h), press = S(1, ...UPSTREAM.press);
  return {
    go([w, h]) {
      const grow = w * h > W.t * H.t;
      W.k = UPSTREAM.w[0]; W.c = UPSTREAM.w[1];
      H.k = UPSTREAM.h[0] * (grow ? 1 : 1.3); H.c = UPSTREAM.h[1];
      W.t = w; H.t = h;
      press.v -= grow ? 1.6 : 1;
    },
    frame(dt) {
      dt = Math.min(dt, 1 / 30);
      for (let k = 0; k < 4; k++) { step(W, dt / 4); step(H, dt / 4); step(press, dt / 4); }
    },
    render() {
      const h = Math.max(H.x, 20);
      const give = Math.max(-0.05, Math.min(0.05, -H.v / 7000));
      return { width: W.x * (1 + give), height: h, radius: Math.min(h / 2, UPSTREAM.radius), scale: press.x };
    },
  };
}
const px = (v) => parseFloat(v);
function assertClose(actual, expected, msg) {
  assert.ok(Math.abs(actual - expected) < 1e-9, `${msg}: ${actual} != ${expected}`);
}

for (const [name, from, to] of [
  ['growing', 'idle', 'develop'],
  ['shrinking (height 1.3x stiffer)', 'develop', 'idle'],
]) {
  test(`frame-by-frame parity with upstream integrator: ${name}`, () => {
    const h = setup();
    const island = h.api.mount(new FakeElement(), { initialState: from });
    const views = h.api.DEFAULT_VIEWS;
    const ref = upstreamSim([views[from].width, views[from].height]);
    island.setState(to);
    ref.go([views[to].width, views[to].height]);
    // Frame gaps include a long stall to exercise the 1/30 s cap.
    const gaps = [16, 16, 16, 250, 16, 8, 33, 16, 16, 16, 16, 16, 16, 16, 16];
    let time = 0;
    let first = true;
    for (const gap of gaps) {
      const jobs = [...h.queue.values()];
      assert.equal(jobs.length, 1, 'one pending frame while moving');
      h.queue.clear();
      time += gap;
      jobs[0](time);
      ref.frame(first ? 1 / 60 : gap / 1000);
      first = false;
      const exp = ref.render();
      const st = island.element.style;
      assertClose(px(st.width), exp.width, 'width');
      assertClose(px(st.height), exp.height, 'height');
      assertClose(px(st.borderRadius), exp.radius, 'radius');
      assertClose(Number(/scale\(([^)]+)\)/.exec(st.transform)[1]), exp.scale, 'scale');
    }
    island.destroy();
  });
}

test('radius follows height and caps at 32px', () => {
  const h = setup();
  const island = h.api.mount(new FakeElement(), {
    views: { tall: { width: 300, height: 120, radius: 60, label: 'tall' } },
  });
  island.setState('tall');
  h.flush();
  assert.equal(h.queue.size, 0, 'animation stops once settled');
  assert.equal(island.element.style.height, '120px');
  assert.equal(island.element.style.borderRadius, '32px');
  island.destroy();
});

test('switching to reduced motion mid-morph snaps to the target', () => {
  const h = setup();
  const island = h.api.mount(new FakeElement());
  island.setState('develop');
  h.flush(3);
  assert.notEqual(island.element.style.width, '292px');
  h.mq.matches = true;
  h.listeners.get('change')();
  assert.equal(h.queue.size, 0);
  assert.equal(island.element.style.width, '292px');
  assert.equal(island.element.style.height, '54px');
  assert.equal(island.element.style.transform, 'scale(1)');
  island.destroy();
});
