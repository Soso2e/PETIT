const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const { verifyApp, afterSign, afterArtifacts } = require('../scripts/verify-mac-package.cjs');

test('macOS packaging rejects modified resources even after re-signing', { skip: process.platform !== 'darwin' }, () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'petit-signature-test-'));
  const appOutDir = path.join(root, 'mac-arm64');
  const app = path.join(appOutDir, 'PETIT.app');
  try {
    fs.mkdirSync(path.join(app, 'Contents', 'MacOS'), { recursive: true });
    fs.mkdirSync(path.join(app, 'Contents', 'Resources'));
    fs.copyFileSync('/usr/bin/true', path.join(app, 'Contents', 'MacOS', 'PETIT'));
    fs.writeFileSync(path.join(app, 'Contents', 'Info.plist'), '<?xml version="1.0"?><plist version="1.0"><dict><key>CFBundleExecutable</key><string>PETIT</string><key>CFBundleIdentifier</key><string>jp.soso2e.petit.signature-test</string><key>CFBundlePackageType</key><string>APPL</string></dict></plist>');
    const resource = path.join(app, 'Contents', 'Resources', 'fixture.txt');
    fs.writeFileSync(resource, 'original');
    const sign = () => execFileSync('codesign', ['--force', '--sign', '-', app], { stdio: 'pipe' });
    sign();
    afterSign({ electronPlatformName: 'darwin', appOutDir, packager: { appInfo: { productFilename: 'PETIT' } } });
    fs.writeFileSync(resource, 'modified');
    assert.throws(() => verifyApp(app));
    sign();
    verifyApp(app);
    assert.throws(() => afterArtifacts({ artifactPaths: [path.join(root, 'PETIT-test-mac-arm64.dmg')] }), /App changed after signing/);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});
