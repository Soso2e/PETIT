'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fsp = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { prepareWakeModel } = require('../scripts/prepare-wake-model.cjs');

async function fixture(t) {
  const root = await fsp.mkdtemp(path.join(os.tmpdir(), 'petit-wake-package-'));
  t.after(() => fsp.rm(root, { recursive: true, force: true }));
  return { projectRoot: root, assetsDir: path.join(root, 'assets') };
}

function digest(buffer) {
  return crypto.createHash('sha256').update(buffer).digest('hex');
}

test('copies a local wake model into installer staging with SHA verification', async (t) => {
  const options = await fixture(t);
  const source = path.join(options.projectRoot, 'model.onnx');
  const bytes = Buffer.alloc(4096, 7);
  await fsp.writeFile(source, bytes);
  const result = await prepareWakeModel({
    ...options,
    env: {
      PETIT_WAKE_MODEL_REQUIRED: '1',
      PETIT_WAKE_MODEL_FILE: source,
      PETIT_WAKE_MODEL_SHA256: digest(bytes),
    },
  });
  assert.equal(result.manifest.included, true);
  assert.equal(result.manifest.source, 'local-file');
  assert.equal(result.manifest.sha256, digest(bytes));
  assert.deepEqual(await fsp.readFile(result.destination), bytes);
});

test('rejects a model when SHA-256 does not match', async (t) => {
  const options = await fixture(t);
  const source = path.join(options.projectRoot, 'model.onnx');
  await fsp.writeFile(source, Buffer.alloc(4096, 3));
  await assert.rejects(() => prepareWakeModel({
    ...options,
    env: {
      PETIT_WAKE_MODEL_REQUIRED: '1',
      PETIT_WAKE_MODEL_FILE: source,
      PETIT_WAKE_MODEL_SHA256: '0'.repeat(64),
    },
  }), /SHA-256/);
  await assert.rejects(() => fsp.stat(path.join(options.assetsDir, 'hey_petit.onnx')), /ENOENT/);
});

test('writes an explicit no-model manifest when Wake distribution is not configured', async (t) => {
  const options = await fixture(t);
  const result = await prepareWakeModel({ ...options, env: { PETIT_WAKE_MODEL_REQUIRED: '0' } });
  assert.equal(result.manifest.included, false);
  assert.equal(result.manifest.source, 'none');
  const persisted = JSON.parse(await fsp.readFile(result.manifestPath, 'utf8'));
  assert.equal(persisted.included, false);
  await assert.rejects(() => fsp.stat(path.join(options.assetsDir, 'hey_petit.onnx')), /ENOENT/);
});

test('fails when Wake distribution is explicitly required but no source is configured', async (t) => {
  const options = await fixture(t);
  await assert.rejects(() => prepareWakeModel({
    ...options,
    env: { PETIT_WAKE_MODEL_REQUIRED: '1' },
  }), /Wakeモデルが必要/);
});

test('requires SHA-256 when downloading a model URL', async (t) => {
  const options = await fixture(t);
  await assert.rejects(() => prepareWakeModel({
    ...options,
    env: { PETIT_WAKE_MODEL_URL: 'https://example.com/hey_petit.onnx' },
    fetchImpl: async () => { throw new Error('must not fetch'); },
  }), /SHA256|SHA-256/);
});
