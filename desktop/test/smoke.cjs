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
let fixtureWork = { session_id: 'fixture-work', task_id: '1', task: '作業中の星', status: 'active', started_at: new Date().toISOString() };
const fixtureTasks = [
  { id: 1, title: '作業中の星', status: 'Yet', priority: 'High', source: 'notion', external_id: 'fixture-1', sync_status: 'conflict', due_date: '2020-01-01', root_task_id: 1, root_title: '作業中の星' },
  { id: 2, title: '選択だけの星', status: 'Yet', priority: 'High', source: 'notion', external_id: 'fixture-2', sync_status: 'synced', root_task_id: 2, root_title: '選択だけの星' },
];
let fixturePreferences = { work_session: false };
let statsFailure = '';
let statsEmpty = false;
const fixtureReflections = new Map();
let reflectionConflict = false;
const fixtureStatsDay = {
  date: '2026-10-13', timezone: 'Asia/Tokyo', total_seconds: 9000,
  tasks: [{ task_id: '1', task: 'PETITの改善', elapsed_seconds: 7200 }, { task_id: '2', task: '振り返り <メモ>', elapsed_seconds: 1800 }],
  sessions: [
    { session_id: 'stats-a', task: 'PETITの改善', started_at: '2026-10-13T01:00:00+00:00', ended_at: '2026-10-13T02:00:00+00:00', status: 'ended', elapsed_seconds: 3600 },
    { session_id: 'stats-b', task: '振り返り <メモ>', started_at: '2026-10-13T03:00:00+00:00', ended_at: null, status: 'paused', elapsed_seconds: 1800 },
    { session_id: 'stats-c', task: 'PETITの改善', started_at: '2026-10-13T04:00:00+00:00', ended_at: '2026-10-13T05:00:00+00:00', status: 'ended', elapsed_seconds: 3600 },
  ],
};
const fixtureStatsWeek = {
  date_from: '2026-10-07', date_to: '2026-10-13', timezone: 'Asia/Tokyo', total_seconds: 22200,
  daily: [0, 1800, 3600, 0, 7200, 600, 9000].map((elapsed_seconds, index) => ({ date: `2026-10-${String(7 + index).padStart(2, '0')}`, elapsed_seconds })),
};
const mime = { '.html': 'text/html', '.js': 'application/javascript', '.css': 'text/css' };
const server = http.createServer(async (request, response) => {
  const url = new URL(request.url, 'http://localhost');
  if (statsFailure && url.pathname === `/api/work-sessions/${statsFailure}`) { response.writeHead(503, { 'Content-Type': 'application/json' }).end(JSON.stringify({ error: 'fixture unavailable' })); return; }
  if (!serveOverlay && url.pathname === '/static/desktop/index.html') { response.writeHead(404).end('Not found'); return; }
  if (url.pathname.startsWith('/static/')) {
    const file = path.resolve(root, 'frontend', url.pathname.slice(8));
    if (!file.startsWith(path.join(root, 'frontend') + path.sep) || !fs.existsSync(file)) { response.writeHead(404).end(); return; }
    response.setHeader('Content-Type', mime[path.extname(file)] || 'application/octet-stream');
    let source = fs.readFileSync(file);
    // Inspect real rendered camera/material state only in this isolated fixture.
    if (url.pathname === '/static/universe-webgl-scene.js') {
      source = source.toString().replace('const clamp =', 'window.__fixtureScene = state; const clamp =');
    }
    response.end(source); return;
  }
  const chunks = []; for await (const chunk of request) chunks.push(chunk);
  const raw = Buffer.concat(chunks);
  if (url.pathname === '/inference') {
    assert.ok(raw.includes(Buffer.from('RIFF')));
    const number = calls.filter((call) => call.path === '/inference').length;
    calls.push({ path: '/inference' });
    response.setHeader('Content-Type', 'application/json');
    response.end(JSON.stringify({ text: number === 0 ? 'テスト予定を追加' : number === 1 ? 'はい' : 'こんにちは' })); return;
  }
  let body = raw.toString();
  const data = body ? JSON.parse(body) : {};
  calls.push({ path: url.pathname, data });
  response.setHeader('Content-Type', 'application/json');
  let payload = {};
  if (url.pathname === '/api/notifications/tasks') payload = { tasks: fixtureTasks };
  if (url.pathname === '/api/work-sessions/active') payload = { session: fixtureWork };
  if (url.pathname === '/api/work-sessions/today') payload = statsEmpty ? { ...fixtureStatsDay, total_seconds: 0, tasks: [], sessions: [], active: null } : { ...fixtureStatsDay, active: fixtureWork };
  if (url.pathname === '/api/work-sessions/today') payload.reflection = fixtureReflections.get(fixtureStatsDay.date) || { note: '', revision: 0 };
  if (url.pathname.startsWith('/api/work-sessions/days/')) {
    const date = url.pathname.split('/')[4];
    const reflection = fixtureReflections.get(date) || { note: '', revision: 0 };
    if (url.pathname.endsWith('/reflection')) {
      if (reflectionConflict || data.revision !== reflection.revision) { response.writeHead(409).end(JSON.stringify({ detail: '別の画面で更新されました。' })); return; }
      payload = { reflection: { note: data.note.trim(), revision: reflection.revision + 1 } };
      fixtureReflections.set(date, payload.reflection);
    } else {
      payload = { ...fixtureStatsDay, date, total_seconds: 1800, tasks: [{ task: '前日の仕上げ', elapsed_seconds: 1800 }], sessions: [{ task: '前日の仕上げ', started_at: '2026-10-12T01:00:00Z', ended_at: '2026-10-12T01:30:00Z', elapsed_seconds: 1800 }], active: null, reflection };
    }
  }
  if (url.pathname === '/api/work-sessions/summary') payload = statsEmpty ? { ...fixtureStatsWeek, total_seconds: 0, daily: fixtureStatsWeek.daily.map(day => ({ ...day, elapsed_seconds: 0 })) } : fixtureStatsWeek;
  if (url.pathname.endsWith('/fixture-work/pause')) payload = { session: fixtureWork = { ...fixtureWork, status: 'paused', paused_at: new Date().toISOString() } };
  if (url.pathname.endsWith('/fixture-work/resume')) payload = { session: fixtureWork = { ...fixtureWork, status: 'active', paused_at: null } };
  if (url.pathname.endsWith('/fixture-work/end')) payload = { session: fixtureWork = { ...fixtureWork, status: 'ended' } };
  if (url.pathname === '/api/notifications/status') payload = { configured: false, dependency_available: false, preferences: fixturePreferences, categories: [{ id: 'work_session', label: '作業セッション' }] };
  if (url.pathname === '/api/notifications/preferences') payload = { preferences: fixturePreferences = data.preferences };
  if (url.pathname === '/api/notifications/events') payload = { events: [], unread_count: 0 };
  if (url.pathname === '/api/notifications/tasks/sync/conflicts') payload = { tasks: [fixtureTasks[0]] };
  if (url.pathname.endsWith('/1/sync/conflict')) payload = request.method === 'GET' ? { local: { title: '作業中の星', parent_external_ids: ['PETITの親'] }, remote: { title: 'Notionの星', parent_external_ids: [] }, revision: 'a'.repeat(64) } : { message: 'PETIT側の変更を再同期します。まだNotionへの反映は完了していません。', sync_status: 'pending' };
  if (url.pathname === '/api/health') payload = { chat_model: { server_ok: true, label: 'Fixture' }, agent_model: { server_ok: true, label: 'Fixture' } };
  if (url.pathname === '/api/conversations') payload = { conversations: [] };
  if (url.pathname === '/api/proactive') payload = { message: '何から始めよう？' };
  if (url.pathname === '/api/jobs') payload = { jobs: [] };
  if (url.pathname === '/api/chat' && data.message === 'こんにちは') payload = { request_id: data.request_id, reply: 'こんにちは。' };
  else if (url.pathname === '/api/chat') payload = { request_id: data.request_id, reply: 'テスト予定を追加しますか？', pending_actions: [{ name: 'add_schedule', approval_id: 'fixture-approval', arguments: { title: 'テスト予定' } }] };
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
    fs.writeFileSync(path.join(profile, 'package.json'), JSON.stringify({ name: 'petit-desktop-smoke', version: require('../package.json').version, main: 'bootstrap.cjs' }));
    instance = await electron.launch({ args: [profile], cwd: path.join(root, 'desktop'), timeout: 30000 });
    const wakeWorker = path.join(root, 'desktop/wake-worker.cjs');
    assert.equal(await instance.evaluate(({ utilityProcess }, file) => new Promise((resolve) => {
      const child = utilityProcess.fork(file, [], { stdio: 'ignore' });
      let done = false; let timer;
      const finish = (value) => {
        if (done) return; done = true; clearTimeout(timer);
        if (value) child.kill();
        resolve(value);
      };
      timer = setTimeout(() => finish(true), 300);
      child.on('exit', () => finish(false));
      child.on('error', () => finish(false));
    }), wakeWorker), true, 'openWakeWord worker loads in the actual utility process without opening a microphone');
    const setup = await instance.firstWindow();
    await setup.emulateMedia({ reducedMotion: 'no-preference' });
    assert.equal(await setup.locator('main').evaluate((el) => getComputedStyle(el).animationName), 'setupEnter');
    await setup.emulateMedia({ reducedMotion: 'reduce' });
    assert.equal(await setup.locator('main').evaluate((el) => getComputedStyle(el).animationName), 'none');
    await setup.emulateMedia({ reducedMotion: 'no-preference' });
    assert.equal(await setup.locator('[data-model=onnx]').isVisible(), true);
    assert.equal(await setup.locator('[data-model=dir]').isVisible(), true);
    assert.equal(await setup.locator('#wakeThreshold').inputValue(), '0.45');
    assert.equal(await setup.locator('#wakeEnabled').isChecked(), false);
    assert.equal(await setup.locator('#notificationSound').isChecked(), false);
    await setup.locator('#notificationSound').check();
    const nudgeOpened = instance.waitForEvent('window', { predicate: candidate => candidate !== setup });
    await setup.locator('#notification-test').click();
    const nudge = await nudgeOpened;
    await nudge.waitForURL(/nudge.html$/);
    await nudge.locator('#body').getByText('この形で声をかけます。届いたか確認してください。').waitFor();
    assert.equal(await nudge.evaluate(() => typeof window.require), 'undefined');
    assert.equal(await nudge.evaluate(() => typeof window.petitSettings), 'undefined');
    await nudge.screenshot({ path: path.join(root, 'desktop/dist/smoke-nudge.png') });
    await nudge.locator('#dismiss').click();
    await setup.locator('#serverUrl').fill(origin);
    await setup.locator('#updates').uncheck();
    const opened = instance.waitForEvent('window', { predicate: (page) => page !== setup });
    await setup.locator('button[type=submit]').click();
    const page = await opened;
    await page.waitForURL(`${origin}/static/desktop/index.html`);
    assert.equal(await page.locator('.presence, .orb, .orbit').count(), 0, 'compact chat has no planet above the date');
    if (process.env.PETIT_SMOKE_SCOPE === 'notifications') {
      const workspaceOpened = instance.waitForEvent('window');
      await page.locator('#open-workspace').click();
      const workspace = await workspaceOpened;
      await workspace.waitForURL(`${origin}/static/universe.html`);
      await workspace.locator('#petit-desktop-toolbar').waitFor();
      await workspace.evaluate(() => window.PetitAppShell.activateView('settings'));
      await workspace.locator('#notification-enable').click();
      await workspace.locator('#notification-disable').waitFor({ state: 'visible' });
      const status = await workspace.evaluate(() => window.petitNotifications.read());
      assert.equal(status.enabled, true); assert.equal(status.sound, true);
      assert.equal(status.permission, 'unknown');
      assert.equal(fixturePreferences.work_session, true);
      assert.equal(await workspace.evaluate(() => Notification.permission), 'denied');
      assert.doesNotMatch(await workspace.locator('#notification-state').textContent(), /ブラウザ設定で拒否/);
      await workspace.locator('#notification-test').click();
      await workspace.waitForFunction(() => document.querySelector('#notification-state').textContent.includes('無音'));
      await workspace.locator('#notification-disable').click();
      await workspace.locator('#notification-enable').waitFor({ state: 'visible' });
      assert.equal(await workspace.evaluate(async () => (await window.petitNotifications.read()).enabled), false);
      console.log('Desktop notification smoke OK: persisted sound opt-in, denied Web permission, independent Desktop enable/test/disable');
      return;
    }

    await page.emulateMedia({ reducedMotion: 'no-preference' });
    assert.equal(await page.locator('#greeting').evaluate((el) => getComputedStyle(el).animationName), 'petitMessageEnter');
    await page.emulateMedia({ reducedMotion: 'reduce' });
    assert.equal(await page.locator('#greeting').evaluate((el) => getComputedStyle(el).animationName), 'none');
    await page.emulateMedia({ reducedMotion: 'no-preference' });
    const errors = []; page.on('pageerror', (e) => errors.push(e.message));
    const beforeInput = calls.filter(call => call.path === '/api/chat').length;
    await page.locator('#input').fill('変換確定のEnter');
    await page.evaluate(() => {
      const input = document.getElementById('input');
      input.dispatchEvent(new CompositionEvent('compositionstart', { bubbles: true }));
      input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', isComposing: true, bubbles: true, cancelable: true }));
      input.dispatchEvent(new CompositionEvent('compositionend', { bubbles: true }));
    });
    await page.waitForTimeout(80);
    await page.evaluate(() => document.getElementById('input').dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', repeat: true, bubbles: true, cancelable: true })));
    assert.equal(calls.filter(call => call.path === '/api/chat').length, beforeInput, 'IME confirmation and held Enter never submit');
    await page.locator('#input').fill('複数行\n'.repeat(20));
    assert.ok(await page.locator('#input').evaluate(el => el.clientHeight <= 90 && getComputedStyle(el).overflowY === 'auto'));
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
    await page.waitForTimeout(300);
    const hiddenReads = calls.filter(call => ['/api/jobs', '/api/health'].includes(call.path)).length;
    await page.waitForTimeout(2200);
    assert.equal(calls.filter(call => ['/api/jobs', '/api/health'].includes(call.path)).length, hiddenReads, 'hidden quick chat pauses polling');
    await instance.evaluate(({ app }) => app.emit('activate'));
    assert.equal(await instance.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].isVisible()), true);
    // Same persisted window, no conversation reset on reactivation.
    assert.ok(await page.getByText('予定を追加しました。', { exact: true }).isVisible());
    // A failed write must restore input without automatically sending it twice.
    const beforeFailure = calls.filter(call => call.path === '/api/chat').length;
    await page.route('**/api/chat', route => route.fulfill({ status: 503, json: { error: 'fixture offline' } }));
    await page.locator('#input').fill('失敗時に保持する文章');
    await page.locator('#send').click();
    await page.waitForFunction(() => !document.getElementById('send').disabled);
    assert.equal(await page.locator('#input').inputValue(), '失敗時に保持する文章');
    assert.equal(calls.filter(call => call.path === '/api/chat').length, beforeFailure);
    await page.unroute('**/api/chat');
    await page.locator('#input').fill('設定変更をまたぐ下書き');
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
    assert.equal(await voicePage.locator('#input').inputValue(), '設定変更をまたぐ下書き');
    await voicePage.locator('#input').fill('');
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
    // Exercise the real DOM/voice/controller wiring, using synthetic playback.
    await voicePage.evaluate(() => {
      window.Audio = class {
        play() { window.fixtureAudio = this; window.fixtureAudioPlaying = true; this.onplay?.(); return Promise.resolve(); }
        pause() { window.fixtureAudioPlaying = false; } removeAttribute() {} load() {}
      };
    });
    let ttsRequests = 0;
    await voicePage.route('**/api/tts', route => { ttsRequests++; return route.fulfill({ status: 200, contentType: 'audio/wav', body: Buffer.from('fixture') }); });
    await voicePage.locator('#voice-conversation').click();
    await voicePage.locator('#mic.mic--listening').waitFor();
    await voicePage.waitForTimeout(450);
    await voicePage.locator('#mic').click();
    await voicePage.getByText('こんにちは。', { exact: true }).last().waitFor();
    assert.equal(calls.filter(call => call.path === '/api/chat').at(-1).data.conversation_mode, 'voice');
    await voicePage.waitForFunction(() => window.fixtureAudioPlaying);
    // Restore real fixture history while a new answer is playing. It must neither
    // enqueue the old reply nor treat an old user bubble as a new interruption.
    await voicePage.route('**/api/conversations?*', route => route.fulfill({ json: {
      conversations: [{ user_text: '過去の質問', assistant_text: '過去の返答' }],
    } }));
    assert.equal(await voicePage.evaluate(() => restoreHistory()), true);
    await voicePage.getByText('過去の返答', { exact: true }).waitFor();
    assert.equal(ttsRequests, 1);
    assert.equal(await voicePage.evaluate(() => window.fixtureAudioPlaying), true);
    await voicePage.evaluate(() => window.fixtureAudio.onended());
    await voicePage.locator('#mic.mic--listening').waitFor();
    await voicePage.locator('#voice-conversation').click();
    assert.equal(await voicePage.locator('#mic').getAttribute('aria-label'), '音声入力を開始');
    assert.equal(await voicePage.locator('#voice-conversation').getAttribute('aria-pressed'), 'false');
    await voicePage.getByText('過去の返答', { exact: true }).locator('..').getByRole('button', { name: 'この返答を読み上げる' }).click();
    await voicePage.waitForFunction(() => window.fixtureAudioPlaying);
    assert.equal(ttsRequests, 2, 'restored replies retain manual playback');
    await voicePage.evaluate(() => window.fixtureAudio.onended());
    // Sleep and screen lock overlap: resume alone must not permit activation.
    await instance.evaluate(({ powerMonitor }) => { powerMonitor.emit('lock-screen'); powerMonitor.emit('suspend'); powerMonitor.emit('resume'); });
    await instance.evaluate(({ app }) => app.emit('activate'));
    assert.equal(await instance.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].isVisible()), false);
    await instance.evaluate(({ powerMonitor, app }) => { powerMonitor.emit('unlock-screen'); app.emit('activate'); });
    assert.equal(await instance.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].isVisible()), true);
    // Workspace reuses the real Universe UI but has a narrow, separate IPC bridge.
    const workspaceOpened = instance.waitForEvent('window');
    await voicePage.locator('#open-workspace').click();
    const workspace = await workspaceOpened;

    await workspace.waitForURL(`${origin}/static/universe.html`);
    await workspace.locator('#petit-desktop-toolbar').waitFor();
    assert.equal(await workspace.evaluate(() => typeof require), 'undefined');
    assert.equal(await workspace.evaluate(() => typeof window.petitDesktop), 'undefined');
    assert.equal(await workspace.evaluate(async () => (await navigator.serviceWorker.getRegistrations()).length), 0);
    assert.equal(await instance.evaluate(async ({ ipcMain, BrowserWindow }) => {
      const web = BrowserWindow.getAllWindows().find(win => win.webContents.getURL().endsWith('/static/universe.html'));
      try { await ipcMain._invokeHandlers.get('desktop:transcribe')({ sender: web.webContents, senderFrame: web.webContents.mainFrame }); return false; }
      catch { return true; }
    }), true);
    await workspace.getByRole('button', { name: '小型会話', exact: true }).click();
    await workspace.waitForTimeout(1000);
    const rail = workspace.locator('.petit-area-rail');
    const railWidth = (width) => workspace.waitForFunction(value => Math.round(document.querySelector('.petit-area-rail').getBoundingClientRect().width) === value, width);
    await workspace.mouse.move(600, 300);
    await railWidth(72);
    assert.equal(await workspace.locator('.petit-area-rail__nav button > span:last-child').first().isVisible(), false, 'Univ starts with an icon rail');
    const sceneBounds = await workspace.locator('.univ-viewport').boundingBox();
    await workspace.screenshot({ path: path.join(root, 'desktop/dist/smoke-rail-compact.png') });
    await rail.hover(); await railWidth(232);
    assert.equal(await workspace.locator('.petit-area-rail__nav button > span:last-child').first().isVisible(), true);
    assert.deepEqual(await workspace.locator('.univ-viewport').boundingBox(), sceneBounds, 'hover does not move or resize Univ');
    await workspace.screenshot({ path: path.join(root, 'desktop/dist/smoke-rail-expanded.png') });
    await workspace.mouse.move(600, 300); await railWidth(72);
    await workspace.locator('[data-rail-view="tasks"]').focus(); await railWidth(232);
    await workspace.locator('[data-rail-view="tasks"]').evaluate(el => el.blur()); await railWidth(72);
    await workspace.locator('.petit-area-rail__pin').click();
    await workspace.waitForFunction(() => document.body.dataset.petitRailMode === 'pinned');
    await workspace.reload();
    await workspace.waitForFunction(() => document.body.dataset.petitRailMode === 'pinned');
    await railWidth(232);
    await workspace.locator('.petit-area-rail__pin').click();
    await workspace.mouse.move(600, 300); await railWidth(72);
    await workspace.emulateMedia({ reducedMotion: 'reduce' });
    assert.ok(await rail.evaluate(el => parseFloat(getComputedStyle(el).transitionDuration) <= .001), 'reduced motion uses the shared near-zero transition');
    await workspace.emulateMedia({ reducedMotion: 'no-preference' });
    await workspace.waitForFunction(() => window.PetitUniverse?.workingTask() === '1');
    await workspace.waitForFunction(() => window.PetitUnivWebGL?.initialized && window.__fixtureScene?.entries.size >= 2);
    await workspace.waitForFunction(() => !window.__fixtureScene.renderFrame);
    assert.ok(await workspace.evaluate(() => {
      const scene = window.__fixtureScene;
      return scene.overviewPoints.every(({ position, radius }) => {
        const p = position.clone().project(scene.camera);
        return Math.abs(p.x) < .86 && Math.abs(p.y) < .72 && p.z > -1 && p.z < 1;
      });
    }), 'overview fits every planet/satellite center with room for HUD');
    const workGlow = await workspace.evaluate(() => {
      const work = window.__fixtureScene.entries.get('1').object;
      const other = window.__fixtureScene.entries.get('2').object;
      return { working: work.userData.working, opacity: work.getObjectByName('Atmosphere').material.uniforms.glowOpacity.value,
        otherOpacity: other.getObjectByName('Atmosphere').material.uniforms.glowOpacity.value,
        dimmed: other.userData.dimmed, ratio: work.material.emissiveIntensity / other.material.emissiveIntensity };
    });
    assert.ok(workGlow.working && workGlow.dimmed && workGlow.opacity > workGlow.otherOpacity * 10 && workGlow.ratio > 5, 'working planet itself and its persistent halo shine while other planets dim');
    const canvas = await workspace.locator('.univ-webgl-canvas').boundingBox();
    const cameraState = () => workspace.evaluate(() => ({ camera: window.__fixtureScene.camera.position.toArray(), target: window.__fixtureScene.controls.target.toArray(), selection: window.__fixtureScene.selectedTaskId }));
    const beforePan = await cameraState();
    await workspace.mouse.move(canvas.x + canvas.width * .65, canvas.y + canvas.height * .65);
    await workspace.mouse.down({ button: 'middle' });
    await workspace.mouse.move(canvas.x + canvas.width * .65 + 60, canvas.y + canvas.height * .65 + 30, { steps: 6 });
    await workspace.mouse.up({ button: 'middle' });
    const afterPan = await cameraState();
    assert.ok(afterPan.target.some((value, i) => Math.abs(value - beforePan.target[i]) > .01), 'middle drag pans the target');
    for (let i = 0; i < 3; i++) assert.ok(Math.abs((afterPan.camera[i] - beforePan.camera[i]) - (afterPan.target[i] - beforePan.target[i])) < .001, 'pan preserves camera direction and distance');
    assert.equal(afterPan.selection, beforePan.selection, 'middle drag never selects a planet');
    const beforeAltPan = await cameraState();
    await workspace.keyboard.down('Alt');
    await workspace.mouse.down({ button: 'middle' });
    await workspace.mouse.move(canvas.x + canvas.width * .65 + 90, canvas.y + canvas.height * .65 + 45, { steps: 4 });
    await workspace.mouse.up({ button: 'middle' });
    await workspace.keyboard.up('Alt');
    const afterAltPan = await cameraState();
    assert.ok(afterAltPan.target.some((value, i) => Math.abs(value - beforeAltPan.target[i]) > .01), 'Alt+Middle also pans');
    for (let i = 0; i < 3; i++) assert.ok(Math.abs((afterAltPan.camera[i] - beforeAltPan.camera[i]) - (afterAltPan.target[i] - beforeAltPan.target[i])) < .001);
    await workspace.screenshot({ path: path.join(root, 'desktop/dist/smoke-v27-planets.png') });
    assert.ok(await workspace.locator('[data-task-id="1"].is-working').count() > 0);
    await workspace.evaluate(() => window.PetitUniverse.selectTask('2'));
    assert.equal(await workspace.locator('[data-task-id="2"].is-working').count(), 0, 'selection does not move work focus');
    await workspace.evaluate(() => document.getElementById('work-session-pause').click());
    await workspace.waitForFunction(() => window.PetitUniverse.workingTask() === null);
    await workspace.waitForFunction(() => document.getElementById('petit-context-session').textContent.startsWith('一時停止中：'));
    await workspace.waitForFunction(() => !window.__fixtureScene.renderFrame);
    assert.ok(await workspace.evaluate(() => {
      const work = window.__fixtureScene.entries.get('1').object;
      return !work.userData.working && Math.abs(work.getObjectByName('Atmosphere').material.uniforms.glowOpacity.value - .12) < .001;
    }), 'pause restores the former work planet glow');
    assert.equal(await workspace.locator('[data-task-id].is-working').count(), 0, 'pause removes work emphasis');
    await workspace.evaluate(() => document.getElementById('work-session-pause').click());
    await workspace.waitForFunction(() => window.PetitUniverse.workingTask() === '1');
    await workspace.evaluate(() => window.dispatchEvent(new CustomEvent('petit:navigate', { detail: { view: 'tasks' } })));
    assert.equal(await workspace.locator('tr[data-due-state="overdue"] .task-due-badge').textContent(), '期限切れ');
    await workspace.locator('#task-table-body .task-table__title').filter({ hasText: '作業中の星' }).click();
    const rowTitle = workspace.locator('#task-table-body .task-table__title').filter({ hasText: '選択だけの星' });
    await rowTitle.click();
    assert.ok(await workspace.locator('[data-view-panel="tasks"]').isVisible());
    await rowTitle.locator('..').press('Enter');
    await workspace.waitForFunction(() => document.body.classList.contains('petit-univ-manage-open') && window.__fixtureScene.selectedTaskId === '2', null, { timeout: 5000 }).catch(async error => {
      console.log('UX selection diagnostic:', await workspace.evaluate(() => ({ classes: document.body.className, selected: window.__fixtureScene.selectedTaskId, hud: document.querySelector('[data-univ-selected-title]').textContent, camera: window.__fixtureScene.camera.position.toArray(), radius: window.__fixtureScene.overviewRadius })));
      await workspace.screenshot({ path: path.join(root, 'desktop/dist/smoke-ux-failure.png') }); throw error;
    });
    assert.equal(await workspace.locator('[data-univ-selected-title]').textContent(), '選択だけの星');
    assert.equal(await workspace.locator('[data-univ-action="manage"]').isEnabled(), true);
    assert.equal(await workspace.locator('#detail-panel [data-detail-form]').isVisible(), false);
    await workspace.locator('#detail-panel [data-action="toggle-edit"]').click();
    assert.equal(await workspace.locator('#detail-panel [data-detail-form]').isVisible(), true);
    assert.equal(await workspace.locator('#detail-panel [data-detail-view="read"]').first().isVisible(), false);
    await workspace.locator('#detail-panel [data-action="cancel-edit"]').click();
    const startBounds = await workspace.locator('#detail-panel [data-action="activate"]').boundingBox();
    const detailBounds = await workspace.locator('#detail-panel').boundingBox();
    assert.ok(startBounds && startBounds.y < detailBounds.y + 180, 'work start is visible near the detail title');
    await workspace.screenshot({ path: path.join(root, 'desktop/dist/smoke-ux-detail.png') });
    await workspace.evaluate(() => window.PetitAppShell.activateView('tasks'));
    await workspace.getByRole('button', { name: '同期競合を確認', exact: true }).click();
    await workspace.locator('.task-conflict-dialog').getByRole('button', { name: '作業中の星', exact: true }).click();
    await workspace.locator('.task-conflict-dialog table').waitFor();
    await workspace.waitForFunction(() => getComputedStyle(document.querySelector('.task-conflict-dialog')).opacity === '1');
    assert.equal(await workspace.locator('.task-conflict-dialog h2').textContent(), '同期競合：作業中の星');
    await workspace.screenshot({ path: path.join(root, 'desktop/dist/smoke-conflict.png') });
    await workspace.getByRole('button', { name: 'PETIT側を残して再同期', exact: true }).click();
    await workspace.getByText('PETIT側の変更を再同期します。まだNotionへの反映は完了していません。', { exact: true }).waitFor();
    await workspace.locator('.task-conflict-dialog').getByRole('button', { name: '閉じる', exact: true }).click();
    await workspace.evaluate(() => window.dispatchEvent(new CustomEvent('petit:navigate', { detail: { view: 'settings' } })));
    await workspace.locator('#notification-enable').click();
    await workspace.locator('#notification-disable').waitFor({ state: 'visible' });
    assert.equal(await workspace.evaluate(async () => (await window.petitNotifications.read()).enabled), true, 'Desktop enables without VAPID');
    assert.equal(await workspace.evaluate(async () => (await window.petitNotifications.read()).sound), true, 'sound setting persisted through settings save');
    assert.equal(await workspace.evaluate(async () => (await window.petitNotifications.read()).permission), 'unknown');
    assert.equal(await workspace.evaluate(() => Notification.permission), 'denied', 'Web permission remains denied while Desktop notifications work');
    assert.equal(fixturePreferences.work_session, true);
    await workspace.locator('#notification-disable').click();
    await workspace.locator('#notification-enable').waitFor({ state: 'visible' });
    assert.equal(await workspace.evaluate(async () => (await window.petitNotifications.read()).enabled), false);
    await workspace.locator('.petit-area-rail__nav button').nth(1).click();
    await workspace.waitForTimeout(350);
    await workspace.screenshot({ path: path.join(root, 'desktop/dist/smoke-workspace.png') });
    const checkChatViewport = async (suffix) => {
      await workspace.evaluate(() => window.PetitAppShell.activateView('chat'));
      await workspace.waitForFunction(() => document.body.classList.contains('petit-chat-screen') && document.getElementById('petit-context-session').textContent === '作業中：作業中の星');
      await workspace.waitForFunction(() => document.querySelector('[data-view-panel="chat"]').getAnimations().every(animation => animation.playState !== 'running'));
      assert.equal(await workspace.locator('#petit-context-view, #petit-context-current, #petit-context-sync').count(), 0);
      assert.equal(await workspace.locator('.chat-context, .quick-prompts').count(), 0, 'Chat has no context panel or quick prompts in the DOM');
      assert.equal(await workspace.locator('select[aria-label="音声入力方式"]').isVisible(), false);
      await workspace.locator('.chat-voice-options > summary').click();
      assert.equal(await workspace.locator('select[aria-label="音声入力方式"]').isVisible(), true);
      await workspace.locator('.chat-voice-options > summary').click();
      assert.equal(await workspace.locator('#detail-panel').isVisible(), false, 'task details are initially collapsed');
      await workspace.locator('#petit-context-bar > summary').click();
      assert.ok(await workspace.locator('#petit-work-details #detail-panel').isVisible());
      const bounds = await workspace.locator('#petit-work-details').boundingBox();
      const railBounds = await workspace.locator('.petit-area-rail').boundingBox();
      await workspace.screenshot({ path: path.join(root, `desktop/dist/smoke-v27-work-${suffix}.png`) });
      assert.ok(bounds.x >= (railBounds ? railBounds.x + railBounds.width : 0), `work details clear the left menu: ${JSON.stringify({ bounds, railBounds })}`);
      await workspace.locator('#petit-context-bar').press('Escape');
      await workspace.evaluate(() => {
        const messages = document.getElementById('messages');
        for (let index = 0; index < 70; index++) {
          const bubble = document.createElement('div'); bubble.className = 'message message--assistant';
          bubble.textContent = `会話のスクロール確認 ${index}。長い会話でも入力欄を下部に残します。`; messages.appendChild(bubble);
        }
        messages.scrollTop = 0;
      });
      const composer = await workspace.locator('#chat-form').boundingBox();
      const sessionBounds = await workspace.locator('#petit-context-bar').boundingBox();
      await workspace.locator('#messages').hover();
      await workspace.mouse.wheel(0, 600);
      await workspace.waitForFunction(() => document.getElementById('messages').scrollTop > 0);
      const afterScroll = await workspace.locator('#chat-form').boundingBox();
      for (const key of ['x', 'y', 'width', 'height']) assert.ok(Math.abs(afterScroll[key] - composer[key]) <= 1, 'scroll keeps composer in place within one CSS pixel');
      assert.deepEqual(await workspace.locator('#petit-context-bar').boundingBox(), sessionBounds, 'scroll keeps session header in place');
      const dimensions = await workspace.evaluate(() => ({ height: innerHeight, width: innerWidth, scroll: document.scrollingElement.scrollTop }));
      assert.ok(composer.y + composer.height <= dimensions.height && composer.x >= 0 && composer.x + composer.width <= dimensions.width);
      assert.equal(dimensions.scroll, 0, 'only messages scroll');
      const utility = await workspace.locator('.petit-utility-dock').boundingBox();
      if (utility) assert.ok(utility.y + utility.height < composer.y, 'mobile utility buttons do not cover chat input');
      await workspace.locator('#chat-input').fill('スクロール後も書ける下書き');
      await workspace.screenshot({ path: path.join(root, `desktop/dist/smoke-v27-chat-${suffix}.png`) });
      await workspace.evaluate(() => window.PetitAppShell.activateView('tasks'));
      assert.equal(await workspace.locator('#detail-panel').isVisible(), false);
      await workspace.evaluate(() => window.PetitAppShell.activateView('chat'));
      assert.equal(await workspace.locator('#chat-input').inputValue(), 'スクロール後も書ける下書き');
    };
    await checkChatViewport('desktop');
    const checkStatsViewport = async (suffix) => {
      await workspace.evaluate(() => window.PetitAppShell.activateView('stats'));
      await workspace.waitForFunction(() => document.getElementById('today-total').textContent === '2時間30分' && document.querySelectorAll('.stats-week-column').length === 7);
      assert.equal(await workspace.locator('#today-session-count').textContent(), '3');
      assert.equal(await workspace.locator('#today-task-count').textContent(), '2');
      assert.equal(await workspace.locator('#today-longest').textContent(), '1時間0分');
      assert.equal(await workspace.locator('#stats-week-total').textContent(), '7日間で 6時間10分');
      assert.deepEqual(await workspace.locator('.stats-task-bar').evaluateAll(bars => bars.map(bar => bar.style.width)), ['80%', '20%']);
      assert.equal(await workspace.locator('.stats-week-column').first().locator('.stats-week-bar').evaluate(bar => bar.style.height), '0%');
      assert.equal(await workspace.locator('.stats-session-row').first().locator('.stats-session-time').textContent(), '10:00〜11:00');
      assert.equal(await workspace.locator('.stats-task-label strong').nth(1).textContent(), '振り返り <メモ>');
      assert.equal(await workspace.locator('.stats-task-label img').count(), 0);
      assert.ok(await workspace.locator('[data-shell-area="stats"]').evaluate(button => button.getAttribute('aria-current') === 'page'));
      assert.ok(await workspace.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'statistics fit the viewport');
      const chartBounds = await workspace.locator('#stats-week-chart').boundingBox();
      assert.ok(chartBounds.x >= 0 && chartBounds.x + chartBounds.width <= await workspace.evaluate(() => innerWidth));
      await workspace.screenshot({ path: path.join(root, `desktop/dist/smoke-statistics-${suffix}.png`), fullPage: true });
      await workspace.locator('.stats-week-column').nth(5).click();
      await workspace.waitForFunction(() => document.getElementById('today-total').textContent === '30分');
      assert.equal(await workspace.locator('#stats-date').inputValue(), '2026-10-12');
      assert.equal(await workspace.locator('.stats-task-label strong').textContent(), '前日の仕上げ');
      assert.equal(await workspace.locator('.stats-now').isVisible(), false);
      await workspace.locator('#stats-reflection-note').fill('仕上げが進んだ <script>');
      await workspace.locator('#refresh-today').click();
      await workspace.waitForFunction(() => !document.getElementById('refresh-today').disabled);
      assert.equal(await workspace.locator('#stats-reflection-note').inputValue(), '仕上げが進んだ <script>', 'polling preserves unsaved reflection');
      await workspace.locator('#stats-go-today').click();
      await workspace.waitForFunction(() => document.getElementById('today-total').textContent === '2時間30分');
      await workspace.locator('.stats-week-column').nth(5).click();
      await workspace.waitForFunction(() => document.getElementById('today-total').textContent === '30分');
      assert.equal(await workspace.locator('#stats-reflection-note').inputValue(), '仕上げが進んだ <script>', 'date switching preserves draft');
      reflectionConflict = true;
      await workspace.locator('#stats-reflection-save').click();
      await workspace.waitForFunction(() => document.getElementById('stats-reflection-state').textContent.includes('入力はこの画面に残っています'));
      assert.equal(await workspace.locator('#stats-reflection-note').inputValue(), '仕上げが進んだ <script>');
      await workspace.locator('#refresh-today').click();
      await workspace.waitForFunction(() => !document.getElementById('refresh-today').disabled);
      assert.ok((await workspace.locator('#stats-reflection-state').textContent()).includes('入力はこの画面に残っています'), 'refresh does not hide save failures');
      reflectionConflict = false;
      await workspace.locator('#stats-reflection-save').click();
      await workspace.waitForFunction(() => document.getElementById('stats-reflection-state').textContent === '振り返りを保存しました。');
      await workspace.locator('#stats-go-today').click();
      await workspace.waitForFunction(() => document.getElementById('today-total').textContent === '2時間30分');
      await workspace.locator('#stats-date').fill('2026-10-12');
      await workspace.locator('#stats-date').dispatchEvent('change');
      await workspace.waitForFunction(() => document.getElementById('today-total').textContent === '30分');
      assert.equal(await workspace.locator('#stats-reflection-note').inputValue(), '仕上げが進んだ <script>');
      await workspace.locator('#stats-go-today').click();
      await workspace.waitForFunction(() => document.getElementById('today-total').textContent === '2時間30分');
      await workspace.evaluate(() => window.PetitAppShell.activateView('univ'));
      await workspace.waitForFunction(() => !window.__fixtureScene.renderFrame);
      assert.equal(await workspace.evaluate(() => scrollY), 0);
      const hud = await workspace.locator('.univ-hud__selection').boundingBox();
      const sessionBar = await workspace.locator('#petit-context-bar').boundingBox();
      assert.ok(hud.y >= sessionBar.y + sessionBar.height, 'HUD clears session bar after statistics scrolling');
      await workspace.evaluate(() => window.PetitAppShell.activateView('stats'));
      await workspace.waitForFunction(() => document.getElementById('today-total').textContent === '2時間30分');
      statsFailure = 'summary';
      await workspace.locator('#refresh-today').click();
      await workspace.waitForFunction(() => document.getElementById('stats-week-state').textContent.includes('前回のグラフ'));
      assert.equal(await workspace.locator('#today-total').textContent(), '2時間30分', 'weekly failure preserves available today summary');
      statsFailure = 'today';
      await workspace.locator('#refresh-today').click();
      await workspace.waitForFunction(() => document.getElementById('stats-load-state').textContent.includes('前回の表示'));
      statsFailure = ''; statsEmpty = true;
      await workspace.locator('#refresh-today').click();
      await workspace.waitForFunction(() => document.getElementById('today-total').textContent === '0分');
      assert.equal(await workspace.locator('.stats-task-bar').count(), 0);
      assert.ok(await workspace.locator('#today-message').textContent().then(copy => copy.includes('記録はまだありません')));
      assert.equal(await workspace.locator('.stats-week-bar').evaluateAll(bars => bars.every(bar => bar.style.height === '0%')), true);
      await workspace.screenshot({ path: path.join(root, `desktop/dist/smoke-statistics-empty-${suffix}.png`), fullPage: true });
      statsEmpty = false;
      await workspace.locator('#refresh-today').click();
      await workspace.waitForFunction(() => document.getElementById('today-total').textContent === '2時間30分');
      await workspace.evaluate(() => window.PetitAppShell.activateView('tasks'));
      const beforeInactive = calls.filter(call => ['/api/work-sessions/today', '/api/work-sessions/summary'].includes(call.path)).length;
      await workspace.waitForTimeout(suffix === 'desktop' ? 9000 : 200);
      assert.equal(calls.filter(call => ['/api/work-sessions/today', '/api/work-sessions/summary'].includes(call.path)).length, beforeInactive, 'statistics navigation does not fetch while another tab is visible');
    };
    await checkStatsViewport('desktop');
    const originalSize = await workspace.evaluate(() => ({ width: innerWidth, height: innerHeight }));
    await workspace.evaluate(() => window.dispatchEvent(new CustomEvent('petit:navigate', { detail: { view: 'univ' } })));
    await workspace.evaluate(() => document.activeElement?.blur());
    const sizeWorkspace = ({ BrowserWindow }, size) => {
      const win = BrowserWindow.getAllWindows().find(candidate => candidate.webContents.getURL().includes('/static/universe.html'));
      win.setMinimumSize(320, 400); win.setContentSize(size.width, size.height);
    };
    await instance.evaluate(sizeWorkspace, { width: 960, height: 740 });
    await workspace.mouse.move(500, 300); await railWidth(72);
    assert.equal(await rail.isVisible(), true);
    await instance.evaluate(sizeWorkspace, { width: 390, height: 780 });
    await workspace.waitForFunction(() => innerWidth === 390);
    assert.equal(await rail.isVisible(), false, 'mobile keeps the existing navigation instead of a sidebar');
    await workspace.waitForTimeout(220);
    await workspace.screenshot({ path: path.join(root, 'desktop/dist/smoke-rail-mobile.png') });
    await checkChatViewport('mobile');
    await checkStatsViewport('mobile');
    await workspace.evaluate(() => window.PetitAppShell.activateView('chat'));
    await workspace.locator('#petit-context-bar > summary').click();
    await workspace.locator('#work-session-end').click();
    await workspace.waitForFunction(() => document.getElementById('petit-context-session').textContent === '作業なし');
    assert.equal(await workspace.locator('#petit-work-details .focus-footer').isVisible(), false);
    assert.equal(await workspace.locator('#petit-work-start-link').isVisible(), true);
    await workspace.locator('#petit-work-start-link').click();
    assert.ok(await workspace.locator('[data-view-panel="tasks"]').isVisible());
    await workspace.reload();
    await workspace.waitForFunction(() => document.getElementById('petit-context-session')?.textContent === '作業なし');
    await instance.evaluate(sizeWorkspace, originalSize);
    await workspace.close();
    // Renderer crash is distinguished from an unavailable server; draft survives.
    await voicePage.locator('#input').fill('クラッシュをまたぐ下書き');
    const crashRecoveryOpened = instance.waitForEvent('window');
    await instance.evaluate(({ BrowserWindow }) => {
      BrowserWindow.getAllWindows().find(win => win.webContents.getURL().includes('/static/desktop/index.html')).webContents.forcefullyCrashRenderer();
    });
    const crashRecovery = await crashRecoveryOpened;
    await crashRecovery.waitForURL(/recovery.html$/);
    await crashRecovery.getByText('画面を再び開けます', { exact: true }).waitFor();
    assert.equal(await crashRecovery.evaluate(() => typeof window.petitDesktop), 'undefined');
    const resumedOpened = instance.waitForEvent('window');
    await crashRecovery.locator('#retry').click();
    const resumed = await resumedOpened;
    await resumed.waitForURL(`${origin}/static/desktop/index.html`);
    assert.equal(await resumed.locator('#input').inputValue(), 'クラッシュをまたぐ下書き');
    const reconnectSettingsOpened = instance.waitForEvent('window');
    await resumed.locator('#desktop-settings').click();
    const reconnectSettings = await reconnectSettingsOpened;
    await reconnectSettings.waitForURL(/setup.html$/);
    serveOverlay = false;
    const incompatibleOverlayOpened = instance.waitForEvent('window');
    await reconnectSettings.locator('button[type=submit]').click();
    const incompatibleOverlay = await incompatibleOverlayOpened;
    const recovery = await instance.waitForEvent('window', { timeout: 15000, predicate: (candidate) => candidate !== incompatibleOverlay });
    await recovery.waitForURL(/recovery.html$/);
    await recovery.getByText('PETITに接続できません', { exact: true }).waitFor();
    assert.equal(await recovery.locator('#server').textContent(), origin);
    await recovery.waitForTimeout(350);
    await recovery.screenshot({ path: path.join(root, 'desktop/dist/smoke-recovery.png') });
    serveOverlay = true;
    const recoveredOpened = instance.waitForEvent('window');
    await recovery.locator('#retry').click();
    const recovered = await recoveredOpened;
    await recovered.waitForURL(`${origin}/static/desktop/index.html`);
    assert.equal(await recovered.locator('#input').inputValue(), 'クラッシュをまたぐ下書き');
    assert.deepEqual(errors, []);
    console.log('PASS: isolated Electron task second-click/HUD/edit/start placement, calendar statistics/reflection save/draft/conflict, tab readiness after 9 seconds, responsive HUD/workbar, existing WebGL/chat/voice/recovery regressions.');
    console.log(`Screenshot: ${screenshot}`);
  } finally {
    if (instance) await instance.close();
    server.closeAllConnections(); await new Promise((resolve) => server.close(resolve));
    fs.rmSync(profile, { recursive: true, force: true });
  }
})().catch((error) => { console.error(error); process.exitCode = 1; });
