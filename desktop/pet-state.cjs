'use strict';

// Render-only state: never pass conversation text, credentials, or audio to the pet.
const ACTIVITIES = new Set(['active', 'listening', 'thinking', 'speaking']);
// One-shot reactions: forwarded once to the pet and never stored as a mode.
const EVENTS = new Set(['success', 'failed', 'approval']);
function visualState({ overlayVisible = false, activity = 'active', wakeReady = false, wakeFailed = false, systemIdle = false } = {}) {
  if (overlayVisible) return ACTIVITIES.has(activity) ? activity : 'active';
  if (wakeFailed) return 'error';
  if (systemIdle) return 'sleep';
  return wakeReady ? 'wake' : 'idle';
}
const isPetActivity = (value) => ACTIVITIES.has(value);
const isPetEvent = (value) => EVENTS.has(value);
module.exports = { visualState, isPetActivity, isPetEvent };
