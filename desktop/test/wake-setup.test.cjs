const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { EventEmitter } = require('node:events');
const { targetPlatform, prepareModels, testWake, MODEL_HASH, API_URL } = require('../wake-setup.cjs');
const { createHash } = require('node:crypto');
// Substitute a known digest for synthetic bytes; no network or account is required.
const vm = require('node:vm');
async function fixture(t) {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'petit-wake-test-'));
  t.after(() => fs.rm(directory, { recursive: true, force: true }));
  const model = Buffer.alloc(128, 42);
  const source = (await fs.readFile(require.resolve('../wake-setup.cjs'), 'utf8')).replace(MODEL_HASH, createHash('sha256').update(model).digest('hex'));
  const context = { require, module: { exports: {} }, process, Buffer, URL, AbortSignal, fetch, setTimeout, clearTimeout };
  vm.runInNewContext(source, context);
  return { directory, model, prepare: context.module.exports.prepareModels, signal: new AbortController().signal, target: { platform: 'mac', arch: 'arm64' }, key: 'SECRET' };
}
test('Mac and Windows architectures map to official Model API platforms', () => {
  for (const arch of ['arm64', 'x64']) {
    assert.deepEqual(targetPlatform('darwin', arch), { platform: 'mac', arch });
    assert.deepEqual(targetPlatform('win32', arch), { platform: 'windows', arch });
  }
  assert.throws(() => targetPlatform('win32', 'ia32'));
  assert.throws(() => targetPlatform('linux', 'x64'));
});
test('generation saves a verified pair and strips key at redirect; successful pair can be reused offline', async (t) => {
  const f = await fixture(t); const calls = [];
  const result = await f.prepare({ ...f, fetchImpl: async (url, options) => {
    calls.push({ url, options });
    if (url === API_URL) return new Response(null, { status: 303, headers: { location: 'https://console.picovoice.ai/model.ppn' } });
    return new Response(calls.length === 1 ? f.model : Buffer.alloc(128, 12));
  } });
  assert.equal(calls[1].options.headers['x-api-key'], 'SECRET');
  assert.deepEqual(JSON.parse(calls[1].options.body), { platform: 'mac', phrase: 'へいプティ' });
  assert.equal(calls[2].options.headers, undefined);
  assert.equal((await fs.readFile(result.modelPath)).length, 128);
  const reused = await f.prepare({ ...f, cached: result.metadata, fetchImpl: () => { throw new Error('must not fetch'); } });
  assert.equal(reused.keywordPath, result.keywordPath);
  assert.equal(reused.staging, undefined);
});
test('key denial and untrusted redirect have actionable safe errors and remove staging files', async (t) => {
  for (const response of [new Response('SECRET', { status: 403 }), new Response(null, { status: 303, headers: { location: 'https://evil.invalid/model' } })]) {
    const f = await fixture(t);
    await assert.rejects(f.prepare({ ...f, fetchImpl: async (url) => url === API_URL ? response : new Response(f.model) }), (error) => !error.message.includes('SECRET'));
    assert.deepEqual(await fs.readdir(f.directory), []);
  }
});
test('bad language hash, text payloads and network failures cannot install a model', async (t) => {
  const f = await fixture(t);
  for (const fetchImpl of [async () => new Response(Buffer.alloc(128)), async () => new Response('bad'), async () => { throw new Error('SECRET'); }]) {
    await assert.rejects(f.prepare({ ...f, fetchImpl }));
    assert.deepEqual(await fs.readdir(f.directory), []);
  }
});
function probe(messages, abort = false) {
  const child = new EventEmitter(); let killed = 0;
  child.kill = () => { killed++; };
  const controller = new AbortController();
  const reports = [];
  const promise = testWake({ fork: () => child, options: {}, signal: controller.signal, report: (s) => reports.push(s), timeout: 15 });
  for (const message of messages) child.emit('message', { type: message });
  if (abort) controller.abort();
  return { promise, reports, killed: () => killed };
}
test('initialization alone is not readiness; actual detection succeeds and stops the worker', async () => {
  const ready = probe(['ready']);
  await assert.rejects(ready.promise, /検出できません/);
  assert.equal(ready.killed(), 1);
  const detection = probe(['ready', 'wake']);
  await detection.promise;
  assert.equal(detection.killed(), 1);
});
test('abort, native failure and initialization timeout stop the worker', async () => {
  const cancelled = probe([], true); await assert.rejects(cancelled.promise, /中止/);
  assert.equal(cancelled.killed(), 1);
  const failed = probe(['error']); await assert.rejects(failed.promise, /初期化/);
  const timeout = probe([]); await assert.rejects(timeout.promise, /タイムアウト/);
});
