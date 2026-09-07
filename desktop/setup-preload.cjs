'use strict';
const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('petitSettings', {
  read: () => ipcRenderer.invoke('settings:read'),
  save: (values) => ipcRenderer.invoke('settings:save', values),
  selectModel: (kind) => ipcRenderer.invoke('settings:model', kind),
  checkUpdates: () => ipcRenderer.invoke('settings:updates'),
});
