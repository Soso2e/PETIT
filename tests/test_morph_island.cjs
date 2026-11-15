// Standalone test: node --test tests/test_morph_island.cjs
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

class FakeElement {
  constructor() {
    this.children = [];
    this.attributes = {};
    this.style = {};
    this.dataset = {};
    this.textContent = '';
    this.hidden = false;
  }
  append(...nodes) { this.children.push(...nodes); }
  appendChild(node) { this.children.push(node); }
  remove() { this.removed = true; }
  setAttribute(name, value) { this.attributes[name] = value; }
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
  };
  const ctx = { window, Element: FakeElement, document: { createElement: () => new FakeElement() } };
  // Browser global requestAnimationFrame/cancelAnimationFrame.
  ctx.requestAnimationFrame = window.requestAnimationFrame.bind(window);
  ctx.cancelAnimationFrame = window.cancelAnimationFrame.bind(window);
  const file = path.join(__dirname, '..', 'frontend', 'components', 'morph-island.js');
  vm.runInNewContext(fs.readFileSync(file, 'utf8'), ctx);
  return {
    api: window.PetitMorphIsland, mq, queue, listeners,
    time: 0,
    flush(max = 600, frameMs = 16) {
      for (let i = 0; i < max && queue.size; i++) {
        const jobs = [...queue.values()];
        queue.clear();
        this.time += frameMs;
        for (const cb of jobs) cb(this.time);
      }
    },
    cancelled: () => cancelled,
  };
}

test('mount, update, and destroy without modifying other page elements', () => {
  const harness = setup();
  const host = new FakeElement();
  const other = new FakeElement();
  host.append(other);
  const island = harness.api.mount(host);
  assert.equal(host.children[0], other);
  assert.equal(host.children[1], island.element);
  assert.equal(island.getState(), 'idle');
  assert.equal(island.element.attributes.role, 'status');
  assert.equal(island.setState('working', { label: 'Codexで開発中' }), true);
  assert.equal(island.getState(), 'working');
  assert.equal(island.element.children[1].textContent, 'Codexで開発中');
  assert.equal(island.setState('unknown'), false);
  harness.flush();
  assert.equal(island.element.style.width, '250px');
  island.destroy();
  assert.equal(island.element.removed, true);
  assert.equal(harness.listeners.has('change'), false);
  assert.equal(island.setState('idle'), false);
});

test('reduced motion jumps directly to target without scheduling frames', () => {
  const h = setup(true);
  const island = h.api.mount(new FakeElement());
  island.setState('listening');
  assert.equal(island.element.style.width, '220px');
  assert.equal(h.queue.size, 0);
  island.destroy();
});

test('destroy cancels any pending spring update', () => {
  const h = setup();
  const island = h.api.mount(new FakeElement());
  island.setState('working');
  assert.ok(h.queue.size > 0);
  island.destroy();
  assert.equal(h.queue.size, 0);
  assert.ok(h.cancelled() >= 1);
});

test('rejects an invalid host', () => {
  const h = setup();
  assert.throws(() => h.api.mount(null), /container Element/);
});

// ---- Upstream parity -------------------------------------------------------
// Independent re-implementation of DesignBookmark morph-island/island.js +
// shared/motion.js, used as the oracle. Values copied from shared/tokens.css.
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
const px = v => parseFloat(v);
function assertClose(actual, expected, msg) {
  assert.ok(Math.abs(actual - expected) < 1e-9, `${msg}: ${actual} != ${expected}`);
}

test('default springs match upstream tokens.css', () => {
  const { api } = setup();
  assert.deepEqual({ ...api.DEFAULT_SPRINGS.width }, { stiffness: 380, damping: 24 });
  assert.deepEqual({ ...api.DEFAULT_SPRINGS.height }, { stiffness: 300, damping: 22 });
  assert.equal(api.DEFAULT_MAX_RADIUS, 32);
});

for (const [name, from, to] of [
  ['growing', 'idle', 'working'],
  ['shrinking (height 1.3x stiffer)', 'working', 'idle'],
]) {
  test(`frame-by-frame parity with upstream integrator: ${name}`, () => {
    const h = setup();
    const island = h.api.mount(new FakeElement(), { initialState: from });
    const views = h.api.DEFAULT_VIEWS;
    const ref = upstreamSim([views[from].width, views[from].height]);
    island.setState(to);
    ref.go([views[to].width, views[to].height]);
    // Frame timings include a long stall to exercise the 1/30 s cap.
    const gaps = [16, 16, 16, 250, 16, 8, 33, 16, 16, 16, 16, 16, 16, 16, 16];
    let first = true;
    for (const gap of gaps) {
      const jobs = [...h.queue.values()];
      assert.equal(jobs.length, 1, 'one pending frame while moving');
      h.queue.clear();
      h.time += gap;
      jobs[0](h.time);
      ref.frame(first ? 1 / 60 : gap / 1000);
      first = false;
      const exp = ref.render();
      const st = island.element.style;
      assertClose(px(st.width), exp.width, 'width');
      assertClose(px(st.height), exp.height, 'height');
      assertClose(px(st.borderRadius), exp.radius, 'radius');
      assertClose(Number(/scale\(([^)]+)\)/.exec(st.transform)?.[1] ?? 1), exp.scale, 'scale');
    }
    island.destroy();
  });
}

test('radius follows height, capped at 32px, and settles exactly on target', () => {
  const h = setup();
  const island = h.api.mount(new FakeElement(), {
    views: { tall: { width: 300, height: 120, label: 'tall' } },
  });
  assert.equal(island.element.style.borderRadius, '19px'); // idle 38px tall -> h/2
  island.setState('tall');
  h.flush();
  assert.equal(h.queue.size, 0, 'animation stops once settled');
  assert.equal(island.element.style.width, '300px');
  assert.equal(island.element.style.height, '120px');
  assert.equal(island.element.style.borderRadius, '32px');
  assert.equal(island.element.style.transform, '');
  island.destroy();
});

test('label-only update does not start a morph', () => {
  const h = setup();
  const island = h.api.mount(new FakeElement(), { initialState: 'working' });
  h.flush();
  island.setState('working', { label: '別の作業' });
  assert.equal(h.queue.size, 0);
  assert.equal(island.element.children[1].textContent, '別の作業');
  island.destroy();
});

test('custom springs and maxRadius options are honoured', () => {
  const h = setup();
  const island = h.api.mount(new FakeElement(), {
    springs: { width: { stiffness: 900, damping: 50 } },
    maxRadius: 10,
  });
  assert.equal(island.element.style.borderRadius, '10px');
  island.setState('working');
  h.flush();
  assert.equal(island.element.style.width, '250px');
  island.destroy();
});

test('switching to reduced motion mid-morph snaps to the target', () => {
  const h = setup();
  const island = h.api.mount(new FakeElement());
  island.setState('working');
  h.flush(3);
  assert.notEqual(island.element.style.width, '250px');
  h.mq.matches = true;
  h.listeners.get('change')();
  assert.equal(h.queue.size, 0);
  assert.equal(island.element.style.width, '250px');
  assert.equal(island.element.style.height, '52px');
  assert.equal(island.element.style.transform, '');
  island.destroy();
});
