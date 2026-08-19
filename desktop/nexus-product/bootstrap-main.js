const { app } = require('electron');
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const BOOTSTRAP_TIMEOUT_MS = 35000;
const OWNER_AUTOSTART_TIMEOUT_MS = 15 * 60 * 1000;

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

function startRunnerColdBootstrap(sourceSha) {
  return runPackagedPowerShell({
    scriptName: 'bootstrap_nexus_runner_from_gui.ps1',
    timeoutMs: BOOTSTRAP_TIMEOUT_MS,
    log: appendBootstrapLog,
    sourceSha,
  });
}

function startOwnerAutostartBootstrap(sourceSha) {
  const bundle = path.join(process.resourcesPath, 'nexus-source.bundle');
  if (!fs.existsSync(bundle)) {
    appendOwnerAutostartLog(`blocked: exact-source bundle missing: ${bundle}`);
    return Promise.resolve({ status: 'SOURCE_BUNDLE_MISSING' });
  }
  return runPackagedPowerShell({
    scriptName: 'install_nexus_owner_autostart_from_gui.ps1',
    timeoutMs: OWNER_AUTOSTART_TIMEOUT_MS,
    log: appendOwnerAutostartLog,
    sourceSha,
  });
}

app.whenReady().then(() => {
  if (process.platform !== 'win32' || !app.isPackaged) return;
  let sourceSha;
  try { sourceSha = packagedSourceSha(); }
  catch (error) {
    appendBootstrapLog(`blocked: ${error.message}`);
    appendOwnerAutostartLog(`blocked: ${error.message}`);
    return;
  }
  startRunnerColdBootstrap(sourceSha).catch(error => appendBootstrapLog(`unexpected bootstrap error: ${error && error.stack ? error.stack : error}`));
  startOwnerAutostartBootstrap(sourceSha).catch(error => appendOwnerAutostartLog(`unexpected owner bootstrap error: ${error && error.stack ? error.stack : error}`));
});

require('./main.js');
