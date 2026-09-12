const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const fsp = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');
const vm = require('node:vm');

async function harness(t, initialConfig, { prepareWakeEnvironment } = {}) {
  const directory = await fsp.mkdtemp(path.join(os.tmpdir(), 'petit-settings-test-'));
  t.after(() => fsp.rm(directory, { recursive: true, force: true }));
  const configFile = path.join(directory, 'desktop.json');
  await fsp.writeFile(configFile, JSON.stringify(initialConfig));
  const handlers = new Map();
  const progress = [];
  const { pathToFileURL } = require('node:url');
  const frame = { url: pathToFileURL(path.resolve(__dirname, '../setup.html')).href };
  const window = { isDestroyed: () => false, webContents: { mainFrame: frame, send: (_channel, message) => progress.push(message) } };
  const event = { sender: window.webContents, senderFrame: frame };
  const electron = {
    app: { getVersion: () => '0.20.3', getPath: () => directory },
    ipcMain: { handle: (name, handler) => handlers.set(name, handler) },
  };
  const context = vm.createContext({
    require: (name) => {
      if (name === 'electron') return electron;
      if (name === './wake-auto-setup.cjs' && prepareWakeEnvironment) return { prepareWakeEnvironment };
      return name.startsWith('./') ? require(path.join(__dirname, '..', name)) : require(name);
    },
    __dirname: path.resolve(__dirname, '..'),
    process: { platform: 'darwin', arch: 'arm64', env: {}, resourcesPath: '' },
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
    progress,
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

test('openWakeWord setup IPC is registered without old Picovoice console IPC', async (t) => {
  const h = await harness(t, { serverUrl: 'http://127.0.0.1:8000' });
  assert.equal(h.handlers.has('settings:wake-setup'), true);
  assert.equal(h.handlers.has('settings:wake-cancel'), true);
  assert.equal(h.handlers.has('settings:console'), false);
  assert.equal(h.handlers.has('settings:read'), true);
  assert.equal(h.handlers.has('settings:model'), true);
  assert.equal(h.handlers.has('settings:save'), true);
});

test('automatic setup persists managed openWakeWord paths after diagnostic', async (t) => {
  const managed = {
    pythonPath: '/managed/.venv/bin/python3',
    runtimePath: '/app/runtime.py',
    modelPath: '/managed/models/hey_petit.onnx',
    backbonePath: '/managed/backbone',
  };
  const h = await harness(t, { serverUrl: 'http://127.0.0.1:8000' }, {
    prepareWakeEnvironment: async ({ report }) => { report('diagnostic'); return managed; },
  });
  const result = await h.call('settings:wake-setup');
  assert.equal(result.ok, true);
  assert.equal(result.modelPath, managed.modelPath);
  assert.deepEqual(h.progress, ['diagnostic']);
  const persisted = JSON.parse(await fsp.readFile(h.configFile, 'utf8'));
  assert.equal(persisted.modelPath, managed.modelPath);
  assert.equal(persisted.backbonePath, managed.backbonePath);
  assert.equal(persisted.wakePythonPath, managed.pythonPath);
  assert.equal('wakeRuntimePath' in persisted, false);
});
