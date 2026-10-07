'use strict';
const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('petitRecovery', {
  read: () => ipcRenderer.invoke('recovery:read'),
  retry: () => ipcRenderer.invoke('recovery:retry'),
  settings: () => ipcRenderer.invoke('recovery:settings'),
});
