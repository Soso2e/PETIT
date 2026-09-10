const { test } = require('node:test');
const assert = require('node:assert/strict');
const { encodeWav, Endpointer } = require('../../frontend/desktop/audio.js');
const { validateWav, transcribe } = require('../transcribe.cjs');
test('mono PCM WAV clips amplitudes and has a validated duration/header', () => {
  const wav = validateWav(encodeWav([new Float32Array([-2, -.5, 0, .5, 2, NaN])], 16000));
  assert.equal(wav.readUInt32LE(24), 16000);
  assert.equal(wav.readInt16LE(44), -32768);
  assert.equal(wav.readInt16LE(52), 32767);
  assert.equal(wav.readInt16LE(54), 0);
  assert.throws(() => validateWav(encodeWav([new Float32Array(16000 * 61)], 16000)));
  const malformed = Buffer.from(wav); malformed.writeUInt32LE(9999, 40);
  assert.throws(() => validateWav(malformed));
  assert.throws(() => validateWav(Buffer.from('not audio')));
});
test('endpoint: silence timeout, speech pause and hard duration bound', () => {
  const silence = new Float32Array(1600), speech = new Float32Array(1600).fill(.1);
  let endpoint = new Endpointer(16000);
  for (let i = 0; i < 79; i++) assert.equal(endpoint.push(silence), false);
  assert.equal(endpoint.push(silence), true);
  endpoint = new Endpointer(16000); endpoint.push(speech); endpoint.push(speech);
  for (let i = 0; i < 11; i++) assert.equal(endpoint.push(silence), false);
  assert.equal(endpoint.push(silence), true);
  endpoint = new Endpointer(16000);
  for (let i = 0; i < 299; i++) assert.equal(endpoint.push(speech), false);
  assert.equal(endpoint.push(speech), true);
});
test('STT uses explicit endpoint, denies redirects, bounds request and accepts text only', async () => {
  const wav = encodeWav([new Float32Array(1600)], 16000), controller = new AbortController();
  const call = (fetcher) => transcribe(wav, { sttUrl: 'http://127.0.0.1:8080/inference' }, controller.signal, fetcher);
  assert.equal(await call(async (url, options) => {
    assert.equal(url, 'http://127.0.0.1:8080/inference');
    assert.equal(options.redirect, 'error');
    assert.equal(options.body.get('language'), 'ja');
    assert.equal(options.body.get('file').size, wav.byteLength);
    return Response.json({ text: ' 今日の予定 ' });
  }), '今日の予定');
  await assert.rejects(call(async () => Response.json({ text: 42 })), /応答形式/);
  await assert.rejects(call(async () => new Response('SECRET UPSTREAM CONTENT', { status: 503 })), /HTTP 503/);
  await assert.rejects(call(async () => { throw new Error('SECRET KEY'); }), /接続できません/);
  await assert.rejects(transcribe(wav, {}, controller.signal), /設定で/);
});
