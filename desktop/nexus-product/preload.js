const { contextBridge, ipcRenderer } = require('electron');

const CHANNELS = Object.freeze({
  get: 'nexus:ui-preferences:get',
  set: 'nexus:ui-preferences:set',
  reset: 'nexus:ui-preferences:reset',
});

contextBridge.exposeInMainWorld('nexusDesktop', Object.freeze({
  getPreferences: () => ipcRenderer.invoke(CHANNELS.get),
  setPreferences: preferences => ipcRenderer.invoke(CHANNELS.set, preferences),
  resetPreferences: () => ipcRenderer.invoke(CHANNELS.reset),
}));
