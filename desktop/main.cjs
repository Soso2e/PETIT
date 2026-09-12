'use strict';
const { app, BrowserWindow, Menu, Tray, nativeImage, globalShortcut, ipcMain, session,
  shell, dialog, Notification, powerMonitor, systemPreferences, utilityProcess, screen } = require('electron');
const fs = require('node:fs');
const path = require('node:path');
const { Readable } = require('node:stream');
const { pipeline } = require('node:stream/promises');
const { pathToFileURL } = require('node:url');
const { serviceUrl, isOverlay, desktopRelease, RELEASES_URL, RELEASES_API } = require('./policy.cjs');
const { transcribe } = require('./transcribe.cjs');
const { wakeError } = require('./wake-setup.cjs');
const { prepareWakeEnvironment } = require('./wake-auto-setup.cjs');
const SHORTCUT = 'CommandOrControl+Shift+Space';
const MAX_UPDATE_BYTES = 350 * 1024 * 1024;
let overlay, settingsWindow, tray, wakeProcess, config, configFile, wakeSetupController;
let quitting = false, suspended = false, wakeFailed = false, shortcutOK = false, overlayReady = false;
let pendingActivation = false, sttRequest = null, updateBusy = false, lastUpdate = '', lastWakeError = '';
let generation = 0;
let wakeReady = false, wakeTimer;
let sleeping = false, locked = false;
const settingsUrl = pathToFileURL(path.join(__dirname, 'setup.html')).href;
const defaults = { serverUrl: 'http://127.0.0.1:8000', sttUrl: '', sttModel: 'whisper-1',
  wakeEnabled: false, modelPath: '', backbonePath: '', wakePythonPath: '', wakeRuntimePath: '',
  wakeThreshold: 0.45, login: false, updates: true };
