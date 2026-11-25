const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const frontend = path.join(__dirname, '../../frontend');
const source = (name) => fs.readFileSync(path.join(frontend, name), 'utf8');
const M = require('../../frontend/mascot/petit-mascot.js');

test('every emotion uses parts that exist, and every state uses a known emotion and action', () => {
  for (const [name, e] of Object.entries(M.EMOTIONS)) {
    for (const slot of ['eyes', 'mouth', 'brows', 'fx']) if (e[slot]) assert.ok(M.PARTS[slot][e[slot]], `${name}.${slot}=${e[slot]}`);
    if (e.lid) assert.ok(['wide', 'low', 'drowsy'].includes(e.lid), `${name}.lid`);
  }
  for (const [name, s] of Object.entries(M.STATES)) {
    assert.ok(M.EMOTIONS[s.emotion], `${name}.emotion`);
    assert.ok(M.ACTIONS[s.action], `${name}.action`);
  }
  for (const b of M.IDLE_LIFE) assert.ok(M.EMOTIONS[b.emotion] && M.ACTIONS[b.action], JSON.stringify(b));
});

test('every action has a CSS rule and the stylesheet respects reduced motion', () => {
  const css = source('mascot/petit-mascot.css');
  for (const name of Object.keys(M.ACTIONS)) {
    if (name === 'idle') continue;
    assert.match(css, new RegExp(`\\[data-action="${name}"\\]`), name);
  }
  assert.match(css, /@media \(prefers-reduced-motion: reduce\)/);
  assert.match(css, /data-paused/);
  assert.doesNotMatch(css, /filter\s*:|backdrop-filter/, 'no heavy filters');
});

