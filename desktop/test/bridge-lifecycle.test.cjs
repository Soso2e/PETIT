const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const tick = () => new Promise(resolve => setImmediate(resolve));
function harness() {
  let resolveMicrophone, stopped = 0, uploads = 0;
  const timers = new Map(); let id = 0;
  const stream = { getTracks: () => [{ stop: () => stopped++ }] };
  const context = {
    navigator: { mediaDevices: { getUserMedia: () => new Promise(resolve => { resolveMicrophone = resolve; }) } },
    window: { petitDesktop: { cancel() {}, transcribe() { uploads++; return Promise.resolve('こんにちは'); } } },
    setTimeout(fn, delay) { const key = ++id; timers.set(key, { fn, delay }); return key; },
    clearTimeout(key) { timers.delete(key); },
    AudioContext: class {
      constructor() { this.sampleRate = 16000; this.state = 'running'; this.audioWorklet = { addModule: async () => {} }; }
      resume() { return Promise.resolve(); }
      close() { this.state = 'closed'; return Promise.resolve(); }
      createMediaStreamSource() { return { connect() {}, disconnect() {} }; }
    },
    AudioWorkletNode: class { constructor() { this.port = {}; } connect() {} disconnect() {} },
    PetitAudio: require('../../frontend/desktop/audio.js'),
    document: { getElementById: () => ({ textContent: '' }) },
  };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(require.resolve('../../frontend/desktop/bridge.js'), 'utf8'), context);
  const recognition = new context.window.PetitDesktopSpeechRecognition();
  return { recognition, timers, resolve: () => resolveMicrophone(stream), get stopped() { return stopped; }, get uploads() { return uploads; } };
}
test('permission timeout ends input; late microphone is released without upload', async () => {
  const h = harness(); let ended = 0, started = 0, error;
  h.recognition.onend = () => ended++; h.recognition.onstart = () => started++;
  h.recognition.onerror = value => { error = value; };
  h.recognition.start(); assert.equal(started, 0);
  [...h.timers.values()][0].fn();
  assert.match(error.message, /時間切れ/); assert.equal(ended, 1);
  h.resolve(); await tick();
  assert.equal(h.stopped, 1); assert.equal(h.uploads, 0); assert.equal(started, 0);
});
test('abort during permission wait invalidates capture and clears its timer', async () => {
  const h = harness(); h.recognition.start(); h.recognition.abort(); h.resolve(); await tick();
  assert.equal(h.timers.size, 0); assert.equal(h.stopped, 1); assert.equal(h.uploads, 0);
});
test('listening begins only after audio graph is ready and replaces preparation timer', async () => {
  const h = harness(); let started = 0, processing = 0;
  h.recognition.onstart = () => started++; h.recognition.onprocessing = () => processing++;
  h.recognition.start(); assert.equal(started, 0); h.resolve(); await tick();
  assert.equal(started, 1); assert.deepEqual([...h.timers.values()].map(x => x.delay), [31000]);
  h.recognition.stop(); assert.equal(processing, 1); assert.equal(h.stopped, 1);
  assert.equal(h.uploads, 0);
});
