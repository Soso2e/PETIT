'use strict';
const fs = require('node:fs');
const fsp = require('node:fs/promises');
const path = require('node:path');
const { spawn } = require('node:child_process');

const BACKBONES = ['melspectrogram.onnx', 'embedding_model.onnx'];
const BACKBONE_BASE = 'https://github.com/dscripka/openWakeWord/releases/download/v0.5.1';

function venvPython(venv, platform = process.platform) {
  return platform === 'win32' ? path.join(venv, 'Scripts', 'python.exe') : path.join(venv, 'bin', 'python3');
}

function pythonCandidates(platform = process.platform, env = process.env) {
  const candidates = [];
  if (env.PETIT_WAKE_BOOTSTRAP_PYTHON) candidates.push({ command: env.PETIT_WAKE_BOOTSTRAP_PYTHON, prefix: [] });
  if (platform === 'win32') candidates.push({ command: 'py', prefix: ['-3'] }, { command: 'python', prefix: [] });
  else candidates.push({ command: 'python3', prefix: [] }, { command: 'python', prefix: [] });
  return candidates;
}

function run(command, args, { signal, cwd, spawnImpl = spawn, timeout = 180000, report = () => {} } = {}) {
  return new Promise((resolve, reject) => {
    let done = false;
    const child = spawnImpl(command, args, { cwd, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] });
    let output = '';
    const finish = (error) => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      signal?.removeEventListener('abort', abort);
      error ? reject(error) : resolve(output.trim());
    };
    const abort = () => { child.kill(); finish(new Error('自動設定を中止しました。')); };
    const timer = setTimeout(() => { child.kill(); finish(new Error('自動設定処理がタイムアウトしました。')); }, timeout);
    signal?.addEventListener('abort', abort, { once: true });
    child.stdout?.on('data', (chunk) => { output += chunk.toString(); });
    child.stderr?.on('data', (chunk) => { output += chunk.toString(); });
    child.on('error', () => finish(new Error(`${command} を起動できません。Python 3をインストールして再試行してください。`)));
    child.on('exit', (code) => code === 0 ? finish() : finish(new Error(output.trim() || `${command} が終了コード ${code} で失敗しました。`)));
    report();
  });
}

async function findPython({ platform = process.platform, env = process.env, signal, runImpl = run } = {}) {
  for (const candidate of pythonCandidates(platform, env)) {
    try {
      await runImpl(candidate.command, [...candidate.prefix, '--version'], { signal, timeout: 15000 });
      return candidate;
    } catch (error) {
      if (signal?.aborted) throw error;
    }
  }
  throw new Error('Python 3が見つかりません。Python 3をインストールしてから再試行してください。');
}

async function downloadFile(url, destination, { signal, fetchImpl = fetch } = {}) {
  const response = await fetchImpl(url, { redirect: 'follow', signal: AbortSignal.any([signal || new AbortController().signal, AbortSignal.timeout(120000)]) });
  if (!response.ok || !response.body) throw new Error(`必要ファイルを取得できませんでした（HTTP ${response.status}）。`);
  await fsp.mkdir(path.dirname(destination), { recursive: true, mode: 0o700 });
  const temporary = `${destination}.part`;
  const handle = await fsp.open(temporary, 'w', 0o600);
  let size = 0;
  try {
    for await (const chunk of response.body) {
      size += chunk.length;
      if (size > 20 * 1024 * 1024) throw new Error('取得ファイルのサイズが上限を超えています。');
      await handle.write(chunk);
    }
  } catch (error) {
    await handle.close().catch(() => {});
    await fsp.rm(temporary, { force: true }).catch(() => {});
    throw error;
  }
  await handle.close();
  if (size < 1024) { await fsp.rm(temporary, { force: true }); throw new Error('取得したモデルファイルが不正です。'); }
  await fsp.rename(temporary, destination);
}

function modelCandidates({ currentModelPath = '', projectRoot, resourcesPath = '', env = process.env }) {
  return [
    env.PETIT_WAKE_MODEL,
    currentModelPath,
    path.join(projectRoot, 'storage', 'wakeword', 'models', 'v0.1', 'hey_petit.onnx'),
    resourcesPath ? path.join(resourcesPath, 'wakeword', 'hey_petit.onnx') : '',
  ].filter(Boolean);
}

