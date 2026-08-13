'use strict';

const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');
const { buildState } = require('./nexus_orchestrator');

const ROOT = path.resolve(__dirname, '..');
const QUEUE_PATH = path.join(ROOT, 'config', 'nexus-mission-queue.json');
const STATE_PATH = path.join(ROOT, 'runtime', 'nexus-worker-state.json');

function run(cmd, args, options = {}) {
  const result = spawnSync(cmd, args, {
    cwd: ROOT,
    encoding: 'utf8',
    shell: process.platform === 'win32',
    timeout: options.timeout || 120000,
    env: { ...process.env, ...(options.env || {}) },
  });
  return {
    ok: result.status === 0,
    status: result.status,
    stdout: (result.stdout || '').trim(),
    stderr: (result.stderr || '').trim(),
  };
}

function ensureRuntimeDir() {
  fs.mkdirSync(path.dirname(STATE_PATH), { recursive: true });
}

function loadQueue() {
  return JSON.parse(fs.readFileSync(QUEUE_PATH, 'utf8'));
}

function missionProfile(mission) {
  const profiles = {
    'M-010': {
      lane: 'product',
      tools: ['orchestrator', 'deepseek', 'agents', 'runner'],
      verify: ['node', ['scripts/nexus_orchestrator.js']],
    },
    'M-011': {
      lane: 'product',
      tools: ['orchestrator', 'deepseek', 'agents', 'runner'],
      verify: ['node', ['scripts/nexus_ai_council.js']],
    },
    'M-012': {
      lane: 'blocker',
      tools: ['orchestrator', 'runner', 'ci'],
      verify: ['node', ['scripts/nexus_orchestrator.js']],
    },
  };
  return profiles[mission.id] || { lane: 'backlog', tools: ['orchestrator'], verify: ['node', ['scripts/nexus_orchestrator.js']] };
}

function deepSeekProbe() {
  if (!process.env.DEEPSEEK_API_KEY) {
    return { attempted: false, ok: false, reason: 'DEEPSEEK_API_KEY_missing' };
  }
  const result = run('python', ['scripts/deepseek_smoke.py'], { timeout: 90000 });
  return { attempted: true, ...result };
}

function executeCycle() {
  const queue = loadQueue();
  const state = buildState(queue);
  const selectedIds = state.selectedMissionIds || (state.selectedMissionId ? [state.selectedMissionId] : []);
  const byId = new Map(queue.missions.map((m) => [m.id, m]));
  const records = [];

  for (const id of selectedIds) {
    const mission = byId.get(id);
    if (!mission) continue;
    const profile = missionProfile(mission);
    const verification = run(profile.verify[0], profile.verify[1]);
    const deepseek = profile.tools.includes('deepseek') ? deepSeekProbe() : { attempted: false, ok: false, reason: 'not_required' };
    records.push({
      missionId: mission.id,
      title: mission.title,
      lane: profile.lane,
      toolsPlanned: profile.tools,
      verification,
      deepseek,
    });
  }

  const snapshot = {
    version: 1,
    timestamp: new Date().toISOString(),
    host: process.env.RUNNER_NAME || process.env.COMPUTERNAME || process.env.HOSTNAME || 'unknown',
    runnerEnvironment: process.env.RUNNER_ENVIRONMENT || 'local',
    selectedMissionIds: selectedIds,
    records,
  };

  ensureRuntimeDir();
  const tmp = `${STATE_PATH}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify(snapshot, null, 2));
  fs.renameSync(tmp, STATE_PATH);
  process.stdout.write(`${JSON.stringify(snapshot, null, 2)}\n`);
  return snapshot;
}

function main() {
  const once = process.argv.includes('--once');
  const intervalArg = process.argv.find((arg) => arg.startsWith('--interval-ms='));
  const intervalMs = intervalArg ? Number(intervalArg.split('=')[1]) : 20000;
  if (!Number.isFinite(intervalMs) || intervalMs < 5000) throw new Error('interval must be >= 5000ms');

  executeCycle();
  if (once) return;
  setInterval(() => {
    try {
      executeCycle();
    } catch (error) {
      process.stderr.write(`[nexus-worker] ${error.stack || error.message}\n`);
    }
  }, intervalMs);
}

if (require.main === module) main();

module.exports = { executeCycle, missionProfile };
