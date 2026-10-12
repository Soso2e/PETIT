const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { createHash } = require('node:crypto');
const { installerAsset, downloadVerified } = require('../update-download.cjs');
const bytes = Buffer.from('fixture installer');
const asset = { name: 'PETIT-0.26.0-win-x64.exe', size: bytes.length, digest: `sha256:${createHash('sha256').update(bytes).digest('hex')}`, browser_download_url: 'https://github.com/Soso2e/PETIT/releases/download/v0.26.0/PETIT-0.26.0-win-x64.exe' };
test('installer metadata requires canonical origin, digest and bounded size', () => {
  assert.equal(installerAsset({ tag_name: 'v0.26.0', assets: [asset] }, 'win32', 'x64'), asset);
  for (const changed of [{ digest: null }, { size: 0 }, { size: 999999999 }, { browser_download_url: 'https://evil.test/a.exe' }]) assert.equal(installerAsset({ tag_name: 'v0.26.0', assets: [{ ...asset, ...changed }] }, 'win32', 'x64'), null);
});
test('download verifies bytes before handoff and removes incomplete files', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'petit-verified-test-'));
  try {
    const destination = await downloadVerified(asset, dir, { fetchImpl: async () => new Response(bytes) });
    assert.deepEqual(fs.readFileSync(destination), bytes);
    fs.rmSync(path.dirname(destination), { recursive: true });
    for (const payload of [Buffer.from('wrong'), Buffer.concat([bytes, bytes]), Buffer.from('fixture installeX')]) {
      await assert.rejects(downloadVerified(asset, dir, { fetchImpl: async () => new Response(payload) }));
      assert.deepEqual(fs.readdirSync(dir), []);
    }
  } finally { fs.rmSync(dir, { recursive: true, force: true }); }
});
