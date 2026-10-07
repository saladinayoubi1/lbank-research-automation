'use strict';
const path = require('node:path');
const { credentialEncryption, trustedSender } = require('./chatgpt-ipc');
const { createTradingViewBridge, safeError } = require('./tradingview-bridge');

function registerTradingViewIpc({ app, BrowserWindow, ipcMain, safeStorage, shell, getOrigin, makeBridge = createTradingViewBridge }) {
  const bridge = makeBridge({ filename: path.join(app.getPath('userData'), 'tradingview', 'oauth.enc.json'),
    encryption: credentialEncryption(safeStorage, () => app.isReady()), openBrowser: url => shell.openExternal(url) });
  for (const name of ['status', 'connect', 'disconnect', 'cancel', 'snapshot']) {
    ipcMain.handle('nexus:tradingview:' + name, async (event, ...args) => {
      if (!trustedSender(event, getOrigin(), BrowserWindow)) return { ok: false, error: { code: 'untrusted_sender' } };
      if (args.length !== (name === 'snapshot' ? 1 : 0)) return { ok: false, error: { code: 'invalid_request' } };
      try { return { ok: true, value: await bridge[name](...args) }; }
      catch (e) { return { ok: false, error: { code: safeError(e) } }; }
    });
  }
  app.on('before-quit', () => { void bridge.close(); });
  return bridge;
}
module.exports = { registerTradingViewIpc };
