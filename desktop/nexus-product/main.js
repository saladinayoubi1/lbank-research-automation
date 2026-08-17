const { app, BrowserWindow, shell } = require('electron');
const { spawn } = require('child_process');
const fs = require('fs');
const net = require('net');
const path = require('path');

let sidecar = null;
let productOrigin = null;

function freePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.on('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const address = server.address();
      const port = address && typeof address === 'object' ? address.port : null;
      server.close(err => err ? reject(err) : resolve(port));
    });
  });
}

async function waitForProduct(origin, timeoutMs = 25000) {
  const deadline = Date.now() + timeoutMs;
  let lastError = null;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`${origin}/api/product/overview`, {
        method: 'GET',
        redirect: 'error',
        cache: 'no-store',
        signal: AbortSignal.timeout(1800),
      });
      if (response.ok) return;
      lastError = new Error(`HTTP ${response.status}`);
    } catch (error) {
      lastError = error;
    }
    await new Promise(resolve => setTimeout(resolve, 250));
  }
  throw new Error(`NEXUS product gateway did not become ready: ${lastError || 'timeout'}`);
}

async function startSidecar() {
  const port = await freePort();
  if (!Number.isInteger(port) || port < 1024 || port > 65535) throw new Error('Unable to allocate bounded product port');
  const dataRoot = path.join(app.getPath('userData'), 'product-data', 'market');
  fs.mkdirSync(dataRoot, { recursive: true });
  const executable = app.isPackaged
    ? path.join(process.resourcesPath, 'nexus-product-server.exe')
    : path.resolve(__dirname, '..', '..', 'dist', 'nexus-product-server.exe');
  if (!fs.existsSync(executable)) throw new Error(`NEXUS product sidecar missing: ${executable}`);
  const args = ['--host', '127.0.0.1', '--port', String(port), '--data-root', dataRoot];
  sidecar = spawn(executable, args, {
    windowsHide: true,
    stdio: ['ignore', 'pipe', 'pipe'],
    env: { ...process.env, PYTHONUTF8: '1' },
  });
  sidecar.stdout.on('data', () => {});
  sidecar.stderr.on('data', () => {});
  sidecar.on('exit', () => { sidecar = null; });
  productOrigin = `http://127.0.0.1:${port}`;
  await waitForProduct(productOrigin);
  return productOrigin;
}

function stopSidecar() {
  if (sidecar && !sidecar.killed) {
    try { sidecar.kill(); } catch {}
  }
  sidecar = null;
}

function createWindow(origin) {
  const win = new BrowserWindow({
    width: 1480,
    height: 920,
    minWidth: 1024,
    minHeight: 700,
    show: false,
    backgroundColor: '#090c10',
    autoHideMenuBar: true,
    title: 'NEXUS Personal Pro',
    titleBarStyle: 'hidden',
    titleBarOverlay: { color: '#0a0e13', symbolColor: '#e8eef6', height: 44 },
    webPreferences: {
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false,
      devTools: false,
      webSecurity: true,
      allowRunningInsecureContent: false,
    },
  });
  win.webContents.setWindowOpenHandler(({ url }) => {
    try {
      const target = new URL(url);
      if (target.protocol === 'https:') shell.openExternal(url);
    } catch {}
    return { action: 'deny' };
  });
  win.webContents.on('will-navigate', (event, url) => {
    if (!url.startsWith(origin + '/')) event.preventDefault();
  });
  win.webContents.session.webRequest.onBeforeRequest((details, callback) => {
    try {
      const target = new URL(details.url);
      const allowed = target.origin === origin || details.url.startsWith('devtools://');
      callback({ cancel: !allowed });
    } catch {
      callback({ cancel: true });
    }
  });
  win.loadURL(origin + '/');
  win.once('ready-to-show', () => win.show());
  return win;
}

app.whenReady().then(async () => {
  try {
    const origin = await startSidecar();
    createWindow(origin);
  } catch (error) {
    const win = new BrowserWindow({ width: 800, height: 520, backgroundColor: '#090c10' });
    const message = String(error && error.message ? error.message : error).replace(/[<>&]/g, '');
    win.loadURL(`data:text/html;charset=utf-8,<body style="background:%23090c10;color:%23fff;font-family:Segoe UI;padding:30px"><h2>NEXUS startup blocked</h2><p>${encodeURIComponent(message)}</p><p>The product failed closed. No Paper or Live state was changed.</p></body>`);
  }
  app.on('activate', async () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      if (!productOrigin) productOrigin = await startSidecar();
      createWindow(productOrigin);
    }
  });
});

app.on('before-quit', stopSidecar);
app.on('window-all-closed', () => {
  stopSidecar();
  if (process.platform !== 'darwin') app.quit();
});
