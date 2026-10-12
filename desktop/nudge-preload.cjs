'use strict';
const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('petitNudge', {
  read: () => ipcRenderer.invoke('nudge:read'),
  open: () => ipcRenderer.invoke('nudge:open'),
  dismiss: () => ipcRenderer.invoke('nudge:dismiss'),
  hover: (value) => ipcRenderer.invoke('nudge:hover', value),
});
