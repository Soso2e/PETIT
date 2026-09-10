const { test } = require('node:test');
const assert = require('node:assert/strict');
const { serviceUrl, isOverlay, isNewer, desktopRelease, RELEASES_URL } = require('../policy.cjs');
test('server trust: HTTPS and loopback only, never credentials/path/query', () => {
  for (const value of ['http://127.0.0.1:8000', 'http://localhost:8000', 'http://[::1]:8000', 'https://petit.example'])
    assert.equal(serviceUrl(value, { originOnly: true }), value);
  for (const value of ['http://192.168.1.2', 'http://127.0.0.1.evil.test', 'file:///tmp/x', 'javascript:alert(1)',
    'https://user:pass@host', 'https://host/path', 'https://host/?secret=x', 'https://host/#x'])
    assert.throws(() => serviceUrl(value, { originOnly: true }));
  assert.equal(serviceUrl('http://localhost:8080/inference'), 'http://localhost:8080/inference');
});
test('privileged bridge only accepts the exact overlay, not another page or query', () => {
  const origin = 'http://127.0.0.1:8000';
  assert.ok(isOverlay(`${origin}/static/desktop/index.html`, origin));
  for (const suffix of ['/', '/static/universe.html', '/static/desktop/index.html?x=1', '/static/desktop/index.html#x'])
    assert.equal(isOverlay(origin + suffix, origin), false);
});
test('stable semver comparisons do not downgrade or select prereleases', () => {
  assert.ok(isNewer('v0.20.1', '0.20.0'));
  assert.ok(isNewer('v0.21.0', '0.20.9'));
  for (const value of ['v0.20.0', 'v0.19.99', 'v0.21.0-rc.1', 'v01.20.1', 'abc']) assert.equal(isNewer(value, '0.20.0'), false);
});
test('updates require an OS/arch Desktop artifact and canonical release link', () => {
  const release = (tag, suffix = 'mac-arm64.dmg') => ({ tag_name: tag, html_url: `${RELEASES_URL}/tag/${tag}`, assets: [{ name: `PETIT-${tag.slice(1)}-${suffix}` }] });
  const good = release('v0.20.1');
  const candidates = [release('v0.22.0', 'win-x64.exe'), { ...release('v0.23.0'), draft: true },
    { ...release('v0.24.0'), prerelease: true }, { ...release('v0.25.0'), html_url: 'https://evil.test' },
    { ...release('v0.26.0'), assets: [] }, good];
  assert.equal(desktopRelease(candidates, '0.20.0', 'darwin', 'arm64'), good);
  assert.equal(desktopRelease(candidates, '0.30.0', 'darwin', 'arm64'), null);
  assert.equal(desktopRelease(candidates, '0.20.0', 'darwin', 'x64'), null);
});
