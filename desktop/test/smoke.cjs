// Real Electron windows against a temporary fixture server. Never uses the owner's DB/mic.
const { _electron: electron } = require('playwright');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '../..');
const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'petit-desktop-smoke-'));
const calls = [];
let serveOverlay = true;
const mime = { '.html': 'text/html', '.js': 'application/javascript', '.css': 'text/css' };
const server = http.createServer(async (request, response) => {
  const url = new URL(request.url, 'http://localhost');
  if (!serveOverlay && url.pathname === '/static/desktop/index.html') { response.writeHead(404).end('Not found'); return; }
  if (url.pathname.startsWith('/static/')) {
    const file = path.resolve(root, 'frontend', url.pathname.slice(8));
    if (!file.startsWith(path.join(root, 'frontend') + path.sep) || !fs.existsSync(file)) { response.writeHead(404).end(); return; }
    response.setHeader('Content-Type', mime[path.extname(file)] || 'application/octet-stream');
    response.end(fs.readFileSync(file)); return;
  }
  const chunks = []; for await (const chunk of request) chunks.push(chunk);
  const raw = Buffer.concat(chunks);
  if (url.pathname === '/inference') {
    assert.ok(raw.includes(Buffer.from('RIFF')));
    const number = calls.filter((call) => call.path === '/inference').length;
    calls.push({ path: '/inference' });
    response.setHeader('Content-Type', 'application/json');
    response.end(JSON.stringify({ text: number === 0 ? 'テスト予定を追加' : 'はい' })); return;
  }
  let body = raw.toString();
  const data = body ? JSON.parse(body) : {};
  calls.push({ path: url.pathname, data });
  response.setHeader('Content-Type', 'application/json');
  let payload = {};
  if (url.pathname === '/api/health') payload = { chat_model: { server_ok: true, label: 'Fixture' }, agent_model: { server_ok: true, label: 'Fixture' } };
  if (url.pathname === '/api/conversations') payload = { conversations: [] };
  if (url.pathname === '/api/proactive') payload = { message: '何から始めよう？' };
  if (url.pathname === '/api/jobs') payload = { jobs: [] };
  if (url.pathname === '/api/chat') payload = { request_id: data.request_id, reply: 'テスト予定を追加しますか？', pending_actions: [{ name: 'add_schedule', approval_id: 'fixture-approval', arguments: { title: 'テスト予定' } }] };
  if (url.pathname === '/api/actions/fixture-approval') payload = { reply: data.approved ? '予定を追加しました。' : 'キャンセルしました。' };
  response.end(JSON.stringify(payload));
});
(async () => {
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const origin = `http://127.0.0.1:${server.address().port}`;
  const bootstrap = path.join(profile, 'bootstrap.cjs');
  fs.writeFileSync(bootstrap, `require('electron').app.setPath('userData', ${JSON.stringify(profile)}); require(${JSON.stringify(path.join(root, 'desktop/main.cjs'))});`);
  let instance;
  try {
    fs.writeFileSync(path.join(profile, 'package.json'), JSON.stringify({ name: 'petit-desktop-smoke', version: '0.20.0', main: 'bootstrap.cjs' }));
    instance = await electron.launch({ args: [profile], cwd: path.join(root, 'desktop'), timeout: 30000 });
    const probe = path.join(profile, 'probe.cjs');
    const nativeBase = process.env.PETIT_PACKAGED_ASAR || path.join(root, 'desktop');
    fs.writeFileSync(probe, `require(${JSON.stringify(path.join(nativeBase, 'node_modules/@picovoice/pvrecorder-node'))}); require(${JSON.stringify(path.join(nativeBase, 'node_modules/@picovoice/porcupine-node'))}); process.parentPort.postMessage('loaded');`);
    assert.equal(await instance.evaluate(({ utilityProcess }, file) => new Promise((resolve) => {
      const child = utilityProcess.fork(file, [], { stdio: 'ignore' });
      const timer = setTimeout(() => { child.kill(); resolve(false); }, 5000);
      child.on('message', (value) => { clearTimeout(timer); child.kill(); resolve(value === 'loaded'); });
      child.on('exit', () => { clearTimeout(timer); resolve(false); });
    }), probe), true, 'native SDKs load in the actual utility process without opening a microphone');
    const setup = await instance.firstWindow();
    await setup.locator('#serverUrl').fill(origin);
    await setup.locator('#updates').uncheck();
    const opened = instance.waitForEvent('window', { predicate: (page) => page !== setup });
    await setup.locator('button[type=submit]').click();
    const page = await opened;
    await page.waitForURL(`${origin}/static/desktop/index.html`);
    const errors = []; page.on('pageerror', (e) => errors.push(e.message));
    await page.locator('#input').fill('テスト予定を追加');
    await page.locator('#send').click();
    await page.getByRole('button', { name: '実行する', exact: true }).waitFor();
    assert.equal(calls.filter((call) => call.path.includes('/api/actions/')).length, 0, 'no write before confirmation');
    await page.getByRole('button', { name: '実行する', exact: true }).click();
    await page.getByText('予定を追加しました。', { exact: true }).waitFor();
    assert.deepEqual(calls.find((call) => call.path.includes('/api/actions/')).data, { approved: true });
    assert.ok(calls.find((call) => call.path === '/api/chat').data.session_id);
    assert.equal(await page.evaluate(() => typeof window.require), 'undefined');
    assert.equal(await page.evaluate(() => typeof window.petitSettings), 'undefined');
    assert.equal(await page.locator('#mic').isDisabled(), true, 'unconfigured STT does not record');
    assert.equal(await page.evaluate(async () => (await navigator.serviceWorker.getRegistrations()).length), 0);
    // Test the IPC sender guard by invoking the registered settings handler with the overlay frame.
    assert.equal(await instance.evaluate(async ({ ipcMain, BrowserWindow }) => {
      const web = BrowserWindow.getAllWindows().find((w) => w.webContents.getURL().includes('/static/desktop/'));
      try { await ipcMain._invokeHandlers.get('settings:read')({ sender: web.webContents, senderFrame: web.webContents.mainFrame }); return false; }
      catch { return true; }
    }), true);
    await page.evaluate(() => { window.open('https://example.com'); });
    assert.equal(await instance.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows().length), 1);
    const screenshot = path.join(root, 'desktop/dist/smoke-overlay.png');
    fs.mkdirSync(path.dirname(screenshot), { recursive: true });
    await page.screenshot({ path: screenshot });
    await page.locator('#hide').click();
    assert.equal(await instance.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].isVisible()), false);
    await instance.evaluate(({ app }) => app.emit('activate'));
    assert.equal(await instance.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].isVisible()), true);
    // Same persisted window, no conversation reset on reactivation.
    assert.ok(await page.getByText('予定を追加しました。', { exact: true }).isVisible());
    const settingsOpened = instance.waitForEvent('window');
    await page.locator('#desktop-settings').click();
    const settings = await settingsOpened;
    await settings.waitForURL(/setup.html$/);
    assert.equal(await settings.locator('#serverUrl').inputValue(), origin);
    assert.equal(await settings.locator('#updates').isChecked(), false);
    await settings.locator('#sttUrl').fill(`${origin}/inference`);
    const voiceOpened = instance.waitForEvent('window');
    await settings.locator('button[type=submit]').click();
    const voicePage = await voiceOpened;
    await voicePage.waitForURL(`${origin}/static/desktop/index.html`);
    await voicePage.locator('#mic').waitFor();
    // A generated tone replaces the microphone; the actual AudioWorklet, WAV upload,
    // transcription adapter, shared voice.js and confirmation UI still execute.
    await voicePage.evaluate(() => {
      navigator.mediaDevices.getUserMedia = async () => {
        const context = new AudioContext();
        const oscillator = context.createOscillator();
        const gain = context.createGain(); gain.gain.value = .1;
        const destination = context.createMediaStreamDestination();
        oscillator.connect(gain); gain.connect(destination); oscillator.start();
        const track = destination.stream.getAudioTracks()[0]; const stop = track.stop.bind(track);
        track.stop = () => { stop(); oscillator.stop(); void context.close(); };
        return destination.stream;
      };
    });
    const beforeVoice = calls.filter((call) => call.path.includes('/api/actions/')).length;
    for (let turn = 0; turn < 2; turn++) {
      await instance.evaluate(({ BrowserWindow }) => {
        BrowserWindow.getAllWindows()[0].webContents.send('desktop:activate', { voice: true });
      });
      await voicePage.locator('#mic.mic--listening').waitFor();
      // Wait on the signal in the live audio graph, not on a real microphone.
      await voicePage.waitForTimeout(450);
      await voicePage.locator('#mic').click();
      if (turn === 0) {
        await voicePage.getByRole('button', { name: '実行する', exact: true }).waitFor();
        assert.equal(calls.filter((call) => call.path.includes('/api/actions/')).length, beforeVoice);
      } else await voicePage.getByText('予定を追加しました。', { exact: true }).last().waitFor();
    }
    assert.equal(calls.filter((call) => call.path === '/inference').length, 2);
    assert.equal(calls.filter((call) => call.path.includes('/api/actions/')).length, beforeVoice + 1);
    // Sleep and screen lock overlap: resume alone must not permit activation.
    await instance.evaluate(({ powerMonitor }) => { powerMonitor.emit('lock-screen'); powerMonitor.emit('suspend'); powerMonitor.emit('resume'); });
    await instance.evaluate(({ app }) => app.emit('activate'));
    assert.equal(await instance.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].isVisible()), false);
    await instance.evaluate(({ powerMonitor, app }) => { powerMonitor.emit('unlock-screen'); app.emit('activate'); });
    assert.equal(await instance.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].isVisible()), true);
    await instance.evaluate(({ dialog }) => { dialog.showMessageBox = async () => ({ response: 0 }); });
    const reconnectSettingsOpened = instance.waitForEvent('window');
    await voicePage.locator('#desktop-settings').click();
    const reconnectSettings = await reconnectSettingsOpened;
    await reconnectSettings.waitForURL(/setup.html$/);
    serveOverlay = false;
    const incompatibleOverlayOpened = instance.waitForEvent('window');
    await reconnectSettings.locator('button[type=submit]').click();
    const incompatibleOverlay = await incompatibleOverlayOpened;
    const recovery = await instance.waitForEvent('window', { timeout: 15000, predicate: (candidate) => candidate !== incompatibleOverlay });
    await recovery.waitForURL(/setup.html$/);
    assert.equal(await recovery.locator('#serverUrl').inputValue(), origin);
    assert.deepEqual(errors, []);
    console.log('PASS: actual Electron setup → shared chat → approval → hide/reopen → settings; synthetic voice/WAV/STT + voice approval; isolated bridge, no PWA registration.');
    console.log(`Screenshot: ${screenshot}`);
  } finally {
    if (instance) await instance.close();
    server.closeAllConnections(); await new Promise((resolve) => server.close(resolve));
    fs.rmSync(profile, { recursive: true, force: true });
  }
})().catch((error) => { console.error(error); process.exitCode = 1; });
