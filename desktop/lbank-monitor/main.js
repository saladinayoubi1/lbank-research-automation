const { app, BrowserWindow, shell, ipcMain, safeStorage } = require('electron');
const path = require('path');
const fs = require('fs');

const GATEWAY_SECRET_ID = 'gateway';
const ALLOWED_PATHS = new Set([
  '/health',
  '/api/readiness/summary',
  '/api/readiness/series',
  '/api/mission-control',
  '/api/integrations/zotero',
  '/api/integrations/research',
]);
const MAX_RESPONSE_BYTES = 1_000_000;
const MAX_REQUEST_CHARS = 4096;

function keyFile() { return path.join(app.getPath('userData'), 'nexus-gateway-secret.json'); }
function loadKeys() { try { return JSON.parse(fs.readFileSync(keyFile(), 'utf8')); } catch { return {}; } }
function saveKeys(keys) {
  fs.mkdirSync(path.dirname(keyFile()), { recursive: true });
  fs.writeFileSync(keyFile(), JSON.stringify(keys), { mode: 0o600 });
}
function assertSecretId(id) {
  if (id !== GATEWAY_SECRET_ID) throw new Error('Only the NEXUS gateway token is accepted by this bridge');
}
function storeKey(id, value) {
  assertSecretId(id);
  const keys = loadKeys();
  if (!value) delete keys[id];
  else {
    if (!safeStorage.isEncryptionAvailable()) throw new Error('Windows secure storage is unavailable');
    keys[id] = safeStorage.encryptString(value).toString('base64');
  }
  saveKeys(keys);
}
function readKey(id) {
  assertSecretId(id);
  const packed = loadKeys()[id];
  if (!packed) return '';
  if (!safeStorage.isEncryptionAvailable()) throw new Error('Windows secure storage is unavailable');
  return safeStorage.decryptString(Buffer.from(packed, 'base64'));
}
function gatewayBaseUrl() {
  const raw = process.env.NEXUS_GATEWAY_URL || 'http://127.0.0.1:8000';
  const url = new URL(raw);
  const loopback = url.hostname === '127.0.0.1' || url.hostname === '::1' || url.hostname === 'localhost';
  if (url.username || url.password || url.search || url.hash || (url.pathname && url.pathname !== '/')) {
    throw new Error('NEXUS gateway URL must be an origin only');
  }
  if (url.protocol === 'http:' && !loopback) throw new Error('Plain HTTP gateway is allowed only on loopback');
  if (url.protocol !== 'https:' && url.protocol !== 'http:') throw new Error('Unsupported NEXUS gateway protocol');
  return url;
}
function parseGatewayRequest(requestJson) {
  if (typeof requestJson !== 'string' || requestJson.length > MAX_REQUEST_CHARS) throw new Error('Gateway request is malformed or oversized');
  const request = JSON.parse(requestJson);
  if (!request || typeof request !== 'object' || Array.isArray(request)) throw new Error('Gateway request must be an object');
  const keys = Object.keys(request).sort();
  if (keys.length !== 1 || keys[0] !== 'path') throw new Error('Only a bounded gateway path is accepted');
  if (typeof request.path !== 'string' || request.path.length > MAX_REQUEST_CHARS || request.path.includes('#')) throw new Error('Gateway path is invalid');
  const parsed = new URL(request.path, 'https://nexus.invalid');
  if (parsed.origin !== 'https://nexus.invalid') throw new Error('Absolute URLs are forbidden in renderer requests');
  if (!ALLOWED_PATHS.has(parsed.pathname)) throw new Error('Gateway route is not allowlisted');
  if (parsed.pathname !== '/api/readiness/series' && parsed.search) throw new Error('Query parameters are forbidden on this gateway route');
  const allowedQuery = new Set(['symbol', 'timeframe', 'limit', 'offset']);
  const seen = new Set();
  for (const [key, value] of parsed.searchParams.entries()) {
    if (!allowedQuery.has(key) || seen.has(key) || value.length > 160) throw new Error('Gateway query is invalid');
    seen.add(key);
  }
  return parsed.pathname + parsed.search;
}
async function callGateway(requestJson) {
  const relativePath = parseGatewayRequest(requestJson);
  const base = gatewayBaseUrl();
  const target = new URL(relativePath, base);
  if (target.origin !== base.origin) throw new Error('Gateway origin escape rejected');
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 30000);
  try {
    const headers = { accept: 'application/json' };
    if (base.protocol === 'https:') {
      const token = readKey(GATEWAY_SECRET_ID);
      if (token) headers.authorization = `Bearer ${token}`;
    }
    const response = await fetch(target, { method: 'GET', headers, signal: controller.signal, redirect: 'error', cache: 'no-store' });
    const length = Number(response.headers.get('content-length') || '0');
    if (length > MAX_RESPONSE_BYTES) throw new Error('Gateway response exceeds bounded size');
    const text = await response.text();
    if (Buffer.byteLength(text, 'utf8') > MAX_RESPONSE_BYTES) throw new Error('Gateway response exceeds bounded size');
    if (!response.ok) throw new Error(`NEXUS gateway HTTP ${response.status}`);
    const payload = JSON.parse(text);
    if (!payload || payload.contract_version !== 'nexus.dashboard.read.v1') throw new Error('Incompatible NEXUS gateway response');
    return JSON.stringify(payload);
  } finally {
    clearTimeout(timer);
  }
}

ipcMain.on('nexus:has-key', (event, id) => {
  try { assertSecretId(String(id)); event.returnValue = !!loadKeys()[GATEWAY_SECRET_ID]; }
  catch { event.returnValue = false; }
});
ipcMain.on('nexus:save-key', (event, id, value) => {
  try { storeKey(String(id), String(value || '')); event.returnValue = true; }
  catch { event.returnValue = false; }
});
ipcMain.on('nexus:delete-key', (event, id) => {
  try { storeKey(String(id), ''); event.returnValue = true; }
  catch { event.returnValue = false; }
});
ipcMain.handle('nexus:request', async (_event, requestJson) => callGateway(String(requestJson)));
ipcMain.handle('nexus:gateway-info', async () => {
  const base = gatewayBaseUrl();
  return { mode: base.protocol === 'https:' ? 'remote-or-tls-local' : 'local-loopback', origin: base.origin, readOnly: true };
});

function createWindow() {
  const window = new BrowserWindow({
    width: 1440, height: 920, minWidth: 980, minHeight: 680, show: false,
    backgroundColor: '#06101d', autoHideMenuBar: true, title: 'NEXUS Personal Pro',
    titleBarStyle: 'hidden', titleBarOverlay: { color: '#081524', symbolColor: '#eef5ff', height: 46 },
    webPreferences: { contextIsolation: true, sandbox: true, nodeIntegration: false, devTools: false, preload: path.join(__dirname, 'preload.js') }
  });
  const appRoot = app.isPackaged ? path.join(process.resourcesPath, 'app') : path.join(__dirname, 'app');
  window.loadFile(path.join(appRoot, 'index.html'));
  window.once('ready-to-show', () => window.show());
  window.webContents.setWindowOpenHandler(({ url }) => { if (/^https:\/\//i.test(url)) shell.openExternal(url); return { action: 'deny' }; });
  window.webContents.on('will-navigate', (event, url) => { if (!url.startsWith('file://')) event.preventDefault(); });
}

app.whenReady().then(() => { createWindow(); app.on('activate', () => { if (BrowserWindow.getAllWindows().length === 0) createWindow(); }); });
app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit(); });
