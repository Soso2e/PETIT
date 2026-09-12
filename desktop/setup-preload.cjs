'use strict';
const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('petitSettings', {
  read: () => ipcRenderer.invoke('settings:read'),
  save: (values) => ipcRenderer.invoke('settings:save', values),
  selectModel: (kind) => ipcRenderer.invoke('settings:model', kind),
  autoSetup: () => ipcRenderer.invoke('settings:wake-setup'),
  cancelSetup: () => ipcRenderer.invoke('settings:wake-cancel'),
  onProgress: (callback) => {
    const listener = (_event, message) => callback(message);
    ipcRenderer.on('settings:wake-progress', listener);
    return () => ipcRenderer.removeListener('settings:wake-progress', listener);
  },
  checkUpdates: () => ipcRenderer.invoke('settings:updates'),
});
