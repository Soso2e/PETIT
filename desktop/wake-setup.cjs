'use strict';

function testWake({ fork, options, signal, report = () => {}, timeout = 30000 }) {
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
    timer = setTimeout(() => finish(new Error('openWakeWordの初期化がタイムアウトしました。Python環境・ONNXモデル・特徴抽出モデルを確認してください。')), timeout);
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
      child.on('exit', () => finish(new Error('openWakeWord音声プロセスが終了しました。Python環境・モデル・マイクを確認してください。')));
      child.on('error', () => finish(new Error('openWakeWord音声プロセスを起動できませんでした。')));
    } catch { finish(new Error('openWakeWord音声プロセスを起動できませんでした。')); }
  });
}

function wakeError(code) {
  return ({
    runtime: 'openWakeWordランタイムを起動できません。Python環境と依存パッケージを確認してください。',
    model: 'ウェイクONNXモデルを読み込めません。モデルファイルを確認してください。',
    backbone: '特徴抽出モデルを読み込めません。melspectrogram.onnx と embedding_model.onnx を確認してください。',
    microphone: 'マイクを開始・読み取りできません。OSのマイク権限、入力デバイス、他アプリの使用状況を確認してください。',
  })[code] || 'openWakeWordの初期化に失敗しました。Python環境・モデル・マイク設定を確認してください。';
}

module.exports = { testWake, wakeError };
