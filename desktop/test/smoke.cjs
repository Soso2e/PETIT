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
  { id: 1, title: '作業中の星', status: 'Yet', priority: 'High', source: 'notion', external_id: 'fixture-1', sync_status: 'conflict', root_task_id: 1, root_title: '作業中の星' },
  { id: 2, title: '選択だけの星', status: 'Yet', priority: 'High', source: 'notion', external_id: 'fixture-2', sync_status: 'synced', root_task_id: 2, root_title: '選択だけの星' },
];
let fixturePreferences = { work_session: false };
const mime = { '.html': 'text/html', '.js': 'application/javascript', '.css': 'text/css' };
const server = http.createServer(async (request, response) => {
  const url = new URL(request.url, 'http://localhost');
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
    await workspace.getByRole('button', { name: '同期競合を確認', exact: true }).click();
    await workspace.locator('.task-conflict-dialog').getByRole('button', { name: '作業中の星', exact: true }).click();
    await workspace.locator('.task-conflict-dialog table').waitFor();
    await workspace.waitForFunction(() => getComputedStyle(document.querySelector('.task-conflict-dialog')).opacity === '1');
    await workspace.screenshot({ path: path.join(root, 'desktop/dist/smoke-conflict.png') });
    await workspace.getByRole('button', { name: 'PETIT側を残して再同期', exact: true }).click();
    await workspace.getByText('PETIT側の変更を再同期します。まだNotionへの反映は完了していません。', { exact: true }).waitFor();
    await workspace.locator('.task-conflict-dialog').getByRole('button', { name: '閉じる', exact: true }).click();
    await workspace.evaluate(() => window.dispatchEvent(new CustomEvent('petit:navigate', { detail: { view: 'settings' } })));
    await workspace.locator('#notification-enable').click();
    await workspace.locator('#notification-disable').waitFor({ state: 'visible' });
    assert.equal(await workspace.evaluate(async () => (await window.petitNotifications.read()).enabled), true, 'Desktop enables without VAPID');
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
    await workspace.locator('#petit-context-bar > summary').click();
    await workspace.locator('#work-session-end').click();
    await workspace.waitForFunction(() => document.getElementById('petit-context-session').textContent === '作業なし');
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
    console.log('PASS: isolated Electron chat/approval/synthetic voice, v27 compact session/dropdown, fixed chat input and message scrolling, actual WebGL work glow/middle pan, voice options, 960/390px layouts, compact/hover/pinned rail, conflicts, notifications, recovery and IPC isolation.');
    console.log(`Screenshot: ${screenshot}`);
  } finally {
    if (instance) await instance.close();
    server.closeAllConnections(); await new Promise((resolve) => server.close(resolve));
    fs.rmSync(profile, { recursive: true, force: true });
  }
})().catch((error) => { console.error(error); process.exitCode = 1; });
