'use strict';
const { app, BrowserWindow, Menu, Tray, nativeImage, globalShortcut, ipcMain, session,
  shell, dialog, Notification, powerMonitor, systemPreferences, utilityProcess, screen } = require('electron');
const fs = require('node:fs');
const path = require('node:path');
const { installerAsset, downloadVerified } = require('./update-download.cjs');
const { pathToFileURL } = require('node:url');
const { serviceUrl, isOverlay, isWorkspace, isCoreSetup, desktopRelease, RELEASES_URL, RELEASES_API } = require('./policy.cjs');
const { windowState } = require('./window-state.cjs');
const { nativeNotifications, deliveryMessage } = require('./native-notifications.cjs');
const nativeDelivery = nativeNotifications({ Notification, open: () => showWorkspace() });
const { notificationFeed } = require('./notification-feed.cjs');
const { transcribe } = require('./transcribe.cjs');
const { wakeError } = require('./wake-setup.cjs');
const { prepareWakeEnvironment } = require('./wake-auto-setup.cjs');
const SHORTCUT = 'CommandOrControl+Shift+Space';
let overlay, settingsWindow, tray, wakeProcess, config, configFile, wakeSetupController;
ipcMain.handle('core-setup:open-web', (event) => {
  const owner = [overlay, workspace].find(win => win && !win.isDestroyed() && win.webContents === event.sender);
  if (!owner || event.senderFrame !== event.sender.mainFrame || !isCoreSetup(event.senderFrame.url, config.serverUrl)) throw new Error('Invalid setup sender');
  return shell.openExternal(`${config.serverUrl}/static/setup.html`);
});
let quitting = false, suspended = false, wakeFailed = false, shortcutOK = false, overlayReady = false;
let pendingActivation = false, sttRequest = null, updateBusy = false, lastUpdate = '', lastWakeError = '';
let generation = 0;
let wakeReady = false, wakeTimer;
let sleeping = false, locked = false;
let workspace, recoveryWindow, recoveryState, geometry;
let nudgeWindow, nudgeEvent, nudgeTimer, feed, cursorFile, cursors = {}, notificationError = '';
const nudgeUrl = pathToFileURL(path.join(__dirname, 'nudge.html')).href;
const settingsUrl = pathToFileURL(path.join(__dirname, 'setup.html')).href;
const recoveryUrl = pathToFileURL(path.join(__dirname, 'recovery.html')).href;
const defaults = { serverUrl: 'http://127.0.0.1:8000', sttUrl: '', sttModel: 'whisper-1',
  wakeEnabled: false, modelPath: '', backbonePath: '', wakePythonPath: '',
  wakeThreshold: 0.45, login: false, updates: true, notifications: false, notificationMode: 'gentle', notificationSound: false };
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
      wakeThreshold: Number.isFinite(threshold) && threshold >= 0.05 && threshold <= 0.99 ? threshold : defaults.wakeThreshold,
      wakeEnabled: raw.wakeEnabled === true && Boolean(modelPath && raw.backbonePath),
      login: raw.login === true,
      updates: raw.updates !== false,
      notifications: raw.notifications === true,
      notificationMode: raw.notificationMode === 'native' ? 'native' : 'gentle',
      notificationSound: raw.notificationSound === true,
    };
    const hadLegacyWakeConfig = ['encryptedKey', 'keywordPath', 'wakeAuto', 'wakeRuntimePath'].some((key) => Object.hasOwn(raw, key));
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
  if (!config.wakeEnabled || wakeFailed || suspended || quitting || overlay?.isVisible() || settingsWindow?.isVisible() || recoveryWindow?.isVisible() || wakeProcess) return;
  if (!config.modelPath || !config.backbonePath || !config.sttUrl) return;
  const token = ++generation;
  if (process.platform === 'darwin' && !(await systemPreferences.askForMediaAccess('microphone'))) {
    if (token !== generation) return;
    wakeFailed = true;
    lastWakeError = wakeError('microphone');
    refreshTray();
    return;
  }
  if (token !== generation || suspended || quitting || overlay?.isVisible() || settingsWindow?.isVisible() || recoveryWindow?.isVisible()) return;
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
    pythonPath: config.wakePythonPath || undefined, threshold: config.wakeThreshold }));
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
    { label: 'ワークスペースを開く', click: () => showWorkspace() },
    { label: 'Web版を開く', click: () => void shell.openExternal(config.serverUrl) },
    { label: '設定', click: () => showSettings() },
    { label: 'アップデートを確認', click: () => void checkUpdates(true) },
    { type: 'separator' },
    { label: 'PETITを終了', click: () => app.quit() },
  ]));
}
function closeNudge() {
  clearTimeout(nudgeTimer);
  if (nudgeWindow && !nudgeWindow.isDestroyed()) nudgeWindow.destroy();
  nudgeWindow = null; nudgeEvent = null;
}
function dismissNudgeLater() {
  clearTimeout(nudgeTimer); nudgeTimer = setTimeout(closeNudge, 12000); nudgeTimer.unref();
}
function showNudge(event) {
  closeNudge();
  nudgeEvent = { title: String(event.title || 'PETIT').slice(0, 120), body: String(event.body || '').slice(0, 500) };
  const area = screen.getPrimaryDisplay().workArea;
  const width = Math.min(380, area.width), height = Math.min(250, area.height);
  const win = nudgeWindow = new BrowserWindow({ width, height, x: area.x + area.width - width - 16,
    y: area.y + area.height - height - 16, frame: false, transparent: true, resizable: false,
    alwaysOnTop: true, skipTaskbar: true, show: false,
    webPreferences: { preload: path.join(__dirname, 'nudge-preload.cjs'), sandbox: true, contextIsolation: true, nodeIntegration: false } });
  lockNavigation(win, (url) => url === nudgeUrl);
  win.once('ready-to-show', () => { if (!win.isDestroyed()) { win.showInactive(); dismissNudgeLater(); } });
  void win.loadURL(nudgeUrl);
}
function deliverDesktopNotification(event) {
  if (suspended || quitting) return;
  if (config.notificationMode === 'gentle') { showNudge(event); return; }
  return nativeDelivery.deliver(event, config.notificationSound);
}
function desktopNotificationStatus() {
  const supported = Notification.isSupported();
  return { enabled: config.notifications, mode: config.notificationMode, sound: config.notificationSound, supported,
    permission: 'unknown', delivery: nativeDelivery.read().delivery,
    error: notificationError || nativeDelivery.read().error || (config.notificationMode === 'native' && !supported ? 'OS通知を利用できません。Desktop設定で「画面のすみに声かけ」を選んでください。' : '') };
}
async function pollNotifications() {
  if (!feed || suspended || quitting) return;
  const origin = config.serverUrl;
  try {
    await feed.poll(origin, config.notifications, () => config.notifications && config.serverUrl === origin && !suspended && !quitting);
    if (notificationError.startsWith('通知の取得に失敗')) notificationError = '';
  } catch { notificationError = nativeDelivery.read().error || (!Notification.isSupported() && config.notificationMode === 'native' ? 'OS通知を利用できません。画面の声かけを選んでください。' : '通知の取得に失敗しました。PETITサーバーの接続を確認してください。'); }
}
function setDesktopNotifications(enabled) {
  if (typeof enabled !== 'boolean') throw new Error('通知設定が不正です。');
  if (enabled && !config.notifications) delete cursors[config.serverUrl];
  persistConfig({ ...config, notifications: enabled }); notificationError = ''; nativeDelivery.reset();
  if (!enabled) closeNudge(); else void pollNotifications();
  return desktopNotificationStatus();
}
function lockNavigation(win, allowed) {
  win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  win.webContents.on('will-navigate', (event, url) => { if (!allowed(url)) event.preventDefault(); });
  win.webContents.on('will-redirect', (event, url) => { if (!allowed(url)) event.preventDefault(); });
  win.webContents.on('will-attach-webview', (event) => event.preventDefault());
}
function clientBounds(kind, width, height) {
  const primary = screen.getDisplayNearestPoint(screen.getCursorScreenPoint());
  const areas = [primary, ...screen.getAllDisplays().filter((display) => display.id !== primary.id)].map((display) => display.workArea);
  return geometry.get(kind, { width, height }, areas);
}
function rememberWindow(win, kind) {
  let timer;
  const save = () => { if (!win.isDestroyed() && !win.isMinimized() && !win.isMaximized()) geometry.remember(kind, win.getBounds()); };
  const schedule = () => { clearTimeout(timer); timer = setTimeout(save, 300); };
  win.on('move', schedule); win.on('resize', schedule);
  win.on('close', save); win.on('closed', () => clearTimeout(timer));
}
function showRecovery(target, reason) {
  if (quitting) return;
  stopWake(); cancelStt();
  recoveryState = { target, reason, serverUrl: config.serverUrl };
  if (recoveryWindow && !recoveryWindow.isDestroyed()) recoveryWindow.destroy();
  const win = recoveryWindow = new BrowserWindow({ width: 580, height: 440, title: 'PETIT 接続と復旧',
    backgroundColor: '#101218', webPreferences: { preload: path.join(__dirname, 'recovery-preload.cjs'),
      sandbox: true, contextIsolation: true, nodeIntegration: false } });
  lockNavigation(win, (url) => url === recoveryUrl);
  win.on('closed', () => { if (recoveryWindow === win) recoveryWindow = null; void startWake(); });
  void win.loadURL(recoveryUrl);
}
function watchClient(win, kind) {
  let readyTimer;
  const failed = (reason = 'connection') => {
    if (quitting || win.isDestroyed() || (kind === 'overlay' ? overlay : workspace) !== win) return;
    if (kind === 'overlay') { overlay = null; overlayReady = false; pendingActivation = false; }
    else workspace = null;
    clearTimeout(readyTimer); win.destroy(); showRecovery(kind, reason);
  };
  win.webContents.on('render-process-gone', () => failed('renderer'));
  win.webContents.on('did-fail-load', (_event, code, _description, _url, mainFrame) => {
    if (mainFrame && code !== -3) failed();
  });
  // Tab changes use replaceState and do not rerun the preload's ready handshake.
  // Only a new main-frame document invalidates renderer readiness.
  win.webContents.on('did-start-navigation', (details) => {
    if (details.isMainFrame && !details.isSameDocument) {
      clearTimeout(readyTimer); win.petitReady = false;
    }
  });
  win.webContents.on('did-finish-load', () => {
    if (win.webContents.getURL && isCoreSetup(win.webContents.getURL(), config.serverUrl)) { win.petitReady = true; clearTimeout(readyTimer); return; }
    clearTimeout(readyTimer); readyTimer = setTimeout(() => { if (!win.petitReady) failed(); }, 8000);
  });
  win.on('closed', () => clearTimeout(readyTimer));
  return failed;
}
function showWorkspace() {
  if (suspended || quitting) return;
  hideOverlay();
  if (!workspace || workspace.isDestroyed()) {
    const win = workspace = new BrowserWindow({ ...clientBounds('workspace', 1180, 800), minWidth: 700, minHeight: 480,
      title: 'PETIT ワークスペース', backgroundColor: '#101218',
      webPreferences: { preload: path.join(__dirname, 'workspace-preload.cjs'), sandbox: true,
        contextIsolation: true, nodeIntegration: false } });
    rememberWindow(win, 'workspace');
    lockNavigation(win, (url) => isWorkspace(url, config.serverUrl) || isCoreSetup(url, config.serverUrl));
    win.on('close', (event) => { if (!quitting) { event.preventDefault(); win.hide(); } });
    win.on('closed', () => { if (workspace === win) workspace = null; });
    win.webContents.on('did-finish-load', () => {
      void win.webContents.insertCSS(fs.readFileSync(path.join(__dirname, 'workspace.css'), 'utf8'));
    });
    const failed = watchClient(win, 'workspace');
    win.loadURL(`${config.serverUrl}/static/universe.html`).catch(() => failed());
  }
  if (workspace.isMinimized()) workspace.restore();
  workspace.show(); workspace.focus();
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
    overlay = new BrowserWindow({ ...clientBounds('overlay', 430, 520), minWidth: 340, minHeight: 400,
      show: false, frame: false, alwaysOnTop: true, resizable: true, backgroundColor: '#0a1020',
      title: 'PETIT', skipTaskbar: false,
      webPreferences: { preload: path.join(__dirname, 'preload.cjs'), sandbox: true, contextIsolation: true,
        nodeIntegration: false, spellcheck: false, backgroundThrottling: true } });
    lockNavigation(overlay, (url) => isOverlay(url, config.serverUrl) || isCoreSetup(url, config.serverUrl));
    rememberWindow(overlay, 'overlay');
    overlay.on('close', (event) => { if (!quitting) { event.preventDefault(); hideOverlay(); } });
    const win = overlay;
    const connectionFailed = watchClient(win, 'overlay');
    win.loadURL(`${config.serverUrl}/static/desktop/index.html`).catch(() => connectionFailed());
  }
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
  const win = kind === 'nudge' ? nudgeWindow : kind === 'settings' ? settingsWindow : kind === 'workspace' ? workspace : kind === 'recovery' ? recoveryWindow : overlay;
  const allowed = kind === 'nudge' ? event.senderFrame?.url === nudgeUrl : kind === 'settings' ? event.senderFrame?.url === settingsUrl :
    kind === 'workspace' ? isWorkspace(event.senderFrame?.url, config.serverUrl) :
    kind === 'recovery' ? event.senderFrame?.url === recoveryUrl : isOverlay(event.senderFrame?.url, config.serverUrl);
  if (!win || event.sender !== win.webContents || event.senderFrame !== event.sender.mainFrame ||
      !allowed)
    throw new Error('許可されていない呼び出しです。');
}
async function downloadAndInstallWindows(release) {
  if (process.platform !== 'win32' || process.arch !== 'x64' || !app.isPackaged) throw new Error('この環境ではアプリ内更新を利用できません。');
  const asset = installerAsset(release, process.platform, process.arch);
  if (!asset) throw new Error('更新用installerを確認できませんでした。');
  const target = settingsWindow || workspace || overlay;
  let destination;
  try {
    destination = await downloadVerified(asset, app.getPath('temp'), { progress: (value) => {
      if (target && !target.isDestroyed()) target.setProgressBar(value);
      if (settingsWindow && !settingsWindow.isDestroyed()) settingsWindow.webContents.send('settings:update-progress', `更新をダウンロード中… ${Math.round(value * 100)}%`);
    } });
    const result = await shell.openPath(destination);
    if (result) throw new Error('installerを起動できませんでした。Releasesから再取得してください。');
  } catch (error) {
    if (destination) await fs.promises.rm(path.dirname(destination), { recursive: true, force: true });
    throw error;
  } finally { if (target && !target.isDestroyed()) target.setProgressBar(-1); }
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
      const canInstall = process.platform === 'win32' && process.arch === 'x64' && app.isPackaged && installerAsset(release, process.platform, process.arch);
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
  for (const kind of ['workspace', 'desktop', 'settings']) {
    const sender = kind === 'desktop' ? 'overlay' : kind;
    on(`${kind}:notifications-read`, sender, desktopNotificationStatus);
    on(`${kind}:notifications-enable`, sender, setDesktopNotifications);
    on(`${kind}:notifications-test`, sender, async () => {
      notificationError = '';
      if (suspended || quitting) throw new Error('ロック・スリープ・終了中は通知をテストできません。');
      const result = await deliverDesktopNotification({ title: 'PETIT 通知テスト', body: 'この形で声をかけます。届いたか確認してください。' });
      return { ...desktopNotificationStatus(), message: config.notificationMode === 'native' ? deliveryMessage(result) : '画面の声かけを要求しました。このモードは無音です。表示を確認してください。' };
    });
  }
  on('nudge:read', 'nudge', () => nudgeEvent);
  on('nudge:dismiss', 'nudge', closeNudge);
  on('nudge:open', 'nudge', () => { closeNudge(); showWorkspace(); });
  on('nudge:hover', 'nudge', (hover) => { if (hover === true) clearTimeout(nudgeTimer); else dismissNudgeLater(); });
  on('desktop:hide', 'overlay', () => hideOverlay());
  on('desktop:open-web', 'overlay', () => shell.openExternal(config.serverUrl));
  on('desktop:workspace', 'overlay', () => showWorkspace());
  on('workspace:chat', 'workspace', () => showOverlay());
  on('workspace:voice', 'workspace', () => showOverlay(true));
  on('workspace:settings', 'workspace', () => showSettings());
  on('workspace:ready', 'workspace', () => { workspace.petitReady = true; });
  on('recovery:read', 'recovery', () => recoveryState);
  on('recovery:settings', 'recovery', () => { recoveryWindow.close(); showSettings(); });
  on('recovery:retry', 'recovery', () => {
    const target = recoveryState.target;
    recoveryWindow.close();
    if (target === 'workspace') showWorkspace(); else showOverlay();
  });
  on('desktop:settings', 'overlay', () => showSettings());
  on('desktop:cancel', 'overlay', () => cancelStt());
  on('desktop:ready', 'overlay', () => {
    overlayReady = true;
    overlay.petitReady = true;
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
  on('settings:wake-setup', 'settings', async (values = {}) => {
    if (wakeSetupController) return { ok: false, message: 'openWakeWordの自動設定はすでに実行中です。' };
    if (suspended || quitting) return { ok: false, message: 'ロック・スリープ解除後に再試行してください。' };
    const controller = new AbortController(); wakeSetupController = controller;
    const owner = settingsWindow;
    const report = (message) => { if (message && owner && !owner.isDestroyed()) owner.webContents.send('settings:wake-progress', message); };
    try {
      stopWake();
      const prepared = await prepareWakeEnvironment({
        userData: app.getPath('userData'), projectRoot: path.resolve(__dirname, '..'), resourcesPath: process.resourcesPath || '',
        currentModelPath: typeof values.modelPath === 'string' ? values.modelPath.trim() : config.modelPath, signal: controller.signal, report,
      });
      controller.signal.throwIfAborted();
      persistConfig({ ...config, modelPath: prepared.modelPath, backbonePath: prepared.backbonePath,
        wakePythonPath: prepared.pythonPath });
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
      wakePythonPath: config.wakePythonPath || '',
      wakeEnabled: values.wakeEnabled === true, login: values.login === true, updates: values.updates === true,
      notifications: values.notifications === true, notificationMode: values.notificationMode === 'native' ? 'native' : 'gentle',
      notificationSound: values.notificationSound === true,
      wakeThreshold: threshold };
    if (next.modelPath && (!path.isAbsolute(next.modelPath) || path.extname(next.modelPath).toLowerCase() !== '.onnx' || !fs.statSync(next.modelPath).isFile())) throw new Error('ONNXモデルを選択してください。');
    if (next.backbonePath && (!path.isAbsolute(next.backbonePath) || !fs.statSync(next.backbonePath).isDirectory())) throw new Error('特徴抽出モデルのフォルダを選択してください。');
    if (next.wakeEnabled && (!next.modelPath || !next.backbonePath || !next.sttUrl)) throw new Error('音声待機にはSTT URL・ONNXモデル・backboneフォルダが必要です。');
    if (next.login && !app.isPackaged) throw new Error('ログイン時の起動はインストール版で設定してください。');
    const changedServer = next.serverUrl !== config.serverUrl;
    if (next.notifications && (!config.notifications || changedServer)) delete cursors[next.serverUrl];
    persistConfig(next);
    closeNudge(); notificationError = ''; nativeDelivery.reset(); void pollNotifications();
    stopWake(); cancelStt(); wakeFailed = false; lastWakeError = '';
    if (app.isPackaged) app.setLoginItemSettings({ openAtLogin: config.login, args: ['--background'] });
    if (workspace && !workspace.isDestroyed() && changedServer) workspace.destroy();
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
  app.on('before-quit', () => { quitting = true; closeNudge(); cancelWakeSetup(); stopWake(); cancelStt(); globalShortcut.unregisterAll(); });
  app.whenReady().then(() => {
    configFile = path.join(app.getPath('userData'), 'desktop.json'); config = readConfig();
    if (process.platform === 'win32') app.setAppUserModelId('jp.soso2e.petit');
    cursorFile = path.join(app.getPath('userData'), 'notification-cursors.json');
    try { cursors = JSON.parse(fs.readFileSync(cursorFile, 'utf8')); if (!cursors || typeof cursors !== 'object' || Array.isArray(cursors)) cursors = {}; } catch { cursors = {}; }
    feed = notificationFeed({
      fetchJson: async (url) => {
        const response = await session.defaultSession.fetch(url, { redirect: 'error', signal: AbortSignal.timeout(8000) });
        if (!response.ok) throw new Error('notification'); return response.json();
      },
      show: deliverDesktopNotification,
      loadCursor: (origin) => Number.isSafeInteger(cursors[origin]) && cursors[origin] >= 0 ? cursors[origin] : null,
      saveCursor: (origin, value) => { cursors[origin] = value; fs.writeFileSync(`${cursorFile}.tmp`, JSON.stringify(cursors), { mode: 0o600 }); fs.renameSync(`${cursorFile}.tmp`, cursorFile); },
    });
    geometry = windowState(path.join(app.getPath('userData'), 'windows.json'));
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
      if (suspended) { closeNudge(); cancelWakeSetup(); stopWake(); hideOverlay(false); } else { void startWake(); void pollNotifications(); }
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
    void pollNotifications();
    setInterval(() => void pollNotifications(), 15000).unref();
  });
}
