const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const fsp = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');
const vm = require('node:vm');

async function harness(t, initialConfig) {
  const directory = await fsp.mkdtemp(path.join(os.tmpdir(), 'petit-settings-test-'));
  t.after(() => fsp.rm(directory, { recursive: true, force: true }));
  const configFile = path.join(directory, 'desktop.json');
  await fsp.writeFile(configFile, JSON.stringify(initialConfig));
  const handlers = new Map();
  const { pathToFileURL } = require('node:url');
  const frame = { url: pathToFileURL(path.resolve(__dirname, '../setup.html')).href };
  const window = { isDestroyed: () => false, webContents: { mainFrame: frame } };
  const event = { sender: window.webContents, senderFrame: frame };
  const electron = {
    app: { getVersion: () => '0.20.3' },
    ipcMain: { handle: (name, handler) => handlers.set(name, handler) },
  };
  const context = vm.createContext({
    require: (name) => name === 'electron' ? electron : name.startsWith('./') ? require(path.join(__dirname, '..', name)) : require(name),
    __dirname: path.resolve(__dirname, '..'),
    process: { platform: 'darwin', arch: 'arm64', env: {} },
    Buffer, AbortController, setTimeout, clearTimeout,
    fixtureWindow: window, fixtureConfigFile: configFile,
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../main.cjs'), 'utf8').split('if (!app.requestSingleInstanceLock())')[0] + `
    configFile = fixtureConfigFile;
    config = readConfig();
    settingsWindow = fixtureWindow;
    installIpc();`, context);
  return {
    call: (name, values) => handlers.get(name)(event, values),
    handlers,
    configFile,
  };
}

test('legacy Porcupine credentials and model metadata are removed on read', async (t) => {
  const h = await harness(t, {
    serverUrl: 'http://127.0.0.1:8000',
    sttUrl: 'http://127.0.0.1:8080/inference',
    encryptedKey: 'ciphertext',
    keywordPath: '/old.ppn',
    modelPath: '/old.pv',
    wakeAuto: { sdk: '4.0.2' },
    wakeEnabled: true,
  });
  const state = h.call('settings:read');
  assert.equal(state.modelPath, '');
  assert.equal(state.wakeEnabled, false);
  assert.equal('encryptedKey' in state, false);
  assert.equal('keywordPath' in state, false);
  assert.equal('wakeAuto' in state, false);
  const persisted = JSON.parse(await fsp.readFile(h.configFile, 'utf8'));
  assert.equal('encryptedKey' in persisted, false);
  assert.equal('keywordPath' in persisted, false);
  assert.equal('wakeAuto' in persisted, false);
});

test('openWakeWord ONNX/backbone settings remain the only wake configuration', async (t) => {
  const h = await harness(t, {
    serverUrl: 'http://127.0.0.1:8000',
    sttUrl: 'http://127.0.0.1:8080/inference',
    modelPath: '/models/hey_petit.onnx',
    backbonePath: '/models/backbone',
    wakeThreshold: 0.55,
    wakeEnabled: true,
    updates: true,
  });
  const state = h.call('settings:read');
  assert.equal(state.modelPath, '/models/hey_petit.onnx');
  assert.equal(state.backbonePath, '/models/backbone');
  assert.equal(state.wakeThreshold, 0.55);
  assert.equal(state.wakeEnabled, true);
});

test('obsolete Picovoice setup IPC is no longer registered', async (t) => {
  const h = await harness(t, { serverUrl: 'http://127.0.0.1:8000' });
  assert.equal(h.handlers.has('settings:wake-setup'), false);
  assert.equal(h.handlers.has('settings:wake-cancel'), false);
  assert.equal(h.handlers.has('settings:console'), false);
  assert.equal(h.handlers.has('settings:read'), true);
  assert.equal(h.handlers.has('settings:model'), true);
  assert.equal(h.handlers.has('settings:save'), true);
});
