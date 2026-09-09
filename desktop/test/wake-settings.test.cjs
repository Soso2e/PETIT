const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const fsp = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');
const vm = require('node:vm');
const { EventEmitter } = require('node:events');
const setup = require('../wake-setup.cjs');
async function harness(t, { permission = 'granted', secure = true, detection = true } = {}) {
  const directory = await fsp.mkdtemp(path.join(os.tmpdir(), 'petit-settings-test-'));
  t.after(() => fsp.rm(directory, { recursive: true, force: true }));
  const handlers = new Map(); const progress = [];
  const { pathToFileURL } = require('node:url');
  const frame = { url: pathToFileURL(path.resolve(__dirname, '../setup.html')).href };
  const window = { isDestroyed: () => false, webContents: { mainFrame: frame, send: (_channel, message) => progress.push(message) } };
  const event = { sender: window.webContents, senderFrame: frame };
  let acquisitions = 0, stopped = 0;
  const electron = {
    app: { getPath: () => directory, getVersion: () => '0.20.0' },
    ipcMain: { handle: (name, handler) => handlers.set(name, handler) },
    safeStorage: { isEncryptionAvailable: () => secure, encryptString: () => Buffer.from('ciphertext'), decryptString: () => 'SECRET' },
    systemPreferences: { getMediaAccessStatus: () => permission },
    utilityProcess: { fork: () => {
      const worker = new EventEmitter(); worker.kill = () => { stopped++; };
      worker.postMessage = () => { worker.emit('message', { type: 'ready' }); if (detection) worker.emit('message', { type: 'wake' }); };
      queueMicrotask(() => worker.emit('spawn'));
      return worker;
    } },
  };
  const context = vm.createContext({
    require: (name) => name === 'electron' ? electron : name === './wake-setup.cjs' ? { ...setup, prepareModels: async () => {
      acquisitions++;
      const staging = path.join(directory, 'stage'); await fsp.mkdir(staging);
      return { staging, keywordPath: path.join(staging, 'test.ppn'), modelPath: path.join(staging, 'ja.pv'), metadata: {} };
    } } : name.startsWith('./') ? require(path.join(__dirname, '..', name)) : require(name),
    __dirname: path.resolve(__dirname, '..'), process: { platform: 'darwin', arch: 'arm64', env: {} },
    Buffer, AbortController, setTimeout, clearTimeout, fixtureWindow: window, fixtureDirectory: directory,
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../main.cjs'), 'utf8').split('if (!app.requestSingleInstanceLock())')[0] + `
    configFile = require('node:path').join(fixtureDirectory, 'desktop.json');
    config = { ...defaults, keywordPath: '/old.ppn', modelPath: '/old.pv' };
    settingsWindow = fixtureWindow;
    installIpc();`, context);
  return { call: (name, values) => handlers.get(name)(event, values), directory, context, acquisitions: () => acquisitions, stopped: () => stopped, progress };
}
test('automatic settings persist encrypted key and commit model paths only after detection', async (t) => {
  const h = await harness(t);
  const result = await h.call('settings:wake-setup', { key: 'SECRET' });
  assert.equal(result.ok, true);
  assert.match(result.message, /準備完了/);
  assert.equal(h.stopped(), 1);
  const raw = await fsp.readFile(path.join(h.directory, 'desktop.json'), 'utf8');
  assert.equal(raw.includes('SECRET'), false);
  assert.equal(JSON.parse(raw).keywordPath, result.keywordPath);
});
test('missing key, unsafe storage and denied microphone never acquire models', async (t) => {
  for (const settings of [{}, { secure: false }, { permission: 'denied' }]) {
    const h = await harness(t, settings);
    const result = await h.call('settings:wake-setup', Object.keys(settings).length ? { key: 'SECRET' } : {});
    assert.equal(result.ok, false);
    assert.equal(h.acquisitions(), 0);
    assert.equal(h.call('settings:read').keywordPath, '/old.ppn');
  }
});
test('cancellation preserves previous models and blocks concurrent setup/save', async (t) => {
  const h = await harness(t, { detection: false });
  const running = h.call('settings:wake-setup', { key: 'SECRET' });
  assert.equal((await h.call('settings:wake-setup', {})).ok, false);
  assert.throws(() => h.call('settings:save', {}), /中止/);
  await new Promise((resolve) => setImmediate(resolve));
  h.call('settings:wake-cancel');
  assert.equal((await running).ok, false);
  assert.equal(h.call('settings:read').keywordPath, '/old.ppn');
  assert.equal(fs.existsSync(path.join(h.directory, 'stage')), false);
});
