'use strict';
const { contextBridge, ipcRenderer } = require('electron');

const subscribe = (channel) => (callback) => {
  const listener = (_event, value) => callback(value);
  ipcRenderer.on(channel, listener);
  return () => ipcRenderer.removeListener(channel, listener);
};
contextBridge.exposeInMainWorld('petitPet', {
  open: () => ipcRenderer.invoke('pet:open'),
  hide: () => ipcRenderer.invoke('pet:hide'),
  onMode: subscribe('pet:mode'),
  onEvent: subscribe('pet:event'),
  onAppearance: subscribe('pet:appearance'),
  onWalk: subscribe('pet:walk'),
});
