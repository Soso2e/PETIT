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
  // The full workspace uses the same small-window STT adapter and permission boundary.
  document.addEventListener('click', (event) => {
    if (!event.target.closest?.('#mic')) return;
    event.preventDefault(); event.stopImmediatePropagation();
    void ipcRenderer.invoke('workspace:voice');
  }, true);
  void ipcRenderer.invoke('workspace:ready');
});
