const { app, BrowserWindow, shell } = require('electron');
const { spawn } = require('child_process');
const fs = require('fs');
const http = require('http');
const net = require('net');
const path = require('path');

let sidecar = null;
let productOrigin = null;
let sidecarExit = null;
let sidecarStderr = '';
let startupLogPath = null;

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

function productBindings() {
  const repoRoot = path.resolve(__dirname, '..', '..');
  const resourceRoot = app.isPackaged ? process.resourcesPath : repoRoot;
  const packagedExecutable = path.join(resourceRoot, 'nexus-product-server', 'nexus-product-server.exe');
  const legacyExecutable = path.join(resourceRoot, 'nexus-product-server.exe');
  const devExecutable = path.join(repoRoot, 'dist', 'nexus-product-server', 'nexus-product-server.exe');
  const executable = app.isPackaged
    ? (fs.existsSync(packagedExecutable) ? packagedExecutable : legacyExecutable)
    : devExecutable;
  const registry = app.isPackaged
    ? path.join(resourceRoot, 'docs', 'architecture', 'market-data-source-registry.yaml')
    : path.join(repoRoot, 'docs', 'architecture', 'market-data-source-registry.yaml');
  let sourceSha = String(process.env.NEXUS_SOURCE_SHA || '').trim().toLowerCase();
  if (app.isPackaged) {
    const sourceFile = path.join(resourceRoot, 'source-sha.txt');
    if (!fs.existsSync(sourceFile)) throw new Error(`NEXUS source binding missing: ${sourceFile}`);
    sourceSha = fs.readFileSync(sourceFile, 'utf8').trim().toLowerCase();
  }
  if (!/^[0-9a-f]{40}$/.test(sourceSha)) throw new Error('NEXUS release source SHA is missing or invalid');
  if (!fs.existsSync(executable)) throw new Error(`NEXUS product sidecar missing: ${executable}`);
  if (!fs.existsSync(registry)) throw new Error(`NEXUS canonical market registry missing: ${registry}`);
  return { executable, registry, sourceSha, resourceRoot };
}

function initStartupLog() {
  const root = app.getPath('logs');
  fs.mkdirSync(root, { recursive: true });
  startupLogPath = path.join(root, 'nexus-product-startup.log');
  try { fs.writeFileSync(startupLogPath, `[${new Date().toISOString()}] NEXUS startup\n`, 'utf8'); } catch {}
}

function logStartup(line) {
  if (!startupLogPath) return;
  try { fs.appendFileSync(startupLogPath, `[${new Date().toISOString()}] ${String(line).slice(0, 4000)}\n`, 'utf8'); } catch {}
}

function probeProduct(origin, timeoutMs = 2500) {
  return new Promise((resolve, reject) => {
    const request = http.get(`${origin}/api/product/overview`, { timeout: timeoutMs }, response => {
      response.resume();
      if (response.statusCode >= 200 && response.statusCode < 300) resolve();
      else reject(new Error(`HTTP ${response.statusCode}`));
    });
    request.on('timeout', () => request.destroy(new Error('probe timeout')));
    request.on('error', reject);
  });
}

async function waitForProduct(origin, timeoutMs = 90000) {
  const deadline = Date.now() + timeoutMs;
  let lastError = null;
  while (Date.now() < deadline) {
    if (sidecarExit) {
      const detail = sidecarStderr.trim().slice(-1600) || 'no stderr captured';
      throw new Error(`NEXUS product engine exited before startup (code ${sidecarExit.code}, signal ${sidecarExit.signal || 'none'}): ${detail}`);
    }
    try {
      await probeProduct(origin);
      logStartup(`Product gateway ready at ${origin}`);
      return;
    } catch (error) {
      lastError = error;
    }
    await new Promise(resolve => setTimeout(resolve, 400));
  }
  const detail = sidecarStderr.trim().slice(-1200);
  throw new Error(`NEXUS product gateway did not become ready within ${Math.round(timeoutMs / 1000)}s: ${lastError || 'timeout'}${detail ? `; engine: ${detail}` : ''}`);
}

async function startSidecar() {
  initStartupLog();
  const port = await freePort();
  if (!Number.isInteger(port) || port < 1024 || port > 65535) throw new Error('Unable to allocate bounded product port');
  const dataRoot = path.join(app.getPath('userData'), 'product-data', 'market');
  fs.mkdirSync(dataRoot, { recursive: true });
  const bindings = productBindings();
  const args = ['--host', '127.0.0.1', '--port', String(port), '--data-root', dataRoot];
  sidecarExit = null;
  sidecarStderr = '';
  logStartup(`Launching engine: ${bindings.executable}`);
  sidecar = spawn(bindings.executable, args, {
    cwd: path.dirname(bindings.executable),
    windowsHide: true,
    stdio: ['ignore', 'pipe', 'pipe'],
    env: {
      ...process.env,
      PYTHONUTF8: '1',
      NEXUS_SOURCE_SHA: bindings.sourceSha,
      NEXUS_MARKET_REGISTRY_PATH: bindings.registry,
    },
  });
  sidecar.stdout.on('data', chunk => logStartup(`stdout: ${String(chunk).trim()}`));
  sidecar.stderr.on('data', chunk => {
    sidecarStderr = (sidecarStderr + String(chunk)).slice(-65536);
    logStartup(`stderr: ${String(chunk).trim()}`);
  });
  sidecar.on('error', error => {
    sidecarStderr = (sidecarStderr + `\nspawn error: ${error.message}`).slice(-65536);
    sidecarExit = { code: 'spawn-error', signal: null };
    logStartup(`spawn error: ${error.message}`);
  });
  sidecar.on('exit', (code, signal) => {
    sidecarExit = { code, signal };
    logStartup(`engine exit: code=${code} signal=${signal || 'none'}`);
    sidecar = null;
  });
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

function showStartupFailure(error) {
  const win = new BrowserWindow({ width: 860, height: 560, backgroundColor: '#090c10' });
  const message = String(error && error.message ? error.message : error).replace(/[<>&]/g, '');
  const logText = startupLogPath ? `Startup diagnostics: ${startupLogPath}` : 'Startup diagnostics unavailable';
  win.loadURL(`data:text/html;charset=utf-8,<body style="background:%23090c10;color:%23fff;font-family:Segoe UI;padding:30px"><h2>NEXUS startup blocked</h2><p>${encodeURIComponent(message)}</p><p>${encodeURIComponent(logText)}</p><p>The product failed closed. No Paper or Live state was changed.</p></body>`);
}

app.whenReady().then(async () => {
  try {
    const origin = await startSidecar();
    createWindow(origin);
  } catch (error) {
    logStartup(`startup blocked: ${error && error.stack ? error.stack : error}`);
    showStartupFailure(error);
  }
  app.on('activate', async () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      try {
        if (!productOrigin) productOrigin = await startSidecar();
        createWindow(productOrigin);
      } catch (error) {
        showStartupFailure(error);
      }
    }
  });
});

app.on('before-quit', stopSidecar);
app.on('window-all-closed', () => {
  stopSidecar();
  if (process.platform !== 'darwin') app.quit();
});
