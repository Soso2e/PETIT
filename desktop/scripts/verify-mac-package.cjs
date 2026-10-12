const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const { execFileSync } = require('node:child_process');

const signedApps = new Map();
function run(command, args) {
  return execFileSync(command, args, { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] });
}

// Compare bytes, permissions and symlink targets without following framework symlinks.
function manifest(root) {
  const entries = [];
  function walk(relative) {
    const file = path.join(root, relative);
    const stat = fs.lstatSync(file);
    if (stat.isSymbolicLink()) entries.push([relative, 'link', fs.readlinkSync(file)]);
    else if (stat.isDirectory()) {
      entries.push([relative, 'dir', stat.mode & 0o777]);
      for (const name of fs.readdirSync(file).sort()) walk(path.join(relative, name));
    } else entries.push([relative, stat.mode & 0o777, crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex')]);
  }
  walk('');
  return entries;
}

function verifyApp(app) {
  run('codesign', ['--verify', '--deep', '--strict', '--verbose=2', app]);
  assert.ok(fs.existsSync(path.join(app, 'Contents', '_CodeSignature', 'CodeResources')), 'App resource seal is missing');
}

function verifyDmg(app, dmg, expected = manifest(app)) {
  verifyApp(app);
  assert.deepEqual(manifest(app), expected, 'App changed after signing');
  run('hdiutil', ['verify', dmg]);
  const mount = fs.mkdtempSync(path.join(os.tmpdir(), 'petit-dmg-'));
  let attached = false;
  try {
    run('hdiutil', ['attach', '-readonly', '-nobrowse', '-mountpoint', mount, dmg]);
    attached = true;
    const packagedApp = path.join(mount, path.basename(app));
    verifyApp(packagedApp);
    assert.deepEqual(manifest(packagedApp), expected, 'DMG app differs from signed app');
  } finally {
    if (attached) run('hdiutil', ['detach', mount]);
    fs.rmdirSync(mount);
  }
  console.log(`Verified signed app and identical DMG contents: ${dmg}`);
}

function afterSign(context) {
  if (context.electronPlatformName !== 'darwin') return;
  const app = path.join(context.appOutDir, `${context.packager.appInfo.productFilename}.app`);
  verifyApp(app);
  signedApps.set(app, manifest(app));
}

function afterArtifacts(context) {
  const dmgs = context.artifactPaths.filter(file => file.endsWith('.dmg'));
  const macBuild = [...(context.platformToTargets?.keys() || [])].some(platform => platform.name === 'mac');
  if (!macBuild && dmgs.length === 0) return [];
  assert.equal(process.platform, 'darwin', 'macOS package verification requires a macOS builder');
  assert.ok(signedApps.size, 'macOS build has no verified afterSign snapshot; signing may have been skipped');
  for (const [app, expected] of signedApps) {
    verifyApp(app);
    assert.deepEqual(manifest(app), expected, 'App changed after signing');
  }
  for (const dmg of dmgs) {
    const match = [...signedApps].find(([app]) => app.includes(`mac${dmg.includes('-arm64.') ? '-arm64' : ''}${path.sep}`));
    assert.ok(match, 'DMG has no verified afterSign snapshot; signing may have been skipped');
    verifyDmg(match[0], dmg, match[1]);
  }
  return [];
}

module.exports = { manifest, verifyApp, verifyDmg, afterSign, afterArtifacts };
if (require.main === module) {
  const [app, dmg] = process.argv.slice(2);
  assert.ok(app && dmg, 'Usage: node verify-mac-package.cjs APP DMG');
  verifyDmg(path.resolve(app), path.resolve(dmg));
}
