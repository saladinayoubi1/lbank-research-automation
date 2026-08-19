const { app } = require('electron');
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const BOOTSTRAP_TIMEOUT_MS = 35000;

function appendBootstrapLog(message) {
  try {
    const root = app.getPath('logs');
    fs.mkdirSync(root, { recursive: true });
    const target = path.join(root, 'nexus-gui-runner-bootstrap.log');
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
  const fixed = path.join(systemRoot, 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe');
  return fixed;
}

function startRunnerColdBootstrap() {
  if (process.platform !== 'win32' || !app.isPackaged) return Promise.resolve({ status: 'SKIPPED' });

  const script = path.join(process.resourcesPath, 'scripts', 'bootstrap_nexus_runner_from_gui.ps1');
  if (!fs.existsSync(script)) {
    appendBootstrapLog(`blocked: bootstrap script missing: ${script}`);
    return Promise.resolve({ status: 'SCRIPT_MISSING' });
  }

  let sourceSha;
  try { sourceSha = packagedSourceSha(); }
  catch (error) {
    appendBootstrapLog(`blocked: ${error.message}`);
    return Promise.resolve({ status: 'SOURCE_BINDING_INVALID' });
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
      appendBootstrapLog(JSON.stringify({ source_sha: sourceSha, ...result, stdout: stdout.slice(-1200), stderr: stderr.slice(-1200) }));
      resolve(result);
    };

    child.stdout.on('data', chunk => { stdout = (stdout + String(chunk)).slice(-8192); });
    child.stderr.on('data', chunk => { stderr = (stderr + String(chunk)).slice(-8192); });
    child.on('error', error => finish({ status: 'SPAWN_ERROR', error: error.message }));
    child.on('exit', (code, signal) => finish({ status: code === 0 ? 'SUCCESS' : 'FAILED', code, signal: signal || null }));

    const timer = setTimeout(() => {
      try { child.kill(); } catch {}
      finish({ status: 'TIMEOUT', code: null, signal: null });
    }, BOOTSTRAP_TIMEOUT_MS);
  });
}

app.whenReady().then(() => {
  startRunnerColdBootstrap().catch(error => appendBootstrapLog(`unexpected bootstrap error: ${error && error.stack ? error.stack : error}`));
});

require('./main.js');
