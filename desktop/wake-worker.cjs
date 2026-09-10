'use strict';
const { spawn } = require('node:child_process');
const path = require('node:path');
const python = process.env.PETIT_WAKE_PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
let child, running = false;
process.parentPort.on('message', ({ data }) => {
  if (data.type !== 'start' || running) return;
  running = true;
  child = spawn(python, [path.join(__dirname, '..', 'scripts', 'wakeword', 'runtime.py'), '--model', data.modelPath, '--backbone', data.backbonePath, '--threshold', String(data.threshold ?? 0.45)], { stdio: ['ignore', 'pipe', 'ignore'], windowsHide: true });
  let buffer = '';
  child.stdout.on('data', (chunk) => { buffer += chunk.toString(); const lines = buffer.split('\n'); buffer = lines.pop(); for (const line of lines) { try { const message = JSON.parse(line); const safe = message.type === 'ready' ? { type: 'ready' } : message.type === 'wake' ? { type: 'wake' } : message.type === 'error' ? { type: 'error', code: ['microphone', 'runtime'].includes(message.code) ? message.code : 'runtime' } : null; if (safe) process.parentPort.postMessage(safe); if (safe?.type === 'wake') stop(); } catch {} } });
  child.on('error', () => process.parentPort.postMessage({ type: 'error', code: 'runtime' }));
  child.on('exit', (code) => { if (running && code !== 0) process.parentPort.postMessage({ type: 'error', code: 'runtime' }); });
});
function stop() { running = false; child?.kill(); child = null; }
process.on('disconnect', stop);
