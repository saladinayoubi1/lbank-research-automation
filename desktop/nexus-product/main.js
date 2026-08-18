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
let productReady = false;
let isQuitting = false;
let restartCount = 0;
let restartWindowStartedAt = Date.now();
let restartScheduled = false;
const MAX_RESTARTS_PER_WINDOW = 3;
const RESTART_WINDOW_MS = 10 * 60 * 1000;

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
  const executable = app.isPackaged ? (fs.existsSync(packagedExecutable) ? packagedExecutable : legacyExecutable) : devExecutable;
  const registry = app.isPackaged
    ? path.join(resourceRoot, 'docs', 'architecture', 'market-data-source-registry.yaml')
    : path.join(repoRoot, 'docs', 'architecture', 'market-data-source-registry.yaml');
  const agentConfig = app.isPackaged
    ? path.join(resourceRoot, 'config', 'nexus-agent-manager.json')
    : path.join(repoRoot, 'config', 'nexus-agent-manager.json');
  const buildEvidence = app.isPackaged
    ? path.join(resourceRoot, 'build-evidence.json')
    : path.join(repoRoot, 'desktop', 'nexus-product', 'sidecar', 'build-evidence.json');
  let sourceSha = String(process.env.NEXUS_SOURCE_SHA || '').trim().toLowerCase();
  if (app.isPackaged) {
    const sourceFile = path.join(resourceRoot, 'source-sha.txt');
    if (!fs.existsSync(sourceFile)) throw new Error(`NEXUS source binding missing: ${sourceFile}`);
    sourceSha = fs.readFileSync(sourceFile, 'utf8').trim().toLowerCase();
  }
  if (!/^[0-9a-f]{40}$/.test(sourceSha)) throw new Error('NEXUS release source SHA is missing or invalid');
  if (!fs.existsSync(executable)) throw new Error(`NEXUS product sidecar missing: ${executable}`);
  if (!fs.existsSync(registry)) throw new Error(`NEXUS canonical market registry missing: ${registry}`);
  if (!fs.existsSync(agentConfig)) throw new Error(`NEXUS Agent Manager contract missing: ${agentConfig}`);
  if (app.isPackaged && !fs.existsSync(buildEvidence)) throw new Error(`NEXUS exact-source build evidence missing: ${buildEvidence}`);
  return { executable, registry, agentConfig, buildEvidence, sourceSha, resourceRoot };
}

function supervisorPath() {
  const root = path.join(app.getPath('userData'), 'product-data');
  fs.mkdirSync(root, { recursive: true });
  return path.join(root, 'supervisor-state.json');
}

function writeSupervisorState(status, extra = {}) {
  const payload = {
    contract_version: 'nexus.local-supervisor.v1',
    status,
    updated_at: new Date().toISOString(),
    restart_count: restartCount,
    restart_limit: MAX_RESTARTS_PER_WINDOW,
    restart_window_seconds: RESTART_WINDOW_MS / 1000,
    bounded_restart_policy: true,
    paper_only: true,
    live_trading_authority: false,
    ...extra,
  };
  try {
    const target = supervisorPath();
    const tmp = `${target}.tmp`;
    fs.writeFileSync(tmp, JSON.stringify(payload), 'utf8');
    fs.renameSync(tmp, target);
  } catch (error) {
    logStartup(`supervisor state write failed: ${error.message}`);
  }
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
    } catch (error) { lastError = error; }
    await new Promise(resolve => setTimeout(resolve, 400));
  }
  const detail = sidecarStderr.trim().slice(-1200);
  throw new Error(`NEXUS product gateway did not become ready within ${Math.round(timeoutMs / 1000)}s: ${lastError || 'timeout'}${detail ? `; engine: ${detail}` : ''}`);
}

function canRestart() {
  const now = Date.now();
  if (now - restartWindowStartedAt > RESTART_WINDOW_MS) {
    restartWindowStartedAt = now;
    restartCount = 0;
  }
  return restartCount < MAX_RESTARTS_PER_WINDOW;
}

