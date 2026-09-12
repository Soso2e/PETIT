const { test } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const {
  resolveWakePython,
  resolveWakeRuntime,
  validateWakeAssets,
} = require('../wake-runtime.cjs');

test('explicit wake runtime and python overrides win', () => {
  const env = { PETIT_WAKE_PYTHON: '/custom/python', PETIT_WAKE_RUNTIME: '/custom/runtime.py' };
  assert.equal(resolveWakePython({ env, platform: 'darwin', existsSync: () => false }), '/custom/python');
  assert.equal(resolveWakeRuntime({ env, existsSync: () => false }), '/custom/runtime.py');
});

test('development venv created by wakeword setup is preferred', () => {
  const projectRoot = path.join(path.sep, 'repo');
  const windowsPython = path.join(projectRoot, 'storage', 'wakeword', '.venv', 'Scripts', 'python.exe');
  const macPython = path.join(projectRoot, 'storage', 'wakeword', '.venv', 'bin', 'python3');
  assert.equal(resolveWakePython({ env: {}, platform: 'win32', projectRoot, existsSync: (file) => file === windowsPython }), windowsPython);
  assert.equal(resolveWakePython({ env: {}, platform: 'darwin', projectRoot, existsSync: (file) => file === macPython }), macPython);
});

test('packaged runtime is selected when repository script is absent', () => {
  const projectRoot = path.join(path.sep, 'repo');
  const resourcesPath = path.join(path.sep, 'app', 'resources');
  const packaged = path.join(resourcesPath, 'wakeword', 'runtime.py');
  assert.equal(resolveWakeRuntime({ env: {}, projectRoot, resourcesPath, existsSync: (file) => file === packaged }), packaged);
});

test('wake assets require runtime, wake model and both backbone models', () => {
  const root = path.join(path.sep, 'wake');
  const files = new Set([
    path.join(root, 'runtime.py'),
    path.join(root, 'hey_petit.onnx'),
    path.join(root, 'backbone', 'melspectrogram.onnx'),
    path.join(root, 'backbone', 'embedding_model.onnx'),
  ]);
  const existsSync = (file) => files.has(file);
  assert.equal(validateWakeAssets({ runtimePath: path.join(root, 'runtime.py'), modelPath: path.join(root, 'hey_petit.onnx'), backbonePath: path.join(root, 'backbone') }, existsSync), '');
  files.delete(path.join(root, 'backbone', 'embedding_model.onnx'));
  assert.equal(validateWakeAssets({ runtimePath: path.join(root, 'runtime.py'), modelPath: path.join(root, 'hey_petit.onnx'), backbonePath: path.join(root, 'backbone') }, existsSync), 'model');
});
