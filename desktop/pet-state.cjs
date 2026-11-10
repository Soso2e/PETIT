'use strict';

// Render-only state: never pass conversation text, credentials, or audio to the pet.
const ACTIVITIES = new Set(['active', 'listening', 'thinking']);
function visualState({ overlayVisible = false, activity = 'active', wakeReady = false, wakeFailed = false } = {}) {
  if (overlayVisible) return ACTIVITIES.has(activity) ? activity : 'active';
  if (wakeFailed) return 'error';
  return wakeReady ? 'wake' : 'idle';
}
module.exports = { visualState };