async function installModel(options) {
  const destination = path.join(options.root, 'models', 'hey_petit.onnx');
  for (const source of modelCandidates(options)) {
    try {
      const stat = await fsp.stat(source);
      if (stat.isFile() && path.extname(source).toLowerCase() === '.onnx') {
        await fsp.mkdir(path.dirname(destination), { recursive: true, mode: 0o700 });
        if (path.resolve(source) !== path.resolve(destination)) await fsp.copyFile(source, destination);
        return destination;
      }
    } catch { /* try the next candidate */ }
  }
  if (options.env.PETIT_WAKE_MODEL_URL) {
    await downloadFile(options.env.PETIT_WAKE_MODEL_URL, destination, options);
    return destination;
  }
  throw new Error('「Hey プティ」のONNXモデルが見つかりません。このPETIT ReleaseはWakeモデルなしでも正常に利用できます。Wake機能を使う場合はモデルを選択するか、モデル配布設定後に自動設定を再実行してください。');
}

async function prepareWakeEnvironment({
  userData,
  projectRoot = path.resolve(__dirname, '..'),
  resourcesPath = process.resourcesPath || '',
  currentModelPath = '',
  platform = process.platform,
  env = process.env,
  signal,
  report = () => {},
  runImpl = run,
  fetchImpl = fetch,
} = {}) {
  if (!userData) throw new Error('PETITのアプリデータ保存先を確認できません。');
  const root = path.join(userData, 'wakeword');
  const venv = path.join(root, '.venv');
  const python = venvPython(venv, platform);
  const runtimePath = resourcesPath && fs.existsSync(path.join(resourcesPath, 'wakeword', 'runtime.py'))
    ? path.join(resourcesPath, 'wakeword', 'runtime.py') : path.join(projectRoot, 'scripts', 'wakeword', 'runtime.py');
  const requirementsPath = resourcesPath && fs.existsSync(path.join(resourcesPath, 'wakeword', 'requirements.txt'))
    ? path.join(resourcesPath, 'wakeword', 'requirements.txt') : path.join(projectRoot, 'scripts', 'wakeword', 'requirements.txt');
  if (!fs.existsSync(runtimePath) || !fs.existsSync(requirementsPath)) throw new Error('openWakeWord runtimeの配布ファイルが不足しています。PETITを更新してください。');
  await fsp.mkdir(root, { recursive: true, mode: 0o700 });

  if (!fs.existsSync(python)) {
    report('Python 3を確認中…');
    const bootstrap = await findPython({ platform, env, signal, runImpl });
    report('openWakeWord専用venvを作成中…');
    await runImpl(bootstrap.command, [...bootstrap.prefix, '-m', 'venv', venv], { signal, timeout: 120000 });
  }

  report('openWakeWordの依存を確認・導入中…');
  await runImpl(python, ['-m', 'pip', 'install', '--disable-pip-version-check', '-r', requirementsPath], { signal, timeout: 600000 });

  const backbonePath = path.join(root, 'backbone');
  for (const name of BACKBONES) {
    const destination = path.join(backbonePath, name);
    if (!fs.existsSync(destination)) {
      report(`特徴抽出モデル ${name} を取得中…`);
      await downloadFile(`${BACKBONE_BASE}/${name}`, destination, { signal, fetchImpl });
    }
  }

  report('「Hey プティ」モデルを準備中…');
  const modelPath = await installModel({ root, currentModelPath, projectRoot, resourcesPath, env, signal, fetchImpl });

  report('マイクを開かずにopenWakeWordを診断中…');
  await runImpl(python, [runtimePath, '--diagnose', '--model', modelPath, '--backbone', backbonePath], { signal, timeout: 120000 });
  report('openWakeWord環境の準備が完了しました。');
  return { pythonPath: python, runtimePath, modelPath, backbonePath };
}

module.exports = { BACKBONES, BACKBONE_BASE, venvPython, pythonCandidates, findPython, downloadFile, modelCandidates, installModel, prepareWakeEnvironment, run };
