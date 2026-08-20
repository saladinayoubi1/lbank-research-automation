const { app, ipcMain } = require('electron');
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const BOOTSTRAP_TIMEOUT_MS = 35000;
const RUNNER_PROVISION_TIMEOUT_MS = 5 * 60 * 1000;
const RUNNER_SUPERVISOR_INTERVAL_MS = 60 * 1000;
const OWNER_AUTOSTART_TIMEOUT_MS = 15 * 60 * 1000;
const OWNER_AUTOSTART_RETRY_LIMIT = 3;
const OWNER_AUTOSTART_RETRY_DELAY_MS = 15 * 1000;
const RUNNER_STATE_CHANNEL = 'nexus:runner-bootstrap:get';
const RUNNER_EVIDENCE_MAX_BYTES = 64 * 1024;
const RUNNER_REGISTRATION_TOKEN_ENV = 'NEXUS_GITHUB_RUNNER_REGISTRATION_TOKEN';
let runnerRegistrationToken = String(process.env[RUNNER_REGISTRATION_TOKEN_ENV] || '').trim();
delete process.env[RUNNER_REGISTRATION_TOKEN_ENV];

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

function safeRunnerText(value, maxLength = 160) {
  if (typeof value !== 'string') return null;
  return value.replace(/[\u0000-\u001f\u007f]+/g, ' ').trim().slice(0, maxLength) || null;
}

function parseRunnerEvidenceJson(raw) {
  const text = String(raw ?? '');
  const normalized = text.charCodeAt(0) === 0xFEFF ? text.slice(1) : text;
  return JSON.parse(normalized);
}

function runnerBootstrapEvidencePath() {
  const localAppData = String(process.env.LOCALAPPDATA || '').trim();
  if (!localAppData || !path.isAbsolute(localAppData)) return null;
  const nexusRoot = path.resolve(localAppData, 'NEXUS');
  const target = path.resolve(nexusRoot, 'GuiRunnerBootstrap', 'evidence.json');
  const relative = path.relative(nexusRoot, target);
  if (!relative || relative.startsWith('..') || path.isAbsolute(relative)) return null;
  return target;
}

function safeRunnerBootstrapState() {
  const target = runnerBootstrapEvidencePath();
  if (!target) return { available: false, status: 'LOCALAPPDATA_UNAVAILABLE' };
  try {
    const stat = fs.lstatSync(target);
    if (!stat.isFile() || stat.isSymbolicLink() || stat.size < 2 || stat.size > RUNNER_EVIDENCE_MAX_BYTES) {
      return { available: false, status: 'EVIDENCE_FILE_REJECTED' };
    }
    const payload = parseRunnerEvidenceJson(fs.readFileSync(target, 'utf8'));
    if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
      return { available: false, status: 'EVIDENCE_SCHEMA_REJECTED' };
    }
    const status = safeRunnerText(payload.status, 96);
    if (!status || !/^[A-Z0-9_]+$/.test(status)) {
      return { available: false, status: 'EVIDENCE_STATUS_REJECTED' };
    }
    const sourceSha = typeof payload.source_sha === 'string' && /^[0-9a-fA-F]{40}$/.test(payload.source_sha)
      ? payload.source_sha.toLowerCase()
      : null;
    return {
      available: true,
      status,
      source_sha: sourceSha,
      generated_at: safeRunnerText(payload.generated_at, 64),
      agent_name: safeRunnerText(payload.agent_name, 96),
      service_name: safeRunnerText(payload.service_name, 128),
      service_state: safeRunnerText(payload.service_state, 48),
      fallback_transport: safeRunnerText(payload.fallback_transport, 64),
      error: safeRunnerText(payload.error, 240),
    };
  } catch (error) {
    if (error && error.code === 'ENOENT') return { available: false, status: 'EVIDENCE_NOT_PRESENT' };
    return { available: false, status: 'EVIDENCE_READ_FAILED' };
  }
}

function trustedRunnerStateSender(event) {
  const senderUrl = String(event?.senderFrame?.url || event?.sender?.getURL?.() || '');
  return /^http:\/\/127\.0\.0\.1:\d+\//.test(senderUrl);
}

ipcMain.handle(RUNNER_STATE_CHANNEL, event => {
  if (!trustedRunnerStateSender(event)) throw new Error('untrusted NEXUS runner-state sender');
  return safeRunnerBootstrapState();
});

function runPackagedPowerShell({ scriptName, timeoutMs, log, sourceSha, extraEnv = {}, redactOutput = false }) {
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
      env: { ...process.env, ...extraEnv },
    });

    let stdout = '';
    let stderr = '';
    let settled = false;
    const finish = (result) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      const output = redactOutput
        ? { stdout_bytes: Buffer.byteLength(stdout), stderr_bytes: Buffer.byteLength(stderr), output_redacted: true }
        : { stdout: stdout.slice(-1200), stderr: stderr.slice(-1200) };
      log(JSON.stringify({ source_sha: sourceSha, script: scriptName, ...result, ...output }));
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

function startRunnerProvisioning(sourceSha) {
  if (!runnerRegistrationToken) {
    appendBootstrapLog('runner_provision_auth_required token_source=NEXUS_GITHUB_RUNNER_REGISTRATION_TOKEN');
    return Promise.resolve({ status: 'REGISTRATION_TOKEN_REQUIRED', code: 20 });
  }
  const token = runnerRegistrationToken;
  runnerRegistrationToken = '';
  return runPackagedPowerShell({
    scriptName: 'provision_nexus_github_runner.ps1',
    timeoutMs: RUNNER_PROVISION_TIMEOUT_MS,
    log: appendBootstrapLog,
    sourceSha,
    extraEnv: { [RUNNER_REGISTRATION_TOKEN_ENV]: token },
    redactOutput: true,
  });
}

let runnerBootstrapInFlight = false;
async function reconcileRunnerFromGui() {
  if (runnerBootstrapInFlight) return { status: 'ALREADY_RUNNING' };
  runnerBootstrapInFlight = true;
  try {
    const initial = await startRunnerColdBootstrap().catch(error => {
      appendBootstrapLog(`cold bootstrap rejected: ${error && error.message ? error.message : error}`);
      return { status: 'FAILED' };
    });
    const state = safeRunnerBootstrapState();
    if (!state.available || state.status !== 'RUNNER_NOT_FOUND') return initial;

    const sourceSha = packagedSourceSha();
    const provisioned = await startRunnerProvisioning(sourceSha);
    if (!provisioned || provisioned.status !== 'SUCCESS') return provisioned || { status: 'PROVISION_FAILED' };
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
  void reconcileRunnerFromGui();
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
