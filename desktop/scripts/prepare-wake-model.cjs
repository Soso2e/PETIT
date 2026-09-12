'use strict';
const crypto = require('node:crypto');
const fs = require('node:fs');
const fsp = require('node:fs/promises');
const path = require('node:path');

const MAX_MODEL_BYTES = 20 * 1024 * 1024;

function normalizeSha(value = '') {
  return String(value).trim().toLowerCase().replace(/^sha256:/, '');
}

function sha256(buffer) {
  return crypto.createHash('sha256').update(buffer).digest('hex');
}

async function validateModel(buffer, expectedSha = '') {
  if (!Buffer.isBuffer(buffer) || buffer.length < 1024) throw new Error('Wakeモデルが小さすぎるため不正です。');
  if (buffer.length > MAX_MODEL_BYTES) throw new Error('Wakeモデルがサイズ上限を超えています。');
  const actualSha = sha256(buffer);
  const expected = normalizeSha(expectedSha);
  if (expected && actualSha !== expected) throw new Error(`WakeモデルのSHA-256が一致しません。expected=${expected} actual=${actualSha}`);
  return actualSha;
}

async function downloadModel(url, { fetchImpl = fetch, signal } = {}) {
  const parsed = new URL(url);
  if (parsed.protocol !== 'https:') throw new Error('WakeモデルURLはHTTPSのみ利用できます。');
  const response = await fetchImpl(url, {
    redirect: 'follow',
    signal: signal || AbortSignal.timeout(120000),
  });
  if (!response.ok) throw new Error(`Wakeモデルを取得できませんでした（HTTP ${response.status}）。`);
  if (response.url && new URL(response.url).protocol !== 'https:') throw new Error('Wakeモデルのリダイレクト先がHTTPSではありません。');
  const declared = Number(response.headers?.get?.('content-length') || 0);
  if (declared && declared > MAX_MODEL_BYTES) throw new Error('Wakeモデルがサイズ上限を超えています。');
  const buffer = Buffer.from(await response.arrayBuffer());
  return buffer;
}

async function writeAtomic(destination, buffer) {
  await fsp.mkdir(path.dirname(destination), { recursive: true });
  const temporary = `${destination}.part`;
  await fsp.writeFile(temporary, buffer, { mode: 0o600 });
  await fsp.rename(temporary, destination);
}

async function prepareWakeModel({
  env = process.env,
  projectRoot = path.resolve(__dirname, '../..'),
  assetsDir = path.resolve(__dirname, '../wakeword-assets'),
  fetchImpl = fetch,
} = {}) {
  const destination = path.join(assetsDir, 'hey_petit.onnx');
  const manifestPath = path.join(assetsDir, 'wake-model.json');
  const localDefault = path.join(projectRoot, 'storage', 'wakeword', 'models', 'v0.1', 'hey_petit.onnx');
  const required = env.PETIT_WAKE_MODEL_REQUIRED === '1';
  const expectedSha = normalizeSha(env.PETIT_WAKE_MODEL_SHA256 || '');
  const sourceFile = String(env.PETIT_WAKE_MODEL_FILE || '').trim() || (fs.existsSync(localDefault) ? localDefault : '');
  const sourceUrl = String(env.PETIT_WAKE_MODEL_URL || '').trim();

  await fsp.mkdir(assetsDir, { recursive: true });
  await fsp.rm(destination, { force: true });
  await fsp.rm(manifestPath, { force: true });

  let buffer = null;
  let source = 'none';
  if (sourceFile) {
    buffer = await fsp.readFile(path.resolve(sourceFile));
    source = 'local-file';
  } else if (sourceUrl) {
    if (!expectedSha) throw new Error('URLからWakeモデルを取得する場合はPETIT_WAKE_MODEL_SHA256が必要です。');
    buffer = await downloadModel(sourceUrl, { fetchImpl });
    source = 'url';
  } else if (required) {
    throw new Error('Wakeモデルが必要です。PETIT_WAKE_MODEL_FILE、またはPETIT_WAKE_MODEL_URLとPETIT_WAKE_MODEL_SHA256を指定してください。');
  }

  let actualSha = '';
  if (buffer) {
    actualSha = await validateModel(buffer, expectedSha);
    await writeAtomic(destination, buffer);
  }

  const manifest = {
    schema: 1,
    model: 'hey_petit.onnx',
    included: Boolean(buffer),
    sha256: actualSha,
    source,
  };
  await fsp.writeFile(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`, { mode: 0o600 });
  return { destination: buffer ? destination : '', manifestPath, manifest };
}

if (require.main === module) {
  prepareWakeModel().then(({ manifest }) => {
    process.stdout.write(`Wake model: ${manifest.included ? `included (${manifest.sha256})` : 'not included'}\n`);
  }).catch((error) => {
    console.error(error.message);
    process.exitCode = 1;
  });
}

module.exports = { MAX_MODEL_BYTES, normalizeSha, sha256, validateModel, downloadModel, prepareWakeModel };
