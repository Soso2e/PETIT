'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

function findResources() {
  const candidates = process.platform === 'darwin'
    ? [path.resolve('dist/mac-arm64/PETIT.app/Contents/Resources')]
    : [path.resolve('dist/win-unpacked/resources')];
  return candidates.find((candidate) => fs.existsSync(candidate)) || '';
}

const resources = findResources();
assert.ok(resources, 'packaged resources directory was not found');
const wake = path.join(resources, 'wakeword');
for (const file of ['runtime.py', 'requirements.txt', 'wake-model.json']) {
  assert.ok(fs.existsSync(path.join(wake, file)), `missing packaged wake resource: ${file}`);
}
const manifest = JSON.parse(fs.readFileSync(path.join(wake, 'wake-model.json'), 'utf8'));
if (process.env.PETIT_WAKE_MODEL_REQUIRED === '1') {
  assert.equal(manifest.included, true, 'release/dev package requires hey_petit.onnx');
}
if (manifest.included) {
  assert.ok(fs.existsSync(path.join(wake, 'hey_petit.onnx')), 'manifest says model included but file is missing');
  assert.match(manifest.sha256, /^[a-f0-9]{64}$/);
} else {
  assert.equal(fs.existsSync(path.join(wake, 'hey_petit.onnx')), false, 'model file exists while manifest says excluded');
}
console.log(`Packaged wake resources OK: ${resources}; model=${manifest.included ? manifest.sha256 : 'not included'}`);
