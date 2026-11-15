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