test('colors accept only #RRGGBB and presets resolve to full palettes', () => {
  for (const [key, p] of Object.entries(M.PRESETS)) {
    const c = M.resolveColors(key);
    assert.equal(c.body, p.body);
    for (const value of Object.values(c)) assert.match(value, /^#[0-9a-f]{6}$/i, key);
  }
  const c = M.resolveColors({ preset: 'mint', body: 'url(x)', ring: '#112233' });
  assert.equal(c.body, M.PRESETS.mint.body);
  assert.equal(c.ring, '#112233');
  assert.equal(M.resolveColors({ preset: '__proto__' }).body, M.PRESETS.pear.body);
});

test('static SVG export is self-contained and only contains the chosen expression', () => {
  const svg = M.toStaticSVG({ emotion: 'joy', size: 64, colors: { preset: 'sky' } });
  assert.match(svg, /^<svg xmlns="http:\/\/www\.w3\.org\/2000\/svg" viewBox="0 0 512 512" width="64" height="64">/);
  assert.doesNotMatch(svg, /class="pm-[fs]-/, 'static export must not depend on the stylesheet');
  assert.match(svg, /data-variant="happy"/);
  assert.doesNotMatch(svg, /data-variant="open"/);
  assert.match(svg, new RegExp(M.PRESETS.sky.ring, 'i'));
  assert.doesNotMatch(M.toStaticSVG({ emotion: 'joy', fx: false }), /data-slot="fx"/);
  assert.ok(svg.length < 6000, `small enough for tray/icon use (${svg.length})`);
});

test('web page loads the mascot after the chat scripts and the service worker caches it', () => {
  const html = source('universe.html');
  assert.ok(html.indexOf('"/static/mascot/petit-mascot.js"') > html.indexOf('"/static/voice.js"'));
  assert.ok(html.indexOf('"/static/mascot/petit-mascot-web.js"') > html.indexOf('"/static/mascot/petit-mascot.js"'));
  assert.match(html, /"\/static\/mascot\/petit-mascot\.css"/);
  const sw = source('service-worker.js');
  for (const file of ['petit-mascot.js', 'petit-mascot.css', 'petit-mascot-web.js', 'petit-mascot-web.css'])
    assert.match(sw, new RegExp(`"/static/mascot/${file.replace('.', '\\.')}"`), file);
});

test('chat and voice only emit display hints, never message text', () => {
  for (const file of ['session.js', 'voice.js']) {
    const js = source(file);
    for (const [line] of js.matchAll(/.*petit:mascot.*/g)) {
      assert.match(line, /detail: \{ state \}/, `${file}: ${line.trim()}`);
    }
  }
  const web = source('mascot/petit-mascot-web.js');
  assert.match(web, /pointer-events|INTERACTIVE/);
  assert.match(web, /visibilitychange/);
  assert.doesNotMatch(web, /fetch\(|XMLHttpRequest|sendBeacon/, 'the mascot never talks to the network');
});


test('flat shaded mascot preserves shadow, cheeks, round eyes, ring mouth and body-color feet', () => {
  const c = M.resolveColors({ preset: 'mint', ring: '#123456' });
  assert.equal(c.mouth, c.ring);
  const svg = M.toStaticSVG({ emotion: 'neutral', colors: { preset: 'pear' } });
  assert.doesNotMatch(svg, /linearGradient|pm-g-|opacity=".9" transform="rotate\(-28/);
  assert.match(svg, /class="pm-shadow"/);
  assert.match(svg, /class="pm-body"><path fill="#FFE9B9"/);
  assert.match(svg, /data-slot="cheeks" data-variant="on"/);
  assert.match(svg, /data-slot="eyes" data-variant="open"/);
  assert.match(svg, /M192 297a19 19/);
  assert.match(svg, /M211 289a6 6/);
  assert.match(svg, /class="pm-foot pm-foot-l"><path fill="#FFE9B9"/);
  assert.match(svg, /data-slot="mouth" data-variant="soft"><path fill="none" stroke="#F37865"/);
});

test('ring inertia layer, action lag keyframes, and web spring physics are wired', () => {
  const svg = M.toStaticSVG({ emotion: 'neutral', colors: { preset: 'pear' } });
  assert.match(svg, /class="pm-ring pm-ring-back"><g class="pm-ring-inertia">/);
  assert.match(svg, /class="pm-ring pm-ring-front"><g class="pm-ring-inertia">/);
  const css = source('mascot/petit-mascot.css');
  assert.match(css, /\.pm-ring-inertia\s*\{/);
  for (const name of ['walk', 'run', 'hop', 'jump', 'celebrate', 'dance', 'nod', 'surprise', 'land']) {
    assert.match(css, new RegExp(`\\[data-action="${name}"\\]\\s+\\.pm-ring`), name);
  }
  const js = source('mascot/petit-mascot.js');
  assert.match(js, /setRingOffset\(/);
  assert.match(js, /data-ring-physics/);
  assert.match(css, /\[data-ring-physics\]\[data-action="land"\]\s+\.pm-ring/);
  const web = source('mascot/petit-mascot-web.js');
  assert.match(web, /stepRing\(/);
  assert.match(web, /setRingOffset\(/);
});

test('dragging and releasing with momentum throws the web mascot with wall bounce and landing', () => {
  const vm = require('node:vm');
  const webSource = source('mascot/petit-mascot-web.js');

  function makeEl(tag) {
    const listeners = new Map();
    const classes = new Set();
    const styles = new Map();
    return {
      tagName: tag.toUpperCase(),
      className: '',
      title: '',
      textContent: '',
      dataset: {},
      children: [],
      classList: {
        add: (c) => classes.add(c),
        remove: (c) => classes.delete(c),
        toggle: (c, f) => (f ? classes.add(c) : classes.delete(c)),
        contains: (c) => classes.has(c),
      },
      style: {
        transform: '',
        setProperty: (k, v) => styles.set(k, v),
        removeProperty: (k) => styles.delete(k),
        getPropertyValue: (k) => styles.get(k) || '',
      },
      setAttribute() {},
      removeAttribute() {},
      toggleAttribute() {},
      setPointerCapture() {},
      append(...nodes) { this.children.push(...nodes); },
      remove() {},
      contains(node) { return node === this || this.children.some((c) => c.contains?.(node)); },
      querySelector() { return null; },
      querySelectorAll() { return []; },
      addEventListener(type, fn) {
        if (!listeners.has(type)) listeners.set(type, []);
        listeners.get(type).push(fn);
      },
      removeEventListener(type, fn) {
        const list = listeners.get(type);
        if (list) listeners.set(type, list.filter((f) => f !== fn));
      },
      dispatch(type, event) {
        for (const fn of (listeners.get(type) || [])) fn({ type, ...event });
      },
    };
  }

  let nowMs = 1000;
  let rafId = 0;
  const rafQueue = new Map();
  const body = makeEl('body');
  const docEl = makeEl('html');
  const mascotState = { facing: 1, reactions: [], ringOffsets: [] };

  const sandbox = {
    Math, Date, Number, String, Object, Array, Map, Set, JSON, Error,
    parseFloat, parseInt, isFinite,
    setTimeout: () => 1,
    clearTimeout: () => {},
    setInterval: () => 1,
    clearInterval: () => {},
    queueMicrotask: (fn) => fn(),
    performance: { now: () => nowMs },
    requestAnimationFrame: (cb) => { const id = ++rafId; rafQueue.set(id, cb); return id; },
    cancelAnimationFrame: (id) => rafQueue.delete(id),
    CustomEvent: class CustomEvent { constructor(type, init) { this.type = type; this.detail = init?.detail; } },
    Element: class Element {},
    localStorage: { getItem: () => null, setItem: () => {} },
    getComputedStyle: () => ({ getPropertyValue: () => '0' }),
    document: {
      readyState: 'complete',
      hidden: false,
      body,
      documentElement: docEl,
      activeElement: null,
      createElement: (tag) => makeEl(tag),
      getElementById: () => null,
      querySelector: () => null,
      elementsFromPoint: () => [],
      addEventListener() {},
      removeEventListener() {},
      dispatchEvent() {},
    },
    window: null,
  };
  sandbox.window = {
    innerWidth: 800,
    innerHeight: 600,
    matchMedia: () => ({ matches: false }),
    addEventListener() {},
    removeEventListener() {},
    dispatchEvent() {},
    PetitMascot: {
      PRESETS: M.PRESETS,
      STATES: M.STATES,
      IDLE_LIFE: M.IDLE_LIFE,
      MOTION_MODES: M.MOTION_MODES,
      isHex: M.isHex,
      resolveColors: M.resolveColors,
      pickWeighted: M.pickWeighted,
      create() {
        return {
          motionAllowed: () => true,
          setFacing: (d) => { mascotState.facing = d; },
          setState() {},
          setEmotion() {},
          setAction() {},
          setColors() {},
          setSize() {},
          setMotion() {},
          setLite() {},
          look() {},
          clearReaction() {},
          react: (e, a) => { mascotState.reactions.push({ e, a }); },
          setRingOffset: (x, y, r) => { mascotState.ringOffsets.push({ x, y, r }); },
          pause() {},
          destroy() {},
        };
      },
    },
  };
  sandbox.globalThis = sandbox;
  vm.runInNewContext(webSource, sandbox);

  const layer = body.children[0];
  const holder = layer.children[0];
  const pos = () => {
    const m = /translate3d\((-?\d+)px,\s*(-?\d+)px/.exec(holder.style.transform);
    assert.ok(m, `expected translate3d transform, got ${holder.style.transform}`);
    return { x: Number(m[1]), y: Number(m[2]) };
  };
  const stepFrames = (count, stepMs = 16) => {
    for (let i = 0; i < count; i++) {
      nowMs += stepMs;
      const pending = Array.from(rafQueue.entries());
      rafQueue.clear();
      for (const [, cb] of pending) cb(nowMs);
    }
  };

  // 1) 右斜め上に勢いよく投げる → 右へ飛んで壁で跳ね返り、最終的に床へ着地する
  mascotState.reactions.length = 0;
  holder.dispatch('pointerdown', { button: 0, pointerId: 1, clientX: 200, clientY: 300 });
  nowMs += 16; holder.dispatch('pointermove', { pointerId: 1, clientX: 230, clientY: 280 });
  nowMs += 16; holder.dispatch('pointermove', { pointerId: 1, clientX: 280, clientY: 245 });
  nowMs += 16; holder.dispatch('pointermove', { pointerId: 1, clientX: 330, clientY: 210 });
  const releasePos = pos();
  nowMs += 8; holder.dispatch('pointerup', { pointerId: 1, clientX: 330, clientY: 210 });

  let maxX = releasePos.x;
  let minY = releasePos.y;
  let bouncedLeft = false;
  let prevX = releasePos.x;
  for (let i = 0; i < 180; i++) {
    stepFrames(1, 16);
    const p = pos();
    if (p.x > maxX) maxX = p.x;
    if (p.y < minY) minY = p.y;
    if (maxX >= 720 && p.x < prevX) bouncedLeft = true;
    prevX = p.x;
  }
  assert.ok(maxX > releasePos.x + 200, `expected horizontal flight beyond release x=${releasePos.x}, got maxX=${maxX}`);
  assert.ok(minY < releasePos.y - 20, `expected upward arc above release y=${releasePos.y}, got minY=${minY}`);
  assert.ok(bouncedLeft, 'expected bounce off right viewport wall');
  assert.ok(mascotState.reactions.some((r) => r.a === 'land'), 'expected mascot to land after throw');

  // 2) 持ち上げて静止してから離す → 横へ飛ばず真下に落下する
  mascotState.reactions.length = 0;
  holder.dispatch('pointerdown', { button: 0, pointerId: 2, clientX: 300, clientY: 200 });
  nowMs += 16; holder.dispatch('pointermove', { pointerId: 2, clientX: 320, clientY: 200 });
  nowMs += 200; // 静止待ち
  const stillPos = pos();
  holder.dispatch('pointerup', { pointerId: 2, clientX: 320, clientY: 200 });
  stepFrames(60, 16);
  const droppedPos = pos();
  assert.equal(droppedPos.x, stillPos.x, 'stationary release should drop straight down');
  assert.ok(droppedPos.y > stillPos.y + 100, 'stationary release should fall to the floor');
  assert.ok(mascotState.reactions.some((r) => r.a === 'land'), 'expected mascot to land after straight drop');
});
