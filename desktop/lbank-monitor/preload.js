const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('NexusNative', {
  isAvailable: () => true,
  hasKey: id => ipcRenderer.sendSync('nexus:has-key', String(id)),
  saveKey: (id, value) => ipcRenderer.sendSync('nexus:save-key', String(id), String(value || '')),
  deleteKey: id => ipcRenderer.sendSync('nexus:delete-key', String(id)),
  request: (id, requestJson) => ipcRenderer.invoke('nexus:request', String(requestJson)).then(
    value => window.NexusNativeResult(String(id), true, String(value)),
    error => window.NexusNativeResult(String(id), false, error?.message || String(error))
  )
});