function persistConfig(next) {
  fs.writeFileSync(`${configFile}.tmp`, JSON.stringify(next, null, 2), { mode: 0o600 });
  fs.renameSync(`${configFile}.tmp`, configFile);
  config = next;
}
function cancelWakeSetup() { wakeSetupController?.abort(); }
function readConfig() {
  try {
    const raw = JSON.parse(fs.readFileSync(configFile, 'utf8'));
    const threshold = Number(raw.wakeThreshold ?? defaults.wakeThreshold);
    const modelPath = typeof raw.modelPath === 'string' && path.extname(raw.modelPath).toLowerCase() === '.onnx' ? raw.modelPath : '';
    const value = {
      ...defaults,
      serverUrl: serviceUrl(raw.serverUrl || defaults.serverUrl, { originOnly: true }),
      sttUrl: raw.sttUrl ? serviceUrl(raw.sttUrl) : '',
      sttModel: String(raw.sttModel || defaults.sttModel).slice(0, 100),
      modelPath,
      backbonePath: typeof raw.backbonePath === 'string' ? raw.backbonePath : '',
      wakePythonPath: typeof raw.wakePythonPath === 'string' ? raw.wakePythonPath : '',
      wakeRuntimePath: typeof raw.wakeRuntimePath === 'string' ? raw.wakeRuntimePath : '',
      wakeThreshold: Number.isFinite(threshold) && threshold >= 0.05 && threshold <= 0.99 ? threshold : defaults.wakeThreshold,
      wakeEnabled: raw.wakeEnabled === true && Boolean(modelPath && raw.backbonePath),
      login: raw.login === true,
      updates: raw.updates !== false,
    };
    const hadLegacyWakeConfig = ['encryptedKey', 'keywordPath', 'wakeAuto'].some((key) => Object.hasOwn(raw, key));
    if (hadLegacyWakeConfig) persistConfig(value);
    return value;
  } catch { return { ...defaults }; }
}
function stopWake() {
  generation++;
  clearTimeout(wakeTimer); wakeReady = false;
  const child = wakeProcess;
  wakeProcess = null;
  if (child) child.kill();
  refreshTray();
}
async function startWake() {
  if (!config.wakeEnabled || wakeFailed || suspended || quitting || overlay?.isVisible() || settingsWindow?.isVisible() || wakeProcess) return;
  if (!config.modelPath || !config.backbonePath || !config.sttUrl) return;
  const token = ++generation;
  if (process.platform === 'darwin' && !(await systemPreferences.askForMediaAccess('microphone'))) {
    if (token !== generation) return;
    wakeFailed = true;
    lastWakeError = wakeError('microphone');
    refreshTray();
    return;
  }
  if (token !== generation || suspended || quitting || overlay?.isVisible() || settingsWindow?.isVisible()) return;
  const child = utilityProcess.fork(path.join(__dirname, 'wake-worker.cjs'), [], { serviceName: 'PETIT Wake Word', stdio: 'ignore' });
  wakeProcess = child;
  const fail = (code) => {
    if (wakeProcess !== child) return;
    wakeFailed = true;
    lastWakeError = wakeError(code);
    stopWake();
    if (Notification.isSupported()) new Notification({ title: 'PETIT 音声待機を停止', body: lastWakeError }).show();
  };
  wakeTimer = setTimeout(() => fail('runtime'), 30000);
  child.on('message', (message) => {
    if (wakeProcess !== child) return;
    if (message.type === 'wake') showOverlay(true);
    else if (message.type === 'error') fail(message.code);
    else if (message.type === 'ready') { clearTimeout(wakeTimer); wakeReady = true; refreshTray(); }
  });
  child.on('exit', () => fail('runtime'));
  child.on('spawn', () => child.postMessage({ type: 'start', modelPath: config.modelPath, backbonePath: config.backbonePath,
    pythonPath: config.wakePythonPath || undefined, runtimePath: config.wakeRuntimePath || undefined, threshold: config.wakeThreshold }));
}
function refreshTray() {
  if (!tray || !config) return;
  const wakeLabel = !config.wakeEnabled ? '音声待機 OFF' : wakeFailed ? '音声待機 エラー（設定を確認）' :
    wakeProcess ? (wakeReady ? '音声待機 ON' : '音声待機 準備中') : '音声待機 一時停止';
  tray.setToolTip(`PETIT · ${wakeLabel}`);
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: 'PETITを呼び出す', click: () => showOverlay(true) },
    { label: wakeLabel, enabled: false },
    { label: shortcutOK ? '呼び出し: Ctrl / ⌘ + Shift + Space' : 'ショートカット登録失敗・トレイで呼び出せます', enabled: false },
    { type: 'separator' },
    { label: 'Web版を開く', click: () => void shell.openExternal(config.serverUrl) },
    { label: '設定', click: () => showSettings() },
    { label: 'アップデートを確認', click: () => void checkUpdates(true) },
    { type: 'separator' },
    { label: 'PETITを終了', click: () => app.quit() },
  ]));
}
function lockNavigation(win, allowed) {
  win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  win.webContents.on('will-navigate', (event, url) => { if (!allowed(url)) event.preventDefault(); });
  win.webContents.on('will-redirect', (event, url) => { if (!allowed(url)) event.preventDefault(); });
  win.webContents.on('will-attach-webview', (event) => event.preventDefault());
}
function showSettings() {
  stopWake();
  hideOverlay(false);
  if (settingsWindow && !settingsWindow.isDestroyed()) { settingsWindow.show(); settingsWindow.focus(); return; }
  settingsWindow = new BrowserWindow({ width: 620, height: 780, title: 'PETIT 設定', backgroundColor: '#0b1020',
    webPreferences: { preload: path.join(__dirname, 'setup-preload.cjs'), sandbox: true, contextIsolation: true, nodeIntegration: false } });
  lockNavigation(settingsWindow, (url) => url === settingsUrl);
  settingsWindow.on('closed', () => { cancelWakeSetup(); settingsWindow = null; void startWake(); });
  void settingsWindow.loadURL(settingsUrl);
}
function showOverlay(voice = false) {
  if (suspended || quitting) return;
  stopWake();
  pendingActivation ||= voice;
  if (!overlay || overlay.isDestroyed()) {
    overlayReady = false;
    overlay = new BrowserWindow({ width: 430, height: 520, minWidth: 340, minHeight: 400,
      show: false, frame: false, alwaysOnTop: true, resizable: true, backgroundColor: '#0a1020',
      title: 'PETIT', skipTaskbar: false,
      webPreferences: { preload: path.join(__dirname, 'preload.cjs'), sandbox: true, contextIsolation: true,
        nodeIntegration: false, spellcheck: false, backgroundThrottling: true } });
    lockNavigation(overlay, (url) => isOverlay(url, config.serverUrl));
    overlay.on('close', (event) => { if (!quitting) { event.preventDefault(); hideOverlay(); } });
    const win = overlay;
    let readyTimer;
    const connectionFailed = () => {
      if (quitting || overlay !== win || win.isDestroyed()) return;
      clearTimeout(readyTimer); cancelStt();
      win.destroy(); overlay = null; pendingActivation = false;
      showSettings();
      void dialog.showMessageBox(settingsWindow, { type: 'warning', message: 'PETITサーバーへ接続できません',
        detail: 'サーバーを起動し、接続URLを確認してください。小型画面を含むv0.20.0以降のPETITサーバーが必要です。' });
    };
    win.webContents.on('render-process-gone', connectionFailed);
    win.webContents.on('did-finish-load', () => {
      readyTimer = setTimeout(() => { if (!overlayReady) connectionFailed(); }, 8000);
    });
    win.on('closed', () => clearTimeout(readyTimer));
    win.loadURL(`${config.serverUrl}/static/desktop/index.html`).catch(connectionFailed);
  }
  const { workArea } = screen.getDisplayNearestPoint(screen.getCursorScreenPoint());
  const [width, height] = overlay.getSize();
  overlay.setPosition(Math.round(workArea.x + (workArea.width - width) / 2), Math.max(workArea.y, Math.round(workArea.y + workArea.height - height - 32)));
  overlay.show(); overlay.focus();
  if (overlayReady) {
    overlay.webContents.send('desktop:activate', { voice: pendingActivation });
    pendingActivation = false;
  }
}
function cancelStt() { sttRequest?.abort(); sttRequest = null; }
function hideOverlay(resume = true) {
  cancelStt(); pendingActivation = false;
  if (overlay && !overlay.isDestroyed()) { overlay.webContents.send('desktop:hidden'); overlay.hide(); }
  if (resume) void startWake();
}
function assertSender(event, kind) {
  const win = kind === 'settings' ? settingsWindow : overlay;
  if (!win || event.sender !== win.webContents || event.senderFrame !== event.sender.mainFrame ||
      !(kind === 'settings' ? event.senderFrame.url === settingsUrl : isOverlay(event.senderFrame.url, config.serverUrl)))
    throw new Error('許可されていない呼び出しです。');
}
function installerAsset(release) {
  const version = release.tag_name.replace(/^v/, '');
  const suffix = process.platform === 'darwin' ? `mac-${process.arch}.dmg` : `win-${process.arch}.exe`;
  const name = `PETIT-${version}-${suffix}`;
  const asset = release.assets?.find((item) => item.name === name);
  if (!asset) return null;
  const expectedPrefix = `https://github.com/Soso2e/PETIT/releases/download/${encodeURIComponent(release.tag_name)}/`;
  if (!asset.browser_download_url?.startsWith(expectedPrefix) || asset.browser_download_url !== `${expectedPrefix}${encodeURIComponent(name)}`) return null;
  return asset;
}
async function downloadAndInstallWindows(release) {
  if (process.platform !== 'win32' || process.arch !== 'x64' || !app.isPackaged) throw new Error('この環境ではアプリ内更新を利用できません。');
  const asset = installerAsset(release);
  if (!asset) throw new Error('更新用installerを確認できませんでした。');
  const destination = path.join(app.getPath('temp'), asset.name);
  await fs.promises.rm(destination, { force: true }).catch(() => {});
  const response = await fetch(asset.browser_download_url, { redirect: 'follow', signal: AbortSignal.timeout(120000) });
  if (!response.ok || !response.body) throw new Error('更新のダウンロードに失敗しました。');
  const size = Number(response.headers.get('content-length') || 0);
  if (size && size > MAX_UPDATE_BYTES) throw new Error('更新ファイルのサイズが上限を超えています。');
  let received = 0;
  const limiter = new TransformStream({ transform(chunk, controller) {
    received += chunk.byteLength;
    if (received > MAX_UPDATE_BYTES) throw new Error('更新ファイルのサイズが上限を超えています。');
    controller.enqueue(chunk);
  } });
  await pipeline(Readable.fromWeb(response.body.pipeThrough(limiter)), fs.createWriteStream(destination, { flags: 'wx' }));
  const result = await shell.openPath(destination);
  if (result) throw new Error(`installerを起動できませんでした: ${result}`);
  quitting = true;
  app.quit();
}
async function checkUpdates(manual = false) {
  if (updateBusy) return '更新確認中です。';
  updateBusy = true;
  let message = '利用可能なDesktop更新はありません。';
  try {
    const response = await fetch(RELEASES_API, { headers: { Accept: 'application/vnd.github+json' }, redirect: 'error', signal: AbortSignal.timeout(10000) });
    if (!response.ok) throw new Error('release');
    const release = desktopRelease(await response.json(), app.getVersion(), process.platform, process.arch);
    if (release) {
      const canInstall = process.platform === 'win32' && process.arch === 'x64' && app.isPackaged && installerAsset(release);
      message = canInstall ? `${release.tag_name}を利用できます。PETITから更新できます。` :
        `${release.tag_name}を利用できます。GitHub Releasesからインストールしてください。`;
      if (manual) {
        const buttons = canInstall ? ['ダウンロードして更新', 'Releasesを開く', '後で'] : ['Releasesを開く', '後で'];
        const answer = await dialog.showMessageBox({ type: 'info', message, buttons, defaultId: buttons.length - 1, cancelId: buttons.length - 1 });
        if (canInstall && answer.response === 0) {
          await dialog.showMessageBox({ type: 'info', message: '更新をダウンロードします', detail: '完了後にinstallerを起動し、PETITを終了します。' });
          await downloadAndInstallWindows(release);
        } else if (answer.response === (canInstall ? 1 : 0)) await shell.openExternal(release.html_url);
      } else if (lastUpdate !== release.tag_name && Notification.isSupported()) {
        const notification = new Notification({ title: 'PETIT アップデート', body: message });
        notification.on('click', () => void checkUpdates(true));
        notification.show(); lastUpdate = release.tag_name;
      }
    }
  } catch (error) { message = `更新を確認できませんでした。${error?.message ? ` ${error.message}` : 'ネットワークを確認してください。'}`; }
  finally { updateBusy = false; }
  if (manual && !message.includes('利用できます')) await dialog.showMessageBox({ message });
  return message;
}
function installIpc() {
  const on = (channel, kind, handler) => ipcMain.handle(channel, (event, ...args) => { assertSender(event, kind); return handler(...args); });
  on('desktop:hide', 'overlay', () => hideOverlay());
  on('desktop:open-web', 'overlay', () => shell.openExternal(config.serverUrl));
  on('desktop:settings', 'overlay', () => showSettings());
  on('desktop:cancel', 'overlay', () => cancelStt());
  on('desktop:ready', 'overlay', () => {
    overlayReady = true;
    const voice = pendingActivation; pendingActivation = false;
    return { voice, sttConfigured: Boolean(config.sttUrl), version: app.getVersion() };
  });
  on('desktop:transcribe', 'overlay', async (wav) => {
    if (suspended || !overlay.isVisible() || sttRequest) throw new Error('いまは音声入力を開始できません。');
    const controller = new AbortController(); sttRequest = controller;
    try { return await transcribe(wav, config, controller.signal); }
    finally { if (sttRequest === controller) sttRequest = null; }
  });
  on('settings:read', 'settings', () => ({ ...config, version: app.getVersion(), shortcutOK, lastWakeError, platform: process.platform, arch: process.arch }));
  on('settings:model', 'settings', async (kind) => {
    if (!['onnx', 'dir'].includes(kind)) throw new Error('モデル形式が不正です。');
    const result = await dialog.showOpenDialog(settingsWindow, { properties: [kind === 'dir' ? 'openDirectory' : 'openFile'], filters: kind === 'onnx' ? [{ name: 'ONNX wake model', extensions: ['onnx'] }] : undefined });
    return result.canceled ? '' : result.filePaths[0];
  });
  on('settings:wake-cancel', 'settings', () => { cancelWakeSetup(); return true; });
  on('settings:wake-setup', 'settings', async () => {
    if (wakeSetupController) return { ok: false, message: 'openWakeWordの自動設定はすでに実行中です。' };
    if (suspended || quitting) return { ok: false, message: 'ロック・スリープ解除後に再試行してください。' };
    const controller = new AbortController(); wakeSetupController = controller;
    const owner = settingsWindow;
    const report = (message) => { if (message && owner && !owner.isDestroyed()) owner.webContents.send('settings:wake-progress', message); };
    try {
      stopWake();
      const prepared = await prepareWakeEnvironment({
        userData: app.getPath('userData'), projectRoot: path.resolve(__dirname, '..'), resourcesPath: process.resourcesPath || '',
        currentModelPath: config.modelPath, signal: controller.signal, report,
      });
      controller.signal.throwIfAborted();
      persistConfig({ ...config, modelPath: prepared.modelPath, backbonePath: prepared.backbonePath,
        wakePythonPath: prepared.pythonPath, wakeRuntimePath: prepared.runtimePath });
      wakeFailed = false; lastWakeError = '';
      return { ok: true, modelPath: config.modelPath, backbonePath: config.backbonePath,
        message: 'openWakeWordの準備とdiagnosticが完了しました。STT URLを設定し、音声待機をONにして保存してください。' };
    } catch (error) {
      const message = controller.signal.aborted ? 'openWakeWordの自動設定を中止しました。' : error.message;
      lastWakeError = message;
      return { ok: false, message };
    } finally { wakeSetupController = null; }
  });
  on('settings:updates', 'settings', () => checkUpdates(true));
  on('settings:save', 'settings', (values) => {
    if (wakeSetupController) throw new Error('openWakeWordの自動設定が完了するか、中止してから保存してください。');
    const threshold = Number(values.wakeThreshold || defaults.wakeThreshold);
    if (!Number.isFinite(threshold) || threshold < 0.05 || threshold > 0.99) throw new Error('検出しきい値は0.05〜0.99で指定してください。');
    const next = { ...defaults, serverUrl: serviceUrl(values.serverUrl, { originOnly: true }),
      sttUrl: values.sttUrl ? serviceUrl(values.sttUrl) : '', sttModel: String(values.sttModel || 'whisper-1').slice(0, 100),
      modelPath: String(values.modelPath || ''), backbonePath: String(values.backbonePath || ''),
      wakePythonPath: config.wakePythonPath || '', wakeRuntimePath: config.wakeRuntimePath || '',
      wakeEnabled: values.wakeEnabled === true, login: values.login === true, updates: values.updates === true,
      wakeThreshold: threshold };
    if (next.modelPath && (!path.isAbsolute(next.modelPath) || path.extname(next.modelPath).toLowerCase() !== '.onnx' || !fs.statSync(next.modelPath).isFile())) throw new Error('ONNXモデルを選択してください。');
    if (next.backbonePath && (!path.isAbsolute(next.backbonePath) || !fs.statSync(next.backbonePath).isDirectory())) throw new Error('特徴抽出モデルのフォルダを選択してください。');
    if (next.wakeEnabled && (!next.modelPath || !next.backbonePath || !next.sttUrl)) throw new Error('音声待機にはSTT URL・ONNXモデル・backboneフォルダが必要です。');
    if (next.login && !app.isPackaged) throw new Error('ログイン時の起動はインストール版で設定してください。');
    persistConfig(next);
    stopWake(); cancelStt(); wakeFailed = false; lastWakeError = '';
    if (app.isPackaged) app.setLoginItemSettings({ openAtLogin: config.login, args: ['--background'] });
    if (overlay && !overlay.isDestroyed()) overlay.destroy(); overlay = null;
    settingsWindow.close(); showOverlay(false); refreshTray();
    return true;
  });
}
if (!app.requestSingleInstanceLock()) app.quit();
else {
  app.on('second-instance', () => showOverlay());
  app.on('activate', () => { if (config) showOverlay(); });
  app.on('window-all-closed', () => {});
  app.on('before-quit', () => { quitting = true; cancelWakeSetup(); stopWake(); cancelStt(); globalShortcut.unregisterAll(); });
  app.whenReady().then(() => {
    configFile = path.join(app.getPath('userData'), 'desktop.json'); config = readConfig();
    session.defaultSession.setPermissionRequestHandler((contents, permission, callback, details) => {
      callback(Boolean(contents === overlay?.webContents && overlay.isVisible() && isOverlay(contents.getURL(), config.serverUrl) &&
        details.isMainFrame && permission === 'media' && details.mediaTypes?.length === 1 && details.mediaTypes[0] === 'audio'));
    });
    session.defaultSession.setPermissionCheckHandler((contents, permission, _origin, details) =>
      Boolean(contents === overlay?.webContents && overlay.isVisible() && isOverlay(contents.getURL(), config.serverUrl) &&
        details.isMainFrame && permission === 'media' && details.mediaType === 'audio'));
    const iconPath = app.isPackaged ? path.join(process.resourcesPath, 'icon.png') : path.join(__dirname, '../frontend/icon-512.png');
    const icon = nativeImage.createFromPath(iconPath).resize({ width: 18, height: 18 });
    tray = new Tray(icon); tray.on('click', () => showOverlay(true));
    shortcutOK = globalShortcut.register(SHORTCUT, () => showOverlay(true));
    installIpc(); refreshTray();
    const syncPower = () => {
      suspended = sleeping || locked;
      if (suspended) { cancelWakeSetup(); stopWake(); hideOverlay(false); } else void startWake();
    };
    powerMonitor.on('suspend', () => { sleeping = true; syncPower(); });
    powerMonitor.on('lock-screen', () => { locked = true; syncPower(); });
    powerMonitor.on('resume', () => { sleeping = false; syncPower(); });
    powerMonitor.on('unlock-screen', () => { locked = false; syncPower(); });
    if (!fs.existsSync(configFile)) showSettings();
    else if (process.argv.includes('--background')) void startWake();
    else showOverlay();
    setTimeout(() => { if (config.updates) void checkUpdates(); }, 10000).unref();
    setInterval(() => { if (config.updates) void checkUpdates(); }, 24 * 60 * 60 * 1000).unref();
  });
}
