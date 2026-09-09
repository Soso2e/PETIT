'use strict';
const fs = require('node:fs/promises');
const path = require('node:path');
const { createHash } = require('node:crypto');
const MODEL_URL = 'https://raw.githubusercontent.com/Picovoice/porcupine/3d3bdb0a4e0c0c8374b8a94d3590666b214686f7/lib/common/porcupine_params_ja.pv';
const MODEL_HASH = '5aed34bc73e8da6c04e17536e43ab878d4e9bfc54bd61e9d195854d66a77518b';
const API_URL = 'https://rest.picovoice.ai/ja/api/ppn';
const PHRASE = 'へいプティ';
const hash = (data) => createHash('sha256').update(data).digest('hex');
function targetPlatform(os = process.platform, arch = process.arch) {
  if (!['darwin', 'win32'].includes(os) || !['arm64', 'x64'].includes(arch))
    throw new Error('このOS / CPUは自動設定の対象外です。Mac / Windowsの64ビット版を使用してください。');
  return { platform: os === 'darwin' ? 'mac' : 'windows', arch };
}
function httpError(status) {
  if ([401, 403].includes(status)) return 'AccessKeyまたはModel APIの利用権限を確認してください。';
  if (status === 400) return '呼びかけ語または対象OSが受け付けられませんでした。詳細設定からConsole生成モデルを選択できます。';
  if (status === 429) return 'Picovoiceの利用上限に達しました。時間をおくか契約を確認してください。';
  return `モデル取得に失敗しました（HTTP ${status}）。通信・サービスの状態を確認してください。`;
}
async function binary(response, limit) {
  if (!response.ok) throw new Error(httpError(response.status));
  const chunks = []; let length = 0;
  for await (const chunk of response.body) {
    length += chunk.length;
    if (length > limit) throw new Error('モデルのサイズが上限を超えています。');
    chunks.push(chunk);
  }
  const data = Buffer.concat(chunks);
  if (data.length < 64 || /text|json|html/i.test(response.headers.get('content-type') || ''))
    throw new Error('モデルの応答形式が不正です。詳細設定からモデルを選択してください。');
  return data;
}
async function prepareModels({ directory, key, signal, cached, report = () => {}, fetchImpl = fetch, target = targetPlatform() }) {
  if (cached && cached.platform === target.platform && cached.arch === target.arch && cached.sdk === '4.0.2' && cached.phrase === PHRASE) {
    try {
      const model = await fs.readFile(cached.modelPath);
      const keyword = await fs.readFile(cached.keywordPath);
      if (hash(model) === MODEL_HASH && hash(keyword) === cached.keywordHash) {
        report('保存済みのモデルを検証しました。再利用します。');
        return { modelPath: cached.modelPath, keywordPath: cached.keywordPath, metadata: cached };
      }
    } catch { /* Missing or damaged cache: acquire a fresh pair. */ }
  }
  const request = async (url, options = {}) => {
    try { return await fetchImpl(url, { ...options, signal: AbortSignal.any([signal, AbortSignal.timeout(60000)]), redirect: 'manual' }); }
    catch { throw new Error(signal.aborted ? '自動設定を中止しました。' : 'モデル取得がタイムアウトしたか通信に失敗しました。ネットワークを確認してください。'); }
  };
  await fs.mkdir(directory, { recursive: true, mode: 0o700 });
  // A private staging directory keeps existing manual settings and previous models intact.
  const staging = await fs.mkdtemp(path.join(directory, 'setup-'));
  try {
    report(`${target.platform} / ${target.arch}：日本語モデルを取得中…`);
    const model = await binary(await request(MODEL_URL), 4 * 1024 * 1024);
    if (createHash('sha256').update(model).digest('hex') !== MODEL_HASH) throw new Error('日本語モデルの検証に失敗しました。再取得してください。');
    report('「Hey プティ」のモデルを生成中…');
    let response = await request(API_URL, { method: 'POST', headers: { 'Content-Type': 'application/json', 'x-api-key': key }, body: JSON.stringify({ platform: target.platform, phrase: PHRASE }) });
    if (response.status === 303) {
      let url;
      try { url = new URL(response.headers.get('location'), API_URL); } catch { throw new Error('モデル取得先が不正です。'); }
      // Never forward AccessKey to the download/CDN, or follow arbitrary redirects.
      if (url.protocol !== 'https:' || url.username || url.password || url.port ||
          !(url.hostname === 'picovoice.ai' || url.hostname.endsWith('.picovoice.ai')))
        throw new Error('モデル配布先を検証できません。詳細設定からConsole生成モデルを選択してください。');
      response = await request(url.href);
    }
    const keyword = await binary(response, 4 * 1024 * 1024);
    const modelPath = path.join(staging, 'porcupine_params_ja.pv');
    const keywordPath = path.join(staging, `hey-petit_${target.platform}_${target.arch}.ppn`);
    await fs.writeFile(modelPath, model, { mode: 0o600 });
    await fs.writeFile(keywordPath, keyword, { mode: 0o600 });
    return { modelPath, keywordPath, staging, metadata: { modelPath, keywordPath, platform: target.platform, arch: target.arch, sdk: '4.0.2', phrase: PHRASE, keywordHash: hash(keyword) } };
  } catch (error) {
    await fs.rm(staging, { recursive: true, force: true });
    if (['AbortError', 'TimeoutError'].includes(error.name))
      throw new Error(signal.aborted ? '自動設定を中止しました。' : 'モデル取得がタイムアウトしました。ネットワークを確認してください。');
    throw error;
  }
}
function testWake({ fork, options, signal, report, timeout = 30000 }) {
  return new Promise((resolve, reject) => {
    let child, timer, done = false;
    const finish = (error) => {
      if (done) return; done = true;
      clearTimeout(timer); signal.removeEventListener('abort', abort);
      child?.kill(); error ? reject(error) : resolve();
    };
    const abort = () => finish(new Error('ウェイクテストを中止しました。'));
    if (signal.aborted) return abort();
    signal.addEventListener('abort', abort, { once: true });
    timer = setTimeout(() => finish(new Error('Porcupineの初期化がタイムアウトしました。通信・AccessKey・モデルを確認してください。')), timeout);
    try {
      child = fork();
      child.on('spawn', () => { if (!done) child.postMessage({ type: 'start', ...options }); });
      child.on('message', (message) => {
        if (done) return;
        if (message.type === 'ready') {
          clearTimeout(timer);
          report('マイクを開始しました。30秒以内に「へいプティ」と話してください。');
          timer = setTimeout(() => finish(new Error('呼びかけを検出できませんでした。マイクの入力先・音量を確認して再試行してください。')), timeout);
        } else if (message.type === 'wake') finish();
        else if (message.type === 'error') finish(new Error(wakeError(message.code)));
      });
      child.on('exit', () => finish(new Error('音声プロセスが終了しました。OS/CPU対応とマイクを確認してください。')));
      child.on('error', () => finish(new Error('音声プロセスを起動できませんでした。')));
    } catch { finish(new Error('音声プロセスを起動できませんでした。')); }
  });
}
function wakeError(code) {
  return ({ key: 'AccessKeyが無効か利用上限に達しています。Picovoice Consoleを確認してください。',
    model: 'モデルを読み込めません。日本語・OS・Porcupineバージョンの組み合わせを確認してください。',
    microphone: 'マイクを開始・読み取りできません。OSのマイク権限、入力デバイス、他アプリの使用状況を確認してください。' })[code] || 'Porcupineの初期化に失敗しました。AccessKey・通信・モデルを確認してください。';
}
module.exports = { targetPlatform, prepareModels, testWake, wakeError, MODEL_URL, MODEL_HASH, API_URL };
