const { test } = require('node:test');
const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const { testWake, wakeError } = require('../wake-setup.cjs');

function probe(messages, { abort = false, timeout = 15 } = {}) {
  const child = new EventEmitter(); let killed = 0; const sent = [];
  child.kill = () => { killed++; };
  child.postMessage = (message) => sent.push(message);
  const controller = new AbortController();
  const reports = [];
  const promise = testWake({
    fork: () => child,
    options: { modelPath: '/hey_petit.onnx', backbonePath: '/backbone', threshold: 0.45 },
    signal: controller.signal,
    report: (message) => reports.push(message),
    timeout,
  });
  child.emit('spawn');
  for (const message of messages) child.emit('message', { type: message });
  if (abort) controller.abort();
  return { promise, reports, sent, killed: () => killed };
}

test('openWakeWord worker receives only local model settings', async () => {
  const h = probe(['ready', 'wake']);
  await h.promise;
  assert.deepEqual(h.sent, [{ type: 'start', modelPath: '/hey_petit.onnx', backbonePath: '/backbone', threshold: 0.45 }]);
  assert.equal(h.killed(), 1);
  assert.match(h.reports[0], /マイク/);
});

test('initialization alone is not detection; wake succeeds and stops the worker', async () => {
  const ready = probe(['ready']);
  await assert.rejects(ready.promise, /検出できません/);
  assert.equal(ready.killed(), 1);
  const detection = probe(['ready', 'wake']);
  await detection.promise;
  assert.equal(detection.killed(), 1);
});

test('abort, runtime failure and initialization timeout stop the worker', async () => {
  const cancelled = probe([], { abort: true });
  await assert.rejects(cancelled.promise, /中止/);
  assert.equal(cancelled.killed(), 1);
  const failed = probe(['error']);
  await assert.rejects(failed.promise, /openWakeWord/);
  const timeout = probe([], { timeout: 5 });
  await assert.rejects(timeout.promise, /openWakeWord.*タイムアウト/);
});

test('wake errors describe openWakeWord assets without Picovoice credentials', () => {
  const messages = ['runtime', 'model', 'backbone', 'microphone', 'unknown'].map(wakeError);
  assert.match(messages[0], /openWakeWord/);
  assert.match(messages[1], /ONNX/);
  assert.match(messages[2], /melspectrogram\.onnx/);
  for (const message of messages) assert.doesNotMatch(message, /Picovoice|Porcupine|AccessKey/i);
});
