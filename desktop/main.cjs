'use strict';
const { app, BrowserWindow, Menu, Tray, nativeImage, globalShortcut, ipcMain, session,
  shell, dialog, Notification, powerMonitor, systemPreferences, safeStorage, utilityProcess, screen } = require('electron');
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { serviceUrl, isOverlay, desktopRelease, RELEASES_URL, RELEASES_API } = require('./policy.cjs');
const { transcribe } = require('./transcribe.cjs');
const SHORTCUT = 'CommandOrControl+Shift+Space';
let overlay, settingsWindow, tray, wakeProcess, config, configFile;
let quitting = false, suspended = false, wakeFailed = false, shortcutOK = false, overlayReady = false;
let pendingActivation = false, sttRequest = null, updateBusy = false, lastUpdate = '';
let generation = 0;
let wakeReady = false, wakeTimer;
let sleeping = false, locked = false;
const settingsUrl = pathToFileURL(path.join(__dirname, 'setup.html')).href;
const defaults = { serverUrl: 'http://127.0.0.1:8000', sttUrl: '', sttModel: 'whisper-1',
  wakeEnabled: false, keywordPath: '', modelPath: '', encryptedKey: '', login: false, updates: true };
function readConfig() {
  try {
    const value = { ...defaults, ...JSON.parse(fs.readFileSync(configFile, 'utf8')) };
    value.serverUrl = serviceUrl(value.serverUrl, { originOnly: true });
    if (value.sttUrl) value.sttUrl = serviceUrl(value.sttUrl);
    return value;
  } catch { return { ...defaults }; }
}
function wakeKey() {
  if (process.env.PETIT_PORCUPINE_ACCESS_KEY) return process.env.PETIT_PORCUPINE_ACCESS_KEY;
  try { return config.encryptedKey ? safeStorage.decryptString(Buffer.from(config.encryptedKey, 'base64')) : ''; }
  catch { return ''; }
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
  if (!config.keywordPath || !config.modelPath || !config.sttUrl || !wakeKey()) return;
  const token = ++generation;
  if (process.platform === 'darwin' && !(await systemPreferences.askForMediaAccess('microphone'))) {
    if (token !== generation) return;
    wakeFailed = true;
    refreshTray();
    return;
  }
  if (token !== generation || suspended || quitting || overlay?.isVisible() || settingsWindow?.isVisible()) return;
  const child = utilityProcess.fork(path.join(__dirname, 'wake-worker.cjs'), [], { serviceName: 'PETIT Wake Word', stdio: 'ignore' });
  wakeProcess = child;
  const fail = () => {
    if (wakeProcess !== child) return;
    wakeFailed = true;
    stopWake();
    if (Notification.isSupported()) new Notification({ title: 'PETIT 音声待機を停止', body: 'マイク権限・AccessKey・OS別の日本語モデルを設定で確認してください。トレイから呼び出せます。' }).show();
  };
  wakeTimer = setTimeout(fail, 30000);
  child.on('message', (message) => {
    if (wakeProcess !== child) return;
    if (message.type === 'wake') showOverlay(true);
    else if (message.type === 'error') fail();
    else if (message.type === 'ready') { clearTimeout(wakeTimer); wakeReady = true; refreshTray(); }
  });
  child.on('exit', fail);
  child.on('spawn', () => child.postMessage({ type: 'start', key: wakeKey(), keywordPath: config.keywordPath, modelPath: config.modelPath }));
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
  settingsWindow.on('closed', () => { settingsWindow = null; void startWake(); });
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
async function checkUpdates(manual = false) {
  if (updateBusy) return '更新確認中です。';
  updateBusy = true;
  let message = '利用可能なDesktop更新はありません。';
  try {
    const response = await fetch(RELEASES_API, { headers: { Accept: 'application/vnd.github+json' }, redirect: 'error', signal: AbortSignal.timeout(10000) });
    if (!response.ok) throw new Error('release');
    const release = desktopRelease(await response.json(), app.getVersion(), process.platform, process.arch);
    if (release) {
      message = `${release.tag_name}を利用できます。GitHub Releasesからインストールしてください。`;
      if (manual) {
        const answer = await dialog.showMessageBox({ type: 'info', message, buttons: ['Releasesを開く', '後で'], defaultId: 1, cancelId: 1 });
        if (answer.response === 0) await shell.openExternal(release.html_url);
      } else if (lastUpdate !== release.tag_name && Notification.isSupported()) {
        const notification = new Notification({ title: 'PETIT アップデート', body: message });
        notification.on('click', () => void shell.openExternal(release.html_url));
        notification.show(); lastUpdate = release.tag_name;
      }
    }
  } catch { message = '更新を確認できませんでした。ネットワークを確認してください。'; }
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
  on('settings:read', 'settings', () => ({ ...config, encryptedKey: undefined, hasKey: Boolean(wakeKey()), version: app.getVersion(), shortcutOK }));
  on('settings:model', 'settings', async (kind) => {
    if (!['ppn', 'pv'].includes(kind)) throw new Error('モデル形式が不正です。');
    const result = await dialog.showOpenDialog(settingsWindow, { properties: ['openFile'], filters: [{ name: 'Porcupine model', extensions: [kind] }] });
    return result.canceled ? '' : result.filePaths[0];
  });
  on('settings:updates', 'settings', () => checkUpdates(true));
  on('settings:save', 'settings', (values) => {
    const next = { ...defaults, serverUrl: serviceUrl(values.serverUrl, { originOnly: true }),
      sttUrl: values.sttUrl ? serviceUrl(values.sttUrl) : '', sttModel: String(values.sttModel || 'whisper-1').slice(0, 100),
      keywordPath: String(values.keywordPath || ''), modelPath: String(values.modelPath || ''),
      wakeEnabled: values.wakeEnabled === true, login: values.login === true, updates: values.updates === true,
      encryptedKey: config.encryptedKey };
    if (values.clearKey) next.encryptedKey = '';
    if (values.key) {
      if (typeof values.key !== 'string' || values.key.length > 1024 || !safeStorage.isEncryptionAvailable()) throw new Error('AccessKeyを安全に保存できません。OSのキーストアを確認してください。');
      next.encryptedKey = safeStorage.encryptString(values.key).toString('base64');
    }
    for (const [key, extension] of [['keywordPath', '.ppn'], ['modelPath', '.pv']]) {
      if (next[key] && (!path.isAbsolute(next[key]) || path.extname(next[key]) !== extension || !fs.statSync(next[key]).isFile())) throw new Error('モデルファイルを選択してください。');
    }
    if (next.wakeEnabled && (!next.keywordPath || !next.modelPath || !next.sttUrl || !(next.encryptedKey || process.env.PETIT_PORCUPINE_ACCESS_KEY)))
      throw new Error('音声待機にはSTT URL・AccessKey・日本語モデル(.pv)・OS別ウェイクモデル(.ppn)が必要です。');
    if (next.login && !app.isPackaged) throw new Error('ログイン時の起動はインストール版で設定してください。');
    fs.writeFileSync(`${configFile}.tmp`, JSON.stringify(next, null, 2), { mode: 0o600 });
    fs.renameSync(`${configFile}.tmp`, configFile);
    stopWake(); cancelStt(); config = next; wakeFailed = false;
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
  app.on('before-quit', () => { quitting = true; stopWake(); cancelStt(); globalShortcut.unregisterAll(); });
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
      if (suspended) { stopWake(); hideOverlay(false); } else void startWake();
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
