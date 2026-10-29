const { test } = require('node:test');
const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { isCoreSetup } = require('../policy.cjs');

test('Core login page is ready without granting the workspace IPC bridge', () => {
  const source = fs.readFileSync(path.join(__dirname, '../main.cjs'), 'utf8');
  const implementation = source.slice(source.indexOf('function watchClient('), source.indexOf('function showWorkspace('));
  const win = new EventEmitter(); win.webContents = new EventEmitter();
  win.webContents.getURL = () => 'https://petit.example/static/setup.html';
  win.isDestroyed = () => false;
  let timer = false;
  const sandbox = { quitting: false, workspace: win, overlay: null, config: { serverUrl: 'https://petit.example' }, isCoreSetup,
    setTimeout: () => { timer = true; }, clearTimeout: () => {}, showRecovery: () => assert.fail('login is not a connection failure') };
  vm.runInNewContext(implementation + '\nwatchClient(workspace, "workspace");', sandbox);
  win.webContents.emit('did-finish-load');
  assert.equal(win.petitReady, true); assert.equal(timer, false);
});

test('history/tab changes retain ready state; a new document still requires readiness', () => {
  const source = fs.readFileSync(path.join(__dirname, '../main.cjs'), 'utf8');
  const implementation = source.slice(source.indexOf('function watchClient('), source.indexOf('function showWorkspace('));
  const win = new EventEmitter();
  win.webContents = new EventEmitter();
  win.petitReady = true;
  let destroyed = false;
  win.isDestroyed = () => destroyed;
  win.destroy = () => { destroyed = true; win.emit('closed'); };
  const timers = new Set();
  const recovery = [];
  const sandbox = { quitting: false, workspace: win, overlay: null,
    setTimeout: callback => { timers.add(callback); return callback; },
    clearTimeout: callback => timers.delete(callback),
    showRecovery: (...args) => recovery.push(args) };
  vm.runInNewContext(implementation + '\nwatchClient(workspace, "workspace");', sandbox);
  const finish = () => { for (const callback of [...timers]) callback(); timers.clear(); };
  win.webContents.emit('did-start-navigation', { isMainFrame: true, isSameDocument: true });
  win.webContents.emit('did-start-loading');
  win.webContents.emit('did-finish-load');
  finish();
  assert.equal(win.petitReady, true);
  assert.equal(destroyed, false);
  win.webContents.emit('did-start-navigation', { isMainFrame: false, isSameDocument: false });
  assert.equal(win.petitReady, true);
  win.webContents.emit('did-start-navigation', { isMainFrame: true, isSameDocument: false });
  assert.equal(win.petitReady, false);
  win.webContents.emit('did-finish-load');
  finish();
  assert.equal(destroyed, true);
  assert.deepEqual(recovery, [['workspace', 'connection']]);
});
