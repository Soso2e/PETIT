const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { encodeWav, Endpointer } = require('../../frontend/desktop/audio.js');
function setup() {
  let grant, complete, stopped = 0, submitted = 0;
  const state = { textContent: '' };
  const context = { window: { petitDesktop: { cancel: async () => {}, transcribe: () => { submitted++; return new Promise((r) => { complete = r; }); } } },
    navigator: { mediaDevices: { getUserMedia: () => new Promise((r) => { grant = r; }) } },
    document: { getElementById: () => state }, PetitAudio: { encodeWav, Endpointer }, setTimeout, clearTimeout };
  vm.runInNewContext(fs.readFileSync(require.resolve('../../frontend/desktop/bridge.js'), 'utf8'), context);
  const recognition = new context.window.PetitDesktopSpeechRecognition();
  return { recognition, grant: () => grant({ getTracks: () => [{ stop: () => stopped++ }] }), complete: (text) => complete(text),
    stopped: () => stopped, submitted: () => submitted };
}
test('aborting a pending permission prompt releases a late microphone stream', async () => {
  const fixture = setup(); let ended = 0;
  fixture.recognition.onend = () => ended++;
  fixture.recognition.start(); fixture.recognition.abort(); fixture.grant();
  await new Promise(setImmediate);
  assert.equal(fixture.stopped(), 1); assert.equal(ended, 1); assert.equal(fixture.submitted(), 0);
});
test('cancelled STT cannot send a stale transcript or double-finish', async () => {
  const fixture = setup(), recognition = fixture.recognition; let ended = 0, results = 0;
  recognition.onend = () => ended++; recognition.onresult = () => results++;
  recognition.active = true; recognition.rate = 16000;
  recognition.chunks = [new Float32Array(1600).fill(.1)]; recognition.endpoint = { speech: 1600 };
  recognition.stop(); recognition.stop();
  assert.equal(fixture.submitted(), 1);
  recognition.abort(); fixture.complete('実行して'); await new Promise(setImmediate);
  assert.equal(results, 0); assert.equal(ended, 1);
});
test('STT result follows the shared SpeechRecognition final-result contract', async () => {
  const fixture = setup(), recognition = fixture.recognition; let text = '', ended = 0;
  recognition.onend = () => ended++;
  recognition.onresult = (event) => { assert.equal(event.results[0].isFinal, true); text = event.results[0][0].transcript; };
  recognition.active = true; recognition.rate = 16000;
  recognition.chunks = [new Float32Array(1600).fill(.1)]; recognition.endpoint = { speech: 1600 };
  recognition.stop(); fixture.complete('今日の予定'); await new Promise(setImmediate);
  assert.equal(text, '今日の予定'); assert.equal(ended, 1);
});
