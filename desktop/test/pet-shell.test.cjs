const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const root = path.join(__dirname, '..');
const source = (file) => fs.readFileSync(path.join(root, file), 'utf8');
const pkg = require('../package.json');

test('pet stays an opt-in, sandboxed local renderer with restricted IPC', () => {
  const main = source('main.cjs');
  assert.match(main, /petEnabled: false, \.\.\.PET_DEFAULTS/);
  assert.match(main, /petEnabled: raw\.petEnabled === true/);
  assert.match(main, /petEnabled: values\.petEnabled === true/);
  assert.match(main, /on\('pet:open', 'pet'/);
  assert.match(main, /on\('pet:hide', 'pet'/);
  assert.match(main, /event\.senderFrame\?\.url === petUrl/);
  assert.match(main, /pet-preload\.cjs/);
  assert.match(main, /sandbox: true, contextIsolation: true, nodeIntegration: false/);
  assert.match(main, /skipTaskbar: true/);
  const preload = source('pet-preload.cjs');
  assert.match(preload, /contextBridge\.exposeInMainWorld\('petitPet'/);
  assert.doesNotMatch(preload, /openExternal|exec\(|ipcRenderer\.send\(/);
  // The pet can only open the chat or hide itself; everything else is one-way render data.
  assert.deepEqual([...preload.matchAll(/ipcRenderer\.invoke\('([^']+)'/g)].map((m) => m[1]), ['pet:open', 'pet:hide']);
});

test('overlay activity is validated and one-shot reactions are never stored as a mode', () => {
  const main = source('main.cjs');
  assert.match(main, /if \(isPetEvent\(activity\)\) \{ if \(petAlive\(\)\) petWindow\.webContents\.send\('pet:event', activity\); return; \}/);
  assert.match(main, /if \(!isPetActivity\(activity\)\) throw new Error/);
});

test('pet assets are packaged and have no remote content or autoplay', () => {
  for (const file of ['pet.html', 'pet.css', 'pet.js', 'pet-preload.cjs', 'pet-state.cjs', 'pet-config.cjs', 'mascot/petit-mascot.js', 'mascot/petit-mascot.css'])
    assert.ok(pkg.build.files.includes(file) || (file.endsWith('.cjs') && !file.includes('/') && pkg.build.files.includes('*.cjs')), file);
  const html = source('pet.html');
  assert.match(html, /object-src 'none'/);
  assert.doesNotMatch(html, /https?:\/\/|<iframe|<audio|<video/);
  assert.match(html, /mascot\/petit-mascot\.js/);
  assert.match(source('mascot/petit-mascot.css'), /prefers-reduced-motion: reduce/);
  assert.match(source('pet.css'), /-webkit-app-region: drag/);
  assert.match(source('pet.js'), /Object\.hasOwn\(MODES, next\)/);
});

test('desktop mascot copy matches the frontend source of truth', () => {
  for (const file of ['petit-mascot.js', 'petit-mascot.css']) {
    const copy = source(path.join('mascot', file)).replace(/\r\n/g, '\n');
    const truth = fs.readFileSync(path.join(root, '..', 'frontend', 'mascot', file), 'utf8').replace(/\r\n/g, '\n');
    assert.equal(copy, truth, file + ' is stale: run npm run sync:mascot');
  }
});

test('every pet mode and reaction maps to a mascot state', () => {
  const M = require('../mascot/petit-mascot.js');
  const js = source('pet.js');
  const states = [...js.matchAll(/state: '([a-z]+)'/g)].map((m) => m[1]);
  assert.ok(states.length >= 8);
  for (const state of states) assert.ok(M.STATES[state], state);
  for (const [, state] of js.matchAll(/(?:success|failed|approval): '([a-z]+)'/g)) assert.ok(M.STATES[state], state);
});
