const { test } = require('node:test');
const assert = require('node:assert/strict');
const { visualState, isPetActivity, isPetEvent } = require('../pet-state.cjs');

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
  assert.equal(visualState({ overlayVisible: true, activity: 'speaking' }), 'speaking');
  assert.equal(visualState({ overlayVisible: true, activity: 'arbitrary', wakeFailed: true }), 'active');
});
test('the pet falls asleep only while no conversation or error needs attention', () => {
  assert.equal(visualState({ systemIdle: true }), 'sleep');
  assert.equal(visualState({ systemIdle: true, wakeReady: true }), 'sleep');
  assert.equal(visualState({ systemIdle: true, wakeFailed: true }), 'error');
  assert.equal(visualState({ systemIdle: true, overlayVisible: true, activity: 'thinking' }), 'thinking');
});
test('activities and one-shot events are separate allow-lists', () => {
  for (const value of ['active', 'listening', 'thinking', 'speaking']) assert.ok(isPetActivity(value) && !isPetEvent(value), value);
  for (const value of ['success', 'failed', 'approval']) assert.ok(isPetEvent(value) && !isPetActivity(value), value);
  for (const value of ['error', 'idle', 'sleep', '__proto__', '', undefined]) assert.ok(!isPetActivity(value) && !isPetEvent(value), String(value));
});
