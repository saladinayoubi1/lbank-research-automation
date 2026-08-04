const { app, BrowserWindow, shell, ipcMain, safeStorage } = require('electron');
const path = require('path');
const fs = require('fs');

function keyFile() { return path.join(app.getPath('userData'), 'nexus-keys.json'); }
function loadKeys() { try { return JSON.parse(fs.readFileSync(keyFile(), 'utf8')); } catch { return {}; } }
function saveKeys(keys) { fs.mkdirSync(path.dirname(keyFile()), { recursive: true }); fs.writeFileSync(keyFile(), JSON.stringify(keys), { mode: 0o600 }); }
function storeKey(id, value) {
  const keys = loadKeys();
  if (!value) delete keys[id];
  else {
    if (!safeStorage.isEncryptionAvailable()) throw new Error('Windows secure storage is unavailable');
    keys[id] = safeStorage.encryptString(value).toString('base64');
  }
  saveKeys(keys);
}
function readKey(id) {
  const packed = loadKeys()[id];
  if (!packed) return '';
  if (!safeStorage.isEncryptionAvailable()) throw new Error('Windows secure storage is unavailable');
  return safeStorage.decryptString(Buffer.from(packed, 'base64'));
}
function validateUrl(raw) {
  const u = new URL(raw);
  const local = ['127.0.0.1', 'localhost'].includes(u.hostname) || u.hostname.startsWith('192.168.') || u.hostname.startsWith('10.');
  if (u.protocol !== 'https:' && !(u.protocol === 'http:' && local)) throw new Error('Only HTTPS or local-network HTTP endpoints are allowed');
  return u;
}
async function postJson(url, body, headers = {}) {
  validateUrl(url);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 90000);
  try {
    const r = await fetch(url, { method: 'POST', headers: { 'content-type': 'application/json', ...headers }, body: JSON.stringify(body), signal: controller.signal });
    const text = await r.text();
    if (!r.ok) throw new Error(`HTTP ${r.status}: ${text.slice(0, 500)}`);
    return JSON.parse(text);
  } finally { clearTimeout(timer); }
}
async function callProvider(request) {
  const p = request.provider, messages = request.messages, base = p.baseUrl.replace(/\/$/, ''), key = readKey(p.id);
  if (p.type !== 'ollama' && !key) throw new Error('API Key تنظیم نشده');
  if (p.type === 'openai-compatible') {
    const j = await postJson(base + '/chat/completions', { model: p.model, messages, temperature: 0.25 }, { authorization: 'Bearer ' + key });
    return j.choices?.[0]?.message?.content || '';
  }
  if (p.type === 'anthropic') {
    const system = messages.find(x => x.role === 'system')?.content || '';
    const j = await postJson(base + '/v1/messages', { model: p.model, max_tokens: 1800, system, messages: messages.filter(x => x.role !== 'system') }, { 'x-api-key': key, 'anthropic-version': '2023-06-01' });
    return (j.content || []).map(x => x.text || '').join('\n');
  }
  if (p.type === 'gemini') {
    const prompt = messages.map(x => `${x.role}: ${x.content}`).join('\n\n');
    const j = await postJson(`${base}/v1beta/models/${encodeURIComponent(p.model)}:generateContent?key=${encodeURIComponent(key)}`, { contents: [{ parts: [{ text: prompt }] }] });
    return j.candidates?.[0]?.content?.parts?.map(x => x.text || '').join('\n') || '';
  }
  if (p.type === 'ollama') {
    const j = await postJson(base + '/api/chat', { model: p.model, stream: false, messages });
    return j.message?.content || '';
  }
  throw new Error('نوع سرویس پشتیبانی نمی‌شود');
}

ipcMain.on('nexus:has-key', (event, id) => { event.returnValue = !!loadKeys()[id]; });
ipcMain.on('nexus:save-key', (event, id, value) => { try { storeKey(id, value); event.returnValue = true; } catch (e) { event.returnValue = false; } });
ipcMain.on('nexus:delete-key', (event, id) => { try { storeKey(id, ''); event.returnValue = true; } catch { event.returnValue = false; } });
ipcMain.handle('nexus:request', async (_event, requestJson) => callProvider(JSON.parse(requestJson)));

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
