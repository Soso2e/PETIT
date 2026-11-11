const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const root = path.join(__dirname, '..');
const source = (file) => fs.readFileSync(path.join(root, file), 'utf8');
const pkg = require('../package.json');

test('pet stays an opt-in, sandboxed local renderer with restricted IPC', () => {
  const main = source('main.cjs');
  assert.match(main, /petEnabled: false/);
  assert.match(main, /petEnabled: raw\.petEnabled === true/);
  assert.match(main, /petEnabled: values\.petEnabled === true/);
  assert.match(main, /on\('pet:open', 'pet'/);
  assert.match(main, /on\('pet:hide', 'pet'/);
  assert.match(main, /event\.senderFrame\?\.url === petUrl/);
  assert.match(main, /pet-preload\.cjs/);
  assert.match(main, /sandbox: true, contextIsolation: true, nodeIntegration: false/);
  assert.match(main, /skipTaskbar: true/);
  assert.match(source('pet-preload.cjs'), /contextBridge\.exposeInMainWorld\('petitPet'/);
  assert.doesNotMatch(source('pet-preload.cjs'), /openExternal|exec\(/);
});
test('pet assets are packaged and have no remote content or autoplay', () => {
  for (const file of ['pet.html', 'pet.css', 'pet.js', 'pet-preload.cjs', 'pet-state.cjs'])
    assert.ok(pkg.build.files.includes(file) || (file.endsWith('.cjs') && pkg.build.files.includes('*.cjs')), file);
  assert.match(source('pet.html'), /object-src 'none'/);
  assert.doesNotMatch(source('pet.html'), /https?:\/\/|<iframe|<audio|<video/);
  assert.match(source('pet.css'), /prefers-reduced-motion: reduce/);
  assert.match(source('pet.css'), /-webkit-app-region: drag/);
  assert.match(source('pet.js'), /Object\.hasOwn\(captions, mode\)/);
});
