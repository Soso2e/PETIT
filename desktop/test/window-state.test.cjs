const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { fitBounds, windowState } = require('../window-state.cjs');
const area = { x: 0, y: 0, width: 1280, height: 720 };
const fallback = { width: 430, height: 520 };
test('restore bounds, detached displays, oversize and corrupt geometry', () => {
  const saved = { x: 20, y: 40, width: 380, height: 480 };
  assert.deepEqual(fitBounds(saved, fallback, [area]), saved);
  assert.deepEqual(fitBounds({ x: 3000, y: -400, width: 2000, height: 1000 }, fallback, [area]), { x: 0, y: 0, width: 1280, height: 720 });
  const second = { ...area, x: -1280 };
  assert.equal(fitBounds({ ...saved, x: -1000 }, fallback, [area, second]).x, -1000);
  assert.equal(fitBounds({ x: NaN }, fallback, [area]).width, 430);
});
test('persist per-window geometry separately from settings', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'petit-geometry-'));
  try {
    const file = path.join(dir, 'windows.json');
    const saved = { x: 12, y: 30, width: 430, height: 520 };
    windowState(file).remember('overlay', saved);
    assert.deepEqual(windowState(file).get('overlay', fallback, [area]), saved);
    fs.writeFileSync(file, 'invalid');
    assert.equal(windowState(file).get('overlay', fallback, [area]).width, 430);
  } finally { fs.rmSync(dir, { recursive: true, force: true }); }
});
