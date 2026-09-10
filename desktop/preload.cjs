'use strict';
const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('petitDesktop', {
  hide: () => ipcRenderer.invoke('desktop:hide'),
  openWeb: () => ipcRenderer.invoke('desktop:open-web'),
  settings: () => ipcRenderer.invoke('desktop:settings'),
  transcribe: (wav) => ipcRenderer.invoke('desktop:transcribe', wav),
  cancel: () => ipcRenderer.invoke('desktop:cancel'),
  ready: () => ipcRenderer.invoke('desktop:ready'),
  onActivate: (callback) => {
    const listener = (_event, detail) => callback(detail);
    ipcRenderer.on('desktop:activate', listener);
    return () => ipcRenderer.removeListener('desktop:activate', listener);
  },
  onHide: (callback) => {
    const listener = () => callback();
    ipcRenderer.on('desktop:hidden', listener);
    return () => ipcRenderer.removeListener('desktop:hidden', listener);
  },
});
