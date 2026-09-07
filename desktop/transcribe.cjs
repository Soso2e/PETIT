'use strict';
const { serviceUrl } = require('./policy.cjs');
const MAX_BYTES = 60 * 48000 * 2 + 44;
function validateWav(input) {
  const wav = Buffer.from(input);
  if (wav.length < 46 || wav.length > MAX_BYTES || wav.toString('ascii', 0, 4) !== 'RIFF' ||
      wav.toString('ascii', 8, 12) !== 'WAVE' || wav.toString('ascii', 12, 16) !== 'fmt ' ||
      wav.readUInt32LE(16) !== 16 || wav.readUInt16LE(20) !== 1 || wav.readUInt16LE(22) !== 1 ||
      wav.readUInt16LE(34) !== 16 || wav.toString('ascii', 36, 40) !== 'data' ||
      wav.readUInt32LE(40) !== wav.length - 44 || wav.readUInt32LE(4) !== wav.length - 8 ||
      (wav.length - 44) % 2) throw new Error('音声データの形式または長さが不正です。');
  const rate = wav.readUInt32LE(24);
  if (rate < 8000 || rate > 48000 || (wav.length - 44) / 2 / rate > 60 ||
      wav.readUInt32LE(28) !== rate * 2 || wav.readUInt16LE(32) !== 2) throw new Error('録音は60秒以内にしてください。');
  return wav;
}
async function transcribe(input, config, signal, fetcher = fetch) {
  const wav = validateWav(input);
  if (!config.sttUrl) throw new Error('設定で音声認識サーバーURLを指定してください。');
  const form = new FormData();
  form.append('file', new Blob([wav], { type: 'audio/wav' }), 'speech.wav');
  form.append('language', 'ja');
  form.append('response_format', 'json');
  form.append('model', config.sttModel || 'whisper-1');
  const headers = process.env.PETIT_DESKTOP_STT_KEY ? { Authorization: `Bearer ${process.env.PETIT_DESKTOP_STT_KEY}` } : {};
  let response;
  try {
    response = await fetcher(serviceUrl(config.sttUrl), { method: 'POST', body: form, headers,
      redirect: 'error', signal: AbortSignal.any([signal, AbortSignal.timeout(60000)]) });
  } catch {
    throw new Error(signal.aborted ? '音声入力を中止しました。' : '音声認識サーバーへ接続できません。URL・起動状態を確認してください。');
  }
  if (!response.ok) throw new Error(`音声認識に失敗しました（HTTP ${response.status}）。`);
  let data;
  try { data = await response.json(); } catch { throw new Error('音声認識サーバーの応答形式が不正です。'); }
  if (typeof data.text !== 'string' || data.text.length > 12000) throw new Error('音声認識サーバーの応答形式が不正です。');
  return data.text.trim();
}
module.exports = { validateWav, transcribe };
