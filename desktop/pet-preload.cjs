'use strict';
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('petitPet', {
  open: () => ipcRenderer.invoke('pet:open'),
  hide: () => ipcRenderer.invoke('pet:hide'),
  onMode: (callback) => {
    const listener = (_event, mode) => callback(mode);
    ipcRenderer.on('pet:mode', listener);
    return () => ipcRenderer.removeListener('pet:mode', listener);
  },
});
