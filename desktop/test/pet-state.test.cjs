const { test } = require('node:test');
const assert = require('node:assert/strict');
const { visualState } = require('../pet-state.cjs');

test('pet is passive by default and shows wake only when the detector is ready', () => {
  assert.equal(visualState(), 'idle');
  assert.equal(visualState({ wakeReady: true }), 'wake');
  assert.equal(visualState({ wakeFailed: true }), 'error');
  assert.equal(visualState({ wakeFailed: true, wakeReady: true }), 'error');
});
test('visible conversation has priority; unknown state never becomes a renderer command', () => {
  assert.equal(visualState({ overlayVisible: true }), 'active');
  assert.equal(visualState({ overlayVisible: true, activity: 'listening', wakeReady: true }), 'listening');
  assert.equal(visualState({ overlayVisible: true, activity: 'thinking' }), 'thinking');
  assert.equal(visualState({ overlayVisible: true, activity: 'arbitrary', wakeFailed: true }), 'active');
});
