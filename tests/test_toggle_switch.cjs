// Standalone test: node --test tests/test_toggle_switch.cjs
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

class FakeElement {
  constructor(tag = 'div') {
    this.tagName = tag.toUpperCase();
    this.children = [];
    this.parentNode = null;
    this.attributes = {};
    this.listeners = {};
    const props = {};
    this.style = { setProperty: (k, v) => { props[k] = v; }, getPropertyValue: k => props[k] };
    this.dataset = {};
    this.textContent = '';
    const classes = new Set();
    this.classList = { add: c => classes.add(c), remove: c => classes.delete(c), contains: c => classes.has(c) };
  }
  appendChild(n) { if (n.parentNode) n.parentNode._detach(n); n.parentNode = this; this.children.push(n); return n; }
  append(...ns) { ns.forEach(n => this.appendChild(n)); }
  insertBefore(n, ref) {
    if (n.parentNode) n.parentNode._detach(n);
    n.parentNode = this;
    const i = this.children.indexOf(ref);
    this.children.splice(i < 0 ? this.children.length : i, 0, n);
    return n;
  }
  _detach(n) { this.children = this.children.filter(c => c !== n); n.parentNode = null; }
  remove() { this.removed = true; if (this.parentNode) this.parentNode._detach(this); }
  setAttribute(k, v) { this.attributes[k] = String(v); }
  removeAttribute(k) { delete this.attributes[k]; }
  addEventListener(e, f) { (this.listeners[e] ||= []).push(f); }
  removeEventListener(e, f) { this.listeners[e] = (this.listeners[e] || []).filter(x => x !== f); }
  dispatch(e) { (this.listeners[e] || []).forEach(f => f()); }
  closest(sel) { for (let n = this; n; n = n.parentNode) if (n.tagName === sel.toUpperCase()) return n; return null; }
  set className(v) { this._className = v; }
  get className() { return this._className; }
}

class FakeInput extends FakeElement {
  constructor() { super('input'); this.type = ''; this.disabled = false; }
  // A real click flips the internal state without calling the JS setter.
  click() { if (!this.disabled) { this._checked = !this._checked; this.dispatch('change'); } }
}
// Mirror the browser: `checked` is an accessor on the prototype.
Object.defineProperty(FakeInput.prototype, 'checked', {
  configurable: true,
  get() { return !!this._checked; },
  set(v) { this._checked = !!v; },
});

function setup(reduced = false) {
  const queue = new Map();
  let nextId = 0;
  const mq = { matches: reduced, addEventListener() {}, removeEventListener() {} };
  const window = {
    HTMLInputElement: FakeInput,
    matchMedia: () => mq,
    requestAnimationFrame(cb) { const id = ++nextId; queue.set(id, cb); return id; },
    cancelAnimationFrame(id) { queue.delete(id); },
  };
  const ctx = {
    window,
    Element: FakeElement,
    document: { createElement: t => (t === 'input' ? new FakeInput() : new FakeElement(t)) },
    requestAnimationFrame: window.requestAnimationFrame,
    cancelAnimationFrame: window.cancelAnimationFrame,
  };
  const file = path.join(__dirname, '..', 'frontend', 'components', 'toggle-switch.js');
  vm.runInNewContext(fs.readFileSync(file, 'utf8'), ctx);
  return {
    api: window.PetitToggleSwitch,
    queue,
    // Run frames; returns the knob's right edge (px) per frame.
    flush(max = 600) {
      const xs = [];
      let time = 0;
      for (let i = 0; i < max && queue.size; i++) {
        const jobs = [...queue.values()];
        queue.clear();
        time += 16;
        jobs.forEach(cb => cb(time));
        if (this.lastKnob) {
          const k = this.lastKnob.style;
          // right edge of the knob = translate + width
          xs.push(parseFloat(/translateX\(([-\d.]+)px\)/.exec(k.transform)[1]) + parseFloat(k.width));
        }
      }
      return xs;
    },
  };
}

const knobOf = sw => sw.element.children.find(c => c.className === 'petit-switch__track').children[0];

test('keeps the upstream spring values', () => {
  const { api } = setup();
  assert.equal(api.springs.position.stiffness, 320);
  assert.equal(api.springs.position.damping, 18);
  assert.equal(api.springs.stretch.stiffness, 300);
  assert.equal(api.springs.stretch.damping, 20);
});

test('mount builds an accessible switch row and flips with motion', () => {
  const h = setup();
  const host = new FakeElement();
  const changes = [];
  const sw = h.api.mount(host, { label: '通知', description: '同期失敗を知らせる', onChange: v => changes.push(v) });
  assert.equal(host.children[0], sw.element);
  assert.equal(sw.input.attributes.role, 'switch');
  assert.equal(sw.isChecked(), false);
  h.lastKnob = knobOf(sw);

  sw.input.click();
  assert.deepEqual(changes, [true]);
  assert.equal(sw.element.dataset.checked, 'true');
  const xs = h.flush();
  assert.equal(h.queue.size, 0, 'animation stops when settled');
  // The knob overshoots past its end (bounce) and the stretch makes it wider mid-flight.
  assert.ok(Math.max(...xs) > 46.5, 'leading edge overshoots past the end (bounce)');
  assert.equal(h.lastKnob.style.transform, 'translateX(20.00px)');
  assert.equal(h.lastKnob.style.width, '26.00px');
});

test('setting input.checked from code snaps without animation', () => {
  const h = setup();
  const label = new FakeElement('label');
  const input = new FakeInput();
  input.type = 'checkbox';
  label.appendChild(input);
  const sw = h.api.enhance(input);
  input.checked = true;              // what setup.js does after loading settings
  assert.equal(h.queue.size, 0);
  assert.equal(knobOf(sw).style.transform, 'translateX(20.00px)');
  assert.equal(input.checked, true);
  assert.equal(h.api.enhance(input), sw, 'enhance is idempotent');
  sw.destroy();
  assert.equal(input.parentNode, label, 'input returns to its place');
  assert.equal(Object.hasOwn(input, 'checked'), false, 'checked accessor restored');
});

test('reduced motion snaps on user flips too', () => {
  const h = setup(true);
  const sw = h.api.mount(new FakeElement(), { label: 'x' });
  sw.input.click();
  assert.equal(h.queue.size, 0);
  assert.equal(knobOf(sw).style.transform, 'translateX(20.00px)');
});