async function restartProductAfterExit(exitInfo) {
  if (isQuitting || restartScheduled) return;
  if (!canRestart()) {
    writeSupervisorState('blocked', { reason: 'bounded_restart_limit_reached', last_exit: exitInfo });
    logStartup('bounded supervisor restart limit reached');
    return;
  }
  restartScheduled = true;
  restartCount += 1;
  writeSupervisorState('restarting', { reason: 'unexpected_sidecar_exit', last_exit: exitInfo });
  await new Promise(resolve => setTimeout(resolve, Math.min(5000, 800 * restartCount)));
  try {
    const origin = await startSidecar();
    for (const win of BrowserWindow.getAllWindows()) { try { win.destroy(); } catch {} }
    createWindow(origin);
  } catch (error) {
    logStartup(`supervised restart failed: ${error && error.stack ? error.stack : error}`);
    writeSupervisorState('restart_failed', { reason: String(error && error.message ? error.message : error), last_exit: exitInfo });
  } finally {
    restartScheduled = false;
  }
}

async function startSidecar() {
  if (!startupLogPath) initStartupLog();
  const port = await freePort();
  if (!Number.isInteger(port) || port < 1024 || port > 65535) throw new Error('Unable to allocate bounded product port');
  const dataRoot = path.join(app.getPath('userData'), 'product-data', 'market');
  fs.mkdirSync(dataRoot, { recursive: true });
  const bindings = productBindings();
  const args = ['--host', '127.0.0.1', '--port', String(port), '--data-root', dataRoot];
  sidecarExit = null;
  sidecarStderr = '';
  productReady = false;
  writeSupervisorState('starting', { source_sha: bindings.sourceSha });
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
      NEXUS_AGENT_MANAGER_CONFIG: bindings.agentConfig,
      NEXUS_BUILD_EVIDENCE_PATH: bindings.buildEvidence,
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
    const wasReady = productReady;
    const info = { code, signal: signal || null, at: new Date().toISOString() };
    sidecarExit = info;
    productReady = false;
    logStartup(`engine exit: code=${code} signal=${signal || 'none'}`);
    sidecar = null;
    if (wasReady && !isQuitting) restartProductAfterExit(info);
  });
  productOrigin = `http://127.0.0.1:${port}`;
  await waitForProduct(productOrigin);
  productReady = true;
  writeSupervisorState('healthy', { source_sha: bindings.sourceSha, origin: productOrigin });
  return productOrigin;
}

function stopSidecar() {
  productReady = false;
  if (sidecar && !sidecar.killed) { try { sidecar.kill(); } catch {} }
  sidecar = null;
}

function createWindow(origin) {
  const win = new BrowserWindow({
    width: 1480, height: 920, minWidth: 1024, minHeight: 700, show: false,
    backgroundColor: '#090c10', autoHideMenuBar: true, title: 'NEXUS Personal Pro',
    titleBarStyle: 'hidden', titleBarOverlay: { color: '#0a0e13', symbolColor: '#e8eef6', height: 44 },
    webPreferences: { contextIsolation: true, sandbox: true, nodeIntegration: false, devTools: false, webSecurity: true, allowRunningInsecureContent: false },
  });
  win.webContents.setWindowOpenHandler(({ url }) => {
    try { const target = new URL(url); if (target.protocol === 'https:') shell.openExternal(url); } catch {}
    return { action: 'deny' };
  });
  win.webContents.on('will-navigate', (event, url) => { if (!url.startsWith(origin + '/')) event.preventDefault(); });
  win.webContents.session.webRequest.onBeforeRequest((details, callback) => {
    try {
      const target = new URL(details.url);
      const allowed = target.origin === origin || details.url.startsWith('devtools://');
      callback({ cancel: !allowed });
    } catch { callback({ cancel: true }); }
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
  try { const origin = await startSidecar(); createWindow(origin); }
  catch (error) {
    logStartup(`startup blocked: ${error && error.stack ? error.stack : error}`);
    writeSupervisorState('startup_failed', { reason: String(error && error.message ? error.message : error) });
    showStartupFailure(error);
  }
  app.on('activate', async () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      try { if (!productOrigin || !productReady) productOrigin = await startSidecar(); createWindow(productOrigin); }
      catch (error) { showStartupFailure(error); }
    }
  });
});

app.on('before-quit', () => { isQuitting = true; writeSupervisorState('stopping'); stopSidecar(); });
app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') { isQuitting = true; stopSidecar(); app.quit(); }
});
