const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { EventEmitter } = require('node:events');
function run() {
  let handler; const messages = []; const child = new EventEmitter(); child.stdout = new EventEmitter(); child.kill = () => {};
  vm.runInNewContext(fs.readFileSync(require.resolve('../wake-worker.cjs'), 'utf8'), {
    require: (name) => name === 'node:child_process' ? { spawn: () => child } : require(name),
    process: { env: {}, platform: 'darwin', parentPort: { on: (_event, callback) => { handler = callback; }, postMessage: (data) => messages.push(data) }, on: () => {} }, __dirname: '/tmp',
  });
  return { handler, child, messages };
}
test('local runtime forwards ready and wake without PCM or credentials', async () => {
  const h = run(); await h.handler({ data: { type: 'start', modelPath: '/hey_petit.onnx', backbonePath: '/backbone', threshold: 0.45 } });
  h.child.stdout.emit('data', Buffer.from('{"type":"ready"}\n{"type":"wake"}\n'));
  assert.deepEqual(JSON.parse(JSON.stringify(h.messages)), [{ type: 'ready' }, { type: 'wake' }]);
});
test('runtime failure is sanitized', async () => {
  const h = run(); await h.handler({ data: { type: 'start', modelPath: '/model.onnx', backbonePath: '/backbone' } });
  h.child.stdout.emit('data', Buffer.from('{"type":"error","code":"microphone","detail":"SECRET"}\n'));
  assert.deepEqual(JSON.parse(JSON.stringify(h.messages)), [{ type: 'error', code: 'microphone' }]);
});
