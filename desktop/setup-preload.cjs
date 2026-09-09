'use strict';
const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('petitSettings', {
  autoSetup: (values) => ipcRenderer.invoke('settings:wake-setup', values),
  cancelSetup: () => ipcRenderer.invoke('settings:wake-cancel'),
  openConsole: () => ipcRenderer.invoke('settings:console'),
  onProgress: (callback) => {
    const listener = (_event, message) => callback(message);
    ipcRenderer.on('settings:wake-progress', listener);
    return () => ipcRenderer.removeListener('settings:wake-progress', listener);
  },
  read: () => ipcRenderer.invoke('settings:read'),
  save: (values) => ipcRenderer.invoke('settings:save', values),
  selectModel: (kind) => ipcRenderer.invoke('settings:model', kind),
  checkUpdates: () => ipcRenderer.invoke('settings:updates'),
});
