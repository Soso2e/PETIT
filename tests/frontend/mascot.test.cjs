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
  const web = source('mascot/petit-mascot-web.js');
  assert.match(web, /stepRing\(/);
  assert.match(web, /setRingOffset\(/);
});
