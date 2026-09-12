'use strict';
const { spawn } = require('node:child_process');
const { resolveWakePython, resolveWakeRuntime, validateWakeAssets } = require('./wake-runtime.cjs');
let child, running = false;
process.parentPort.on('message', ({ data }) => {
  if (data.type !== 'start' || running) return;
  const python = data.pythonPath || resolveWakePython();
  const runtime = data.runtimePath || resolveWakeRuntime();
  const issue = validateWakeAssets({ modelPath: data.modelPath, backbonePath: data.backbonePath, runtimePath: runtime });
  if (issue) {
    process.parentPort.postMessage({ type: 'error', code: issue });
    return;
  }
  running = true;
  child = spawn(python, [runtime, '--model', data.modelPath, '--backbone', data.backbonePath, '--threshold', String(data.threshold ?? 0.45)], { stdio: ['ignore', 'pipe', 'ignore'], windowsHide: true });
  let buffer = '';
  child.stdout.on('data', (chunk) => { buffer += chunk.toString(); const lines = buffer.split('\n'); buffer = lines.pop(); for (const line of lines) { try { const message = JSON.parse(line); const safe = message.type === 'ready' ? { type: 'ready' } : message.type === 'wake' ? { type: 'wake' } : message.type === 'error' ? { type: 'error', code: ['microphone', 'runtime', 'model'].includes(message.code) ? message.code : 'runtime' } : null; if (safe) process.parentPort.postMessage(safe); if (safe?.type === 'wake') stop(); } catch {} } });
  child.on('error', () => { running = false; process.parentPort.postMessage({ type: 'error', code: 'runtime' }); });
  child.on('exit', (code) => { const wasRunning = running; running = false; child = null; if (wasRunning && code !== 0) process.parentPort.postMessage({ type: 'error', code: 'runtime' }); });
});
function stop() { running = false; child?.kill(); child = null; }
process.on('disconnect', stop);
