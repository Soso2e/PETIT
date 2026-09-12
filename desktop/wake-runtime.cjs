'use strict';
const fs = require('node:fs');
const path = require('node:path');

function firstExisting(candidates, existsSync = fs.existsSync) {
  for (const candidate of candidates) if (candidate && existsSync(candidate)) return candidate;
  return '';
}

function venvCandidates(root, platform = process.platform) {
  if (!root) return [];
  const venv = path.join(root, '.venv');
  return platform === 'win32'
    ? [path.join(venv, 'Scripts', 'python.exe')]
    : [path.join(venv, 'bin', 'python3'), path.join(venv, 'bin', 'python')];
}

function resolveWakePython({
  env = process.env,
  platform = process.platform,
  projectRoot = path.resolve(__dirname, '..'),
  userData = '',
  existsSync = fs.existsSync,
} = {}) {
  if (env.PETIT_WAKE_PYTHON) return env.PETIT_WAKE_PYTHON;
  const candidates = [
    ...venvCandidates(userData ? path.join(userData, 'wakeword') : '', platform),
    ...venvCandidates(path.join(projectRoot, 'storage', 'wakeword'), platform),
  ];
  return firstExisting(candidates, existsSync) || (platform === 'win32' ? 'python' : 'python3');
}

function resolveWakeRuntime({
  env = process.env,
  projectRoot = path.resolve(__dirname, '..'),
  resourcesPath = process.resourcesPath || '',
  existsSync = fs.existsSync,
} = {}) {
  if (env.PETIT_WAKE_RUNTIME) return env.PETIT_WAKE_RUNTIME;
  const development = path.join(projectRoot, 'scripts', 'wakeword', 'runtime.py');
  const packaged = resourcesPath ? path.join(resourcesPath, 'wakeword', 'runtime.py') : '';
  return firstExisting([development, packaged], existsSync) || packaged || development;
}

function validateWakeAssets({ modelPath, backbonePath, runtimePath }, existsSync = fs.existsSync) {
  if (!runtimePath || !existsSync(runtimePath)) return 'runtime';
  if (!modelPath || !existsSync(modelPath)) return 'model';
  if (!backbonePath || !existsSync(path.join(backbonePath, 'melspectrogram.onnx')) ||
      !existsSync(path.join(backbonePath, 'embedding_model.onnx'))) return 'backbone';
  return '';
}

module.exports = { firstExisting, venvCandidates, resolveWakePython, resolveWakeRuntime, validateWakeAssets };
