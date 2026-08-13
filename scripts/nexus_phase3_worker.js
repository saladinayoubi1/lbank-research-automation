'use strict';

const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');
const { buildState } = require('./nexus_orchestrator');

const ROOT = path.resolve(__dirname, '..');
const QUEUE = path.join(ROOT, 'config', 'nexus-mission-queue.json');
const STATUS = path.join(ROOT, 'build', 'nexus', 'phase3-resource-status.json');

function run(cmd, args, options = {}) {
  const result = spawnSync(cmd, args, {
    cwd: ROOT,
    encoding: 'utf8',
    shell: false,
    ...options,
  });
  return {
    ok: result.status === 0,
    status: result.status,
    stdout: (result.stdout || '').trim(),
    stderr: (result.stderr || '').trim(),
  };
}

function cycle() {
  const queue = JSON.parse(fs.readFileSync(QUEUE, 'utf8'));
  const state = buildState(queue);
  const status = {
    version: 1,
    timestamp: new Date().toISOString(),
    selected: state.readyMissionIds || [],
    resources: {},
  };

  status.resources.orchestrator = {
    ok: true,
    selected: state.readyMissionIds || [],
  };

  status.resources.aiCouncil = run(process.execPath, [path.join('scripts', 'test_nexus_ai_council.js')]);

  if (process.env.DEEPSEEK_API_KEY) {
    status.resources.deepseek = run(process.env.PYTHON || 'python', [path.join('scripts', 'deepseek_smoke.py')], {
      env: { ...process.env, PYTHONPATH: ROOT },
    });
  } else {
    status.resources.deepseek = {
      ok: false,
      skipped: true,
      reason: 'DEEPSEEK_API_KEY missing from runtime environment',
    };
  }

  status.resources.runner = {
    ok: true,
    platform: process.platform,
    arch: process.arch,
    hostname: process.env.COMPUTERNAME || process.env.HOSTNAME || 'unknown',
    githubRunnerName: process.env.RUNNER_NAME || null,
    githubRunnerEnvironment: process.env.RUNNER_ENVIRONMENT || null,
  };

  fs.mkdirSync(path.dirname(STATUS), { recursive: true });
  fs.writeFileSync(STATUS, `${JSON.stringify(status, null, 2)}\n`, 'utf8');
  process.stdout.write(`${JSON.stringify(status)}\n`);

  const requiredFailed = !status.resources.aiCouncil.ok;
  if (requiredFailed) process.exitCode = 1;
}

function main() {
  const loop = process.argv.includes('--loop');
  const intervalArg = process.argv.find((arg) => arg.startsWith('--interval-ms='));
  const intervalMs = intervalArg ? Math.max(5000, Number(intervalArg.split('=')[1])) : 30000;

  cycle();
  if (!loop) return;
  setInterval(cycle, intervalMs);
}

if (require.main === module) main();
