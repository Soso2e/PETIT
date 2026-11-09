const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

test('Developer mode attribution badge contract in app.js', () => {
  const appJs = fs.readFileSync(path.join(__dirname, '..', 'frontend', 'app.js'), 'utf-8');
  const css = fs.readFileSync(path.join(__dirname, '..', 'frontend', 'petit-ui-preferences.css'), 'utf-8');

  // Verify class exists in CSS
  assert.ok(css.includes('.turn-author-badge'), 'turn-author-badge CSS class must exist');
  assert.ok(css.includes('.turn-author-badge--system'), 'turn-author-badge--system CSS class must exist');

  // Verify app.js creates badge with data-developer-only
  assert.ok(appJs.includes('badge.className = "turn-author-badge"'), 'turn-author-badge must be assigned');
  assert.ok(appJs.includes('badge.setAttribute("data-developer-only", "")'), 'badge must have data-developer-only attribute');
  assert.ok(appJs.includes('Antigravity CLI'), 'Provider Antigravity CLI label must be supported');
  assert.ok(appJs.includes('Codex CLI'), 'Provider Codex CLI label must be supported');
  assert.ok(appJs.includes('Claude Code CLI'), 'Provider Claude Code CLI label must be supported');

  // Verify restoreHistory passes modelRoute
  assert.ok(appJs.includes('modelRoute: row.model_route'), 'restoreHistory must pass row.model_route');
});
