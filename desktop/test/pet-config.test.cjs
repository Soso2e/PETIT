const { test } = require('node:test');
const assert = require('node:assert/strict');
const { PET_DEFAULTS, normalizePet, petAppearance, petWindowSize, nextRoamX, roamStep } = require('../pet-config.cjs');

test('pet appearance defaults and validation keep only safe render values', () => {
  assert.deepEqual(normalizePet({}), { ...PET_DEFAULTS });
  assert.deepEqual(normalizePet({ petSize: '400', petPreset: 'nope', petBody: 'red', petRing: '#12ab9f', petMotion: 'fast', petRoam: 'yes' }),
    { petSize: 200, petPreset: 'pear', petBody: '', petRing: '#12AB9F', petMotion: 'auto', petRoam: false });
  assert.equal(normalizePet({ petSize: 10 }).petSize, 56);
  assert.equal(normalizePet({ petPreset: '__proto__' }).petPreset, 'pear');
  assert.deepEqual(petAppearance({ petSize: 120, petPreset: 'mint', petBody: '#ffffff', petMotion: 'full', serverUrl: 'http://example.invalid' }),
    { size: 120, preset: 'mint', body: '#FFFFFF', ring: '', motion: 'full' });
});
test('window grows with the mascot but keeps room for the caption', () => {
  assert.deepEqual(petWindowSize(96), { width: 132, height: 130 });
  assert.deepEqual(petWindowSize(200), { width: 236, height: 234 });
  assert.deepEqual(petWindowSize('bad'), petWindowSize(96));
});
test('roaming stays inside the work area and moves in bounded steps', () => {
  const area = { x: 0, y: 0, width: 1000, height: 800 };
  const bounds = { x: 980 - 132, y: 600, width: 132, height: 130 };
  for (let i = 0; i < 50; i++) {
    const x = nextRoamX(bounds, area, Math.random);
    assert.ok(x >= 0 && x <= area.width - bounds.width, String(x));
    assert.ok(Math.abs(x - bounds.x) <= 260, String(x));
  }
  assert.equal(nextRoamX({ ...bounds, width: 2000 }, area), bounds.x);
  assert.equal(roamStep(100, 110, 3), 103);
  assert.equal(roamStep(100, 90, 3), 97);
  assert.equal(roamStep(100, 102, 3), 102);
});
