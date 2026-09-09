const { test } = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const source = name => fs.readFileSync(path.join(__dirname, '../../frontend', name), 'utf8');
const tick = () => new Promise(resolve => setImmediate(resolve));
function environment() {
  const nodes = {};
  function element() { return { value: '', disabled: false, textContent: '', classList: { toggle() {} },
    setAttribute() {}, append() {}, before() {}, dispatchEvent() {}, querySelectorAll() { return []; },
    handlers: {}, addEventListener(name, fn) { this.handlers[name] = fn; } }; }
  for (const id of ['messages', 'chat-form', 'input', 'send', 'mic', 'voice-toggle', 'voice-state']) nodes[id] = element();
  let submits = 0;
  nodes['chat-form'].requestSubmit = () => submits++;
  const storage = new Map();
  class Native { start() { this.onstart(); } stop() { this.onend(); } abort() { this.onend(); } }
  let native;
  const context = { console, Blob, AbortController, AbortSignal, Event,
    setTimeout, clearTimeout, navigator: {}, MediaRecorder: null,
    localStorage: { getItem: key => storage.get(key), setItem: (k, v) => storage.set(k, v) },
    document: { getElementById: id => nodes[id], createElement: element, addEventListener() {} },
    MutationObserver: class { observe() {} }, fetch: async () => ({ ok: true, json: async () => ({ configured: false }) }) };
  context.window = { isSecureContext: true, setTimeout() {}, addEventListener() {},
    SpeechRecognition: class extends Native { constructor() { super(); native = this; } } };
  vm.createContext(context);
  return { context, nodes, storage, get native() { return native; }, get submits() { return submits; } };
}
test('native failure with partial result preserves draft and never sends', () => {
  const env = environment(); vm.runInContext(source('voice.js'), env.context);
  env.nodes.input.value = '下書き'; env.nodes.mic.handlers.click();
  const result = [{ transcript: '途中の認識' }]; result.isFinal = true;
  env.native.onresult({ resultIndex: 0, results: [result] });
  env.native.onerror({ error: 'network' }); env.native.onend();
  assert.equal(env.nodes.input.value, '下書き'); assert.equal(env.submits, 0);
  assert.match(env.nodes['voice-state'].textContent, /録音認識/);
});
test('successful dictation appends to draft and submits once', () => {
  const env = environment(); vm.runInContext(source('voice.js'), env.context);
  env.nodes.input.value = '追加して'; env.nodes.mic.handlers.click();
  const result = [{ transcript: '牛乳' }]; result.isFinal = true;
  env.native.onresult({ resultIndex: 0, results: [result] }); env.native.onend();
  assert.equal(env.nodes.input.value, '追加して 牛乳'); assert.equal(env.submits, 1);
});
test('insecure HTTP displays HTTPS requirement', () => {
  const env = environment(); env.context.window.isSecureContext = false;
  vm.runInContext(source('voice.js'), env.context);
  assert.equal(env.nodes.mic.disabled, true);
  assert.match(env.nodes['voice-state'].textContent, /HTTPS/);
});
test('abort during permission request releases late microphone without upload', async () => {
  const env = environment(); let resolve, stopped = 0, uploads = 0, ended = 0;
  env.context.navigator.mediaDevices = { getUserMedia: () => new Promise(r => { resolve = r; }) };
  env.context.fetch = () => { uploads++; };
  vm.runInContext(source('recorded_speech.js'), env.context);
  const speech = new env.context.window.PetitRecordedSpeechRecognition();
  speech.onend = () => ended++;
  speech.start(); speech.abort();
  resolve({ getTracks: () => [{ stop() { stopped++; } }] }); await tick();
  assert.equal(stopped, 1); assert.equal(uploads, 0); assert.equal(ended, 1);
});
test('recording stops microphone before uploading, delivers one final result', async () => {
  const env = environment(); let stopped = 0, results = 0, ended = 0, uploads = 0;
  env.context.navigator.mediaDevices = { getUserMedia: async () => ({ getTracks: () => [{ stop() { stopped++; } }] }) };
  class Recorder {
    static isTypeSupported(type) { return type === 'audio/mp4'; }
    start() { this.state = 'recording'; }
    stop() {
      this.state = 'inactive';
      this.ondataavailable({ data: new Blob(['audio']) });
      queueMicrotask(() => this.onstop?.());
    }
  }
  env.context.MediaRecorder = Recorder; env.context.window.MediaRecorder = Recorder;
  env.context.fetch = async (url, options) => {
    assert.equal(stopped, 1); assert.equal(url, '/api/stt');
    assert.equal(options.headers['Content-Type'], 'audio/mp4'); uploads++;
    return { ok: true, json: async () => ({ text: 'こんにちは' }) };
  };
  vm.runInContext(source('recorded_speech.js'), env.context);
  const speech = new env.context.window.PetitRecordedSpeechRecognition();
  speech.onresult = event => { assert.equal(event.results[0][0].transcript, 'こんにちは'); results++; };
  speech.onend = () => ended++;
  speech.start(); await tick(); speech.stop(); speech.stop(); await tick();
  assert.equal(uploads, 1); assert.equal(results, 1); assert.equal(ended, 1); assert.equal(speech.active, false);
});
test('permission denied reports actionable error and ends without upload', async () => {
  const env = environment(); let message, ended = 0;
  env.context.navigator.mediaDevices = { getUserMedia: async () => { const e = new Error(); e.name = 'NotAllowedError'; throw e; } };
  vm.runInContext(source('recorded_speech.js'), env.context);
  const speech = new env.context.window.PetitRecordedSpeechRecognition();
  speech.onerror = e => { message = e.message; }; speech.onend = () => ended++;
  speech.start(); await tick();
  assert.match(message, /プライバシーとセキュリティ/); assert.equal(ended, 1);
});

test('current Universe DOM initializes microphone without legacy IDs or voice toggle', () => {
  const env = environment();
  const input = env.nodes.input, send = env.nodes.send;
  delete env.nodes.input; delete env.nodes.send; delete env.nodes['voice-toggle'];
  env.nodes['chat-input'] = input;
  env.nodes['chat-form'].querySelector = selector => selector === 'button[type="submit"]' ? send : null;
  vm.runInContext(source('voice.js'), env.context);
  assert.equal(typeof env.nodes.mic.handlers.click, 'function');
  env.nodes.mic.handlers.click();
  const result = [{ transcript: '明日の予定は' }]; result.isFinal = true;
  env.native.onresult({ resultIndex: 0, results: [result] }); env.native.onend();
  assert.equal(input.value, '明日の予定は'); assert.equal(env.submits, 1);
});
