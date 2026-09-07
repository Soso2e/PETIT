const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
async function run(fail = false) {
  let handler, stopped = 0, released = 0, engineReleased = 0;
  const messages = [];
  class Engine {
    constructor() { if (fail) throw new Error('SECRET-KEY'); }
    frameLength = 512; sampleRate = 16000;
    process() { return 0; }
    release() { engineReleased++; }
  }
  class Recorder {
    sampleRate = 16000; isRecording = false;
    start() { this.isRecording = true; }
    stop() { stopped++; this.isRecording = false; }
    async read() { return new Int16Array(512); }
    release() { released++; }
  }
  vm.runInNewContext(fs.readFileSync(require.resolve('../wake-worker.cjs'), 'utf8'), {
    require: (name) => name.endsWith('porcupine-node') ? { Porcupine: Engine } : { PvRecorder: Recorder },
    process: { parentPort: { on: (_event, callback) => { handler = callback; }, postMessage: (data) => messages.push(data) } },
  });
  await handler({ data: { type: 'start', key: 'SECRET-KEY', keywordPath: '/keyword.ppn', modelPath: '/ja.pv' } });
  return { messages: JSON.parse(JSON.stringify(messages)), stopped, released, engineReleased };
}
test('wake detection releases audio and only emits status/detection, never PCM/key', async () => {
  assert.deepEqual(await run(), { messages: [{ type: 'ready' }, { type: 'wake' }], stopped: 1, released: 1, engineReleased: 1 });
});
test('wake SDK failure reports a sanitized error without credential leakage', async () => {
  assert.deepEqual(await run(true), { messages: [{ type: 'error' }], stopped: 0, released: 0, engineReleased: 0 });
});
