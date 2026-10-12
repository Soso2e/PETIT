const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const workflow = fs.readFileSync(path.join(__dirname, '../../.github/workflows/desktop.yml'), 'utf8');
const pkg = require('../package.json');

test('tag releases use ad-hoc macOS signing without Apple credentials', () => {
  assert.match(workflow, /name: Build ad-hoc macOS personal release/);
  assert.match(workflow, /if: startsWith\(github\.ref, 'refs\/tags\/v'\) && matrix\.platform == 'mac'\n\s+run: npm run build:mac:personal/);
  assert.doesNotMatch(workflow, /MAC_CSC_LINK|APPLE_APP_SPECIFIC_PASSWORD|APPLE_TEAM_ID|Build signed and notarized macOS release/);
  assert.match(pkg.scripts['build:mac:personal'], /-c\.mac\.identity=-/);
  assert.match(pkg.scripts['build:mac:personal'], /-c\.mac\.notarize=false/);
  assert.doesNotMatch(pkg.scripts['build:mac:personal'], /artifactName/);
  assert.match(workflow, /- name: Verify packaged Wake resources/);
  assert.match(workflow, /pattern: PETIT-\*-release/);
});

test('manual macOS build remains a development artifact', () => {
  assert.match(workflow, /if: github\.event_name == 'workflow_dispatch' && matrix\.platform == 'mac'\n\s+run: npm run build:mac:development/);
  assert.match(pkg.scripts['build:mac:development'], /development/);
});
