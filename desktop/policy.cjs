'use strict';
const RELEASES_URL = 'https://github.com/Soso2e/PETIT/releases';
const RELEASES_API = 'https://api.github.com/repos/Soso2e/PETIT/releases?per_page=30';
function serviceUrl(value, { originOnly = false } = {}) {
  const url = new URL(value);
  const loopback = ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname);
  if (!(url.protocol === 'https:' || (url.protocol === 'http:' && loopback)) ||
      url.username || url.password || url.hash || url.search ||
      (originOnly && url.pathname !== '/')) throw new Error('HTTPS、またはlocalhostのHTTP URLを指定してください。');
  return originOnly ? url.origin : url.href;
}
function isOverlay(url, serverUrl) {
  return url === `${serverUrl}/static/desktop/index.html`;
}
function isNewer(candidate, current) {
  const parse = (v) => /^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/.exec(v)?.slice(1).map(Number);
  const a = parse(candidate), b = parse(current);
  if (!a || !b) return false;
  for (let i = 0; i < 3; i++) if (a[i] !== b[i]) return a[i] > b[i];
  return false;
}
function desktopRelease(releases, current, platform, arch) {
  if (!Array.isArray(releases)) return null;
  const suffix = platform === 'darwin' ? `mac-${arch}.dmg` : `win-${arch}.exe`;
  return releases.filter((r) => !r.draft && !r.prerelease && isNewer(r.tag_name, current) &&
    r.html_url === `${RELEASES_URL}/tag/${r.tag_name}` &&
    r.assets?.some((a) => a.name === `PETIT-${r.tag_name.replace(/^v/, '')}-${suffix}`))
    .sort((a, b) => isNewer(a.tag_name, b.tag_name) ? -1 : 1)[0] || null;
}
module.exports = { serviceUrl, isOverlay, isNewer, desktopRelease, RELEASES_URL, RELEASES_API };
