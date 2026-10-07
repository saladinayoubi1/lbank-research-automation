'use strict';
const path = require('node:path');
const { createChatGPTBridge, safeCode, USAGE_URL } = require('./chatgpt-bridge');

function credentialEncryption(storage, isReady, platform = process.platform) {
  const available = () => Boolean(isReady() && storage?.isEncryptionAvailable() &&
    (platform !== 'linux' || ['gnome_libsecret', 'kwallet', 'kwallet5', 'kwallet6'].includes(storage.getSelectedStorageBackend())));
  const requireAvailable = () => { if (!available()) { const e = new Error('storage_unavailable'); e.code = 'storage_unavailable'; throw e; } };
  return { id: 'electron-safe-storage-v1', isAvailable: available,
    encrypt: plaintext => { requireAvailable(); return storage.encryptString(plaintext); },
    decrypt: ciphertext => { requireAvailable(); return storage.decryptString(Buffer.from(ciphertext)); } };
}

function trustedSender(event, origin, BrowserWindow) {
  if (!origin || !event?.senderFrame || event.senderFrame !== event.sender?.mainFrame) return false;
  const win = BrowserWindow.fromWebContents(event.sender);
  if (!win || win.isDestroyed()) return false;
  try {
    const url = new URL(event.senderFrame.url);
    return url.origin === origin && url.pathname === '/' && !url.username && !url.password;
  } catch { return false; }
}

function registerChatGPTIpc({ app, BrowserWindow, ipcMain, safeStorage, shell, getOrigin }) {
  const encryption = credentialEncryption(safeStorage, () => app.isReady());
  let client = null;
  const getClient = async () => {
    if (!encryption.isAvailable()) { const e = new Error('storage_unavailable'); e.code = 'storage_unavailable'; throw e; }
    if (!client) {
      const { createChatGPT } = require('./chatgpt-sdk.cjs');
      client = createChatGPT({ appName: 'NEXUS Personal Pro', appId: 'nexus-personal-pro',
        redirectPort: 0, sendHostId: true, storageDir: path.join(app.getPath('userData'), 'chatgpt'),
        credentialEncryption: encryption,
        openBrowser: async raw => {
          const url = new URL(raw);
          if (url.origin !== 'https://auth.openai.com' || url.pathname !== '/api/accounts/authorize' ||
              url.username || url.password || url.hash) throw new Error('Invalid OAuth destination');
          await shell.openExternal(url.href);
        } });
    }
    return client;
  };
  const postBackend = async (route, payload) => {
    const origin = getOrigin();
    if (!/^http:\/\/127\.0\.0\.1:\d+$/.test(origin || '')) throw Object.assign(new Error(), { code: 'gateway_unavailable' });
    const response = await fetch(origin + route, { method: 'POST', headers: { 'Content-Type': 'application/json', Origin: origin },
      body: JSON.stringify(payload), signal: AbortSignal.timeout(15000), redirect: 'error' });
    const body = await response.text();
    if (Buffer.byteLength(body) > 100000) throw Object.assign(new Error(), { code: 'gateway_unavailable' });
    const result = JSON.parse(body);
    if (!response.ok) throw Object.assign(new Error(), { code: result.error?.code ||
      (typeof result.error === 'string' ? result.error : 'gateway_unavailable') });
    return result;
  };
  const bridge = createChatGPTBridge({ getClient, postBackend, encryptionAvailable: encryption.isAvailable });
  const actions = { status: bridge.status, connect: bridge.connect, disconnect: bridge.disconnect,
    models: bridge.refreshModels, ask: bridge.ask, cancel: bridge.cancel,
    usage: async () => { await shell.openExternal(USAGE_URL); return {}; } };
  for (const [name, action] of Object.entries(actions)) {
    ipcMain.handle('nexus:chatgpt:' + name, async (event, ...args) => {
      if (!trustedSender(event, getOrigin(), BrowserWindow)) return { ok: false, error: { code: 'untrusted_sender' } };
      if (args.length !== (name === 'ask' ? 1 : 0)) return { ok: false, error: { code: 'invalid_request' } };
      try { return { ok: true, value: await action(...args) }; }
      catch (e) { return { ok: false, error: { code: safeCode(e) } }; }
    });
  }
  app.on('before-quit', () => { bridge.close(); client?.cancelSignIn(); });
  return bridge;
}
module.exports = { registerChatGPTIpc, credentialEncryption, trustedSender };
