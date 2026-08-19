const { app } = require('electron');
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const BOOTSTRAP_TIMEOUT_MS = 35000;
const RUNNER_SUPERVISOR_INTERVAL_MS = 60 * 1000;
const OWNER_AUTOSTART_TIMEOUT_MS = 15 * 60 * 1000;
const OWNER_AUTOSTART_RETRY_LIMIT = 3;
const OWNER_AUTOSTART_RETRY_DELAY_MS = 15 * 1000;

function appendBootstrapLog(message) {
  try {
    const root = app.getPath('logs');
    fs.mkdirSync(root, { recursive: true });
    const target = path.join(root, 'nexus-gui-runner-bootstrap.log');
    fs.appendFileSync(target, `[${new Date().toISOString()}] ${String(message).slice(0, 4000)}\n`, 'utf8');
  } catch {}
}

function appendOwnerAutostartLog(message) {
  try {
    const root = app.getPath('logs');
    fs.mkdirSync(root, { recursive: true });
    const target = path.join(root, 'nexus-owner-autostart-bootstrap.log');
    fs.appendFileSync(target, `[${new Date().toISOString()}] ${String(message).slice(0, 4000)}\n`, 'utf8');
  } catch {}
}

function packagedSourceSha() {
  const sourcePath = path.join(process.resourcesPath, 'source-sha.txt');
  if (!fs.existsSync(sourcePath)) throw new Error('NEXUS packaged source SHA binding is missing');
  const sha = fs.readFileSync(sourcePath, 'utf8').trim().toLowerCase();
  if (!/^[0-9a-f]{40}$/.test(sha)) throw new Error('NEXUS packaged source SHA binding is invalid');
  return sha;
}

function windowsPowerShell() {
  const systemRoot = process.env.SystemRoot || 'C:\\Windows';
  return path.join(systemRoot, 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe');
}

function runPackagedPowerShell({ scriptName, timeoutMs, log, sourceSha }) {
  const script = path.join(process.resourcesPath, 'scripts', scriptName);
  if (!fs.existsSync(script)) {
    log(`blocked: bootstrap script missing: ${script}`);
    return Promise.resolve({ status: 'SCRIPT_MISSING' });
  }

  return new Promise((resolve) => {
    const child = spawn(windowsPowerShell(), [
      '-NoProfile',
      '-NonInteractive',
      '-WindowStyle', 'Hidden',
      '-ExecutionPolicy', 'Bypass',
      '-File', script,
      '-SourceSha', sourceSha,
    ], {
      windowsHide: true,
      stdio: ['ignore', 'pipe', 'pipe'],
      env: { ...process.env },
    });

    let stdout = '';
    let stderr = '';
    let settled = false;
    const finish = (result) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      log(JSON.stringify({ source_sha: sourceSha, script: scriptName, ...result, stdout: stdout.slice(-1200), stderr: stderr.slice(-1200) }));
      resolve(result);
    };

    child.stdout.on('data', chunk => { stdout = (stdout + String(chunk)).slice(-8192); });
    child.stderr.on('data', chunk => { stderr = (stderr + String(chunk)).slice(-8192); });
    child.on('error', error => finish({ status: 'SPAWN_ERROR', error: error.message }));
    child.on('exit', (code, signal) => finish({ status: code === 0 ? 'SUCCESS' : 'FAILED', code, signal: signal || null }));

    const timer = setTimeout(() => {
      try { child.kill(); } catch {}
      finish({ status: 'TIMEOUT', code: null, signal: null });
    }, timeoutMs);
  });
}

function startRunnerColdBootstrap() {
  const sourceSha = packagedSourceSha();
  return runPackagedPowerShell({
    scriptName: 'bootstrap_nexus_runner_from_gui.ps1',
    timeoutMs: BOOTSTRAP_TIMEOUT_MS,
    log: appendBootstrapLog,
    sourceSha,
  });
}

let runnerBootstrapInFlight = false;
async function reconcileRunnerFromGui() {
  if (runnerBootstrapInFlight) return { status: 'ALREADY_RUNNING' };
  runnerBootstrapInFlight = true;
  try {
    return await startRunnerColdBootstrap();
  } catch (error) {
    appendBootstrapLog(`unexpected bootstrap error: ${error && error.stack ? error.stack : error}`);
    return { status: 'UNEXPECTED_ERROR' };
  } finally {
    runnerBootstrapInFlight = false;
  }
}

function startRunnerSupervisor() {
  const timer = setInterval(() => { void reconcileRunnerFromGui(); }, RUNNER_SUPERVISOR_INTERVAL_MS);
  app.once('before-quit', () => clearInterval(timer));
  appendBootstrapLog(`runner_supervisor_started interval_ms=${RUNNER_SUPERVISOR_INTERVAL_MS}`);
}

function startOwnerAutostartBootstrap(sourceSha) {
  const seed = path.join(process.resourcesPath, 'nexus-source-seed.git');
  if (!fs.existsSync(seed)) {
    appendOwnerAutostartLog(`blocked: exact-source seed missing: ${seed}`);
    return Promise.resolve({ status: 'SOURCE_SEED_MISSING' });
  }
  return runPackagedPowerShell({
    scriptName: 'install_nexus_owner_autostart_from_gui.ps1',
    timeoutMs: OWNER_AUTOSTART_TIMEOUT_MS,
    log: appendOwnerAutostartLog,
    sourceSha,
  });
}

function delay(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

async function startOwnerAutostartWithRetry(sourceSha) {
  for (let attempt = 1; attempt <= OWNER_AUTOSTART_RETRY_LIMIT; attempt += 1) {
    const result = await startOwnerAutostartBootstrap(sourceSha).catch(error => {
      appendOwnerAutostartLog(`unexpected owner bootstrap error attempt=${attempt}: ${error && error.stack ? error.stack : error}`);
      return { status: 'UNEXPECTED_ERROR' };
    });
    if (result && result.status === 'SUCCESS') {
      appendOwnerAutostartLog(`owner_bootstrap_complete attempt=${attempt}`);
      return result;
    }
    if (attempt < OWNER_AUTOSTART_RETRY_LIMIT) {
      appendOwnerAutostartLog(`owner_bootstrap_retry attempt=${attempt} status=${result && result.status ? result.status : 'UNKNOWN'} delay_ms=${OWNER_AUTOSTART_RETRY_DELAY_MS}`);
      await delay(OWNER_AUTOSTART_RETRY_DELAY_MS);
    }
  }
  appendOwnerAutostartLog(`owner_bootstrap_exhausted attempts=${OWNER_AUTOSTART_RETRY_LIMIT}`);
  return { status: 'RETRY_EXHAUSTED' };
}

app.whenReady().then(() => {
  if (process.platform !== 'win32' || !app.isPackaged) return;
  startRunnerColdBootstrap().catch(error => appendBootstrapLog(`unexpected bootstrap error: ${error && error.stack ? error.stack : error}`));
  startRunnerSupervisor();
  let sourceSha;
  try { sourceSha = packagedSourceSha(); }
  catch (error) {
    appendOwnerAutostartLog(`blocked: ${error.message}`);
    return;
  }
  void startOwnerAutostartWithRetry(sourceSha);
});

require('./main.js');
