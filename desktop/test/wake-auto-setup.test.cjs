const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');
const {
  pythonCandidates,
  modelCandidates,
  prepareWakeEnvironment,
} = require('../wake-auto-setup.cjs');

test('bootstrap python candidates are platform appropriate and allow explicit override', () => {
  assert.deepEqual(pythonCandidates('win32', { PETIT_WAKE_BOOTSTRAP_PYTHON: 'C:/Python/python.exe' }), [
    { command: 'C:/Python/python.exe', prefix: [] },
    { command: 'py', prefix: ['-3'] },
    { command: 'python', prefix: [] },
  ]);
  assert.deepEqual(pythonCandidates('darwin', {}), [
    { command: 'python3', prefix: [] },
    { command: 'python', prefix: [] },
  ]);
});

test('wake model discovery prefers explicit/current then generated development model', () => {
  const root = path.join(path.sep, 'repo');
  assert.deepEqual(modelCandidates({
    currentModelPath: '/chosen.onnx', projectRoot: root, resourcesPath: '/resources', env: { PETIT_WAKE_MODEL: '/explicit.onnx' },
  }), [
    '/explicit.onnx',
    '/chosen.onnx',
    path.join(root, 'storage', 'wakeword', 'models', 'v0.1', 'hey_petit.onnx'),
    path.join('/resources', 'wakeword', 'hey_petit.onnx'),
  ]);
});

test('one-click setup creates managed paths, downloads backbones and runs microphone-free diagnostic', async (t) => {
  const temp = await fs.mkdtemp(path.join(os.tmpdir(), 'petit-wake-auto-'));
  t.after(() => fs.rm(temp, { recursive: true, force: true }));
  const projectRoot = path.join(temp, 'repo');
  const userData = path.join(temp, 'user');
  const scripts = path.join(projectRoot, 'scripts', 'wakeword');
  const sourceModel = path.join(projectRoot, 'storage', 'wakeword', 'models', 'v0.1', 'hey_petit.onnx');
  await fs.mkdir(path.dirname(sourceModel), { recursive: true });
  await fs.mkdir(scripts, { recursive: true });
  await fs.writeFile(path.join(scripts, 'runtime.py'), 'runtime');
  await fs.writeFile(path.join(scripts, 'requirements.txt'), 'openwakeword==0.6.0\n');
  await fs.writeFile(sourceModel, Buffer.alloc(2048, 7));

  const calls = [];
  const runImpl = async (command, args) => { calls.push({ command, args }); return 'ok'; };
  const fetchImpl = async () => new Response(Buffer.alloc(2048, 3), { status: 200 });
  const progress = [];
  const result = await prepareWakeEnvironment({
    userData,
    projectRoot,
    resourcesPath: '',
    platform: 'darwin',
    env: { PETIT_WAKE_BOOTSTRAP_PYTHON: '/usr/bin/python3' },
    signal: new AbortController().signal,
    runImpl,
    fetchImpl,
    report: (message) => progress.push(message),
  });

  assert.equal(result.modelPath, path.join(userData, 'wakeword', 'models', 'hey_petit.onnx'));
  assert.equal(result.backbonePath, path.join(userData, 'wakeword', 'backbone'));
  assert.equal((await fs.stat(result.modelPath)).size, 2048);
  for (const name of ['melspectrogram.onnx', 'embedding_model.onnx']) {
    assert.equal((await fs.stat(path.join(result.backbonePath, name))).size, 2048);
  }
  assert.equal(calls.some((call) => call.args.includes('venv')), true);
  assert.equal(calls.some((call) => call.args.includes('pip')), true);
  const diagnostic = calls.find((call) => call.args.includes('--diagnose'));
  assert.ok(diagnostic);
  assert.equal(diagnostic.args.includes('--model'), true);
  assert.equal(diagnostic.args.includes('--backbone'), true);
  assert.equal(progress.at(-1), 'openWakeWord環境の準備が完了しました。');
});
