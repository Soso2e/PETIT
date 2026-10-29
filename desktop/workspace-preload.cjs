'use strict';
const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('petitCoreSetup', { openWeb: () => ipcRenderer.invoke('core-setup:open-web') });
contextBridge.exposeInMainWorld('petitWorkspace', { desktop: true });
contextBridge.exposeInMainWorld('petitNotifications', {
  read: () => ipcRenderer.invoke('workspace:notifications-read'),
  enable: (value) => ipcRenderer.invoke('workspace:notifications-enable', value),
  test: () => ipcRenderer.invoke('workspace:notifications-test'),
});
window.addEventListener('DOMContentLoaded', () => {
  if (!document.querySelector('.universe-shell')) return;
  const toolbar = document.createElement('nav');
  toolbar.id = 'petit-desktop-toolbar'; toolbar.setAttribute('aria-label', 'Desktop操作');
  for (const [label, channel] of [['小型会話', 'workspace:chat'], ['Desktop設定', 'workspace:settings']]) {
    const button = document.createElement('button');
    button.textContent = label; button.type = 'button';
    button.addEventListener('click', () => void ipcRenderer.invoke(channel)); toolbar.appendChild(button);
  }
  document.body.prepend(toolbar);
  // The full workspace uses the same small-window STT adapter and permission boundary.
  document.addEventListener('click', (event) => {
    if (!event.target.closest?.('#mic')) return;
    event.preventDefault(); event.stopImmediatePropagation();
    void ipcRenderer.invoke('workspace:voice');
  }, true);
  void ipcRenderer.invoke('workspace:ready');
});
