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

function assessProjectMemory() {
  const head = run('git', ['rev-parse', 'HEAD']);
  if (!head.ok || !/^[0-9a-f]{40}$/.test(head.stdout)) {
    return {
      authoritative: false,
      reason: 'current_head_unavailable',
    };
  }
  const result = run(process.env.PYTHON || 'python', [
    'project_memory_runtime_gate.py',
    '--expected-main',
    head.stdout,
  ]);
  if (!result.ok) {
    return {
      authoritative: false,
      reason: 'runtime_gate_execution_failed',
      expectedMainSha: head.stdout,
    };
  }
  try {
    const parsed = JSON.parse(result.stdout);
    return {
      authoritative: parsed.authoritative === true,
      reason: parsed.reason || 'unknown',
      expectedMainSha: head.stdout,
      observedMainSha: parsed.observed_main_sha || null,
    };
  } catch (_error) {
    return {
      authoritative: false,
      reason: 'runtime_gate_output_malformed',
      expectedMainSha: head.stdout,
    };
  }
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

  status.resources.projectMemory = assessProjectMemory();
  status.resources.aiCouncil = run(process.execPath, [path.join('scripts', 'test_nexus_ai_council.js')]);

  const paidRoutingAllowed = process.env.NEXUS_DEEPSEEK_PAID_ROUTING_ALLOWED === '1';
  if (paidRoutingAllowed && process.env.DEEPSEEK_API_KEY) {
    status.resources.deepseek = run(process.env.PYTHON || 'python', [path.join('scripts', 'deepseek_smoke.py')], {
      env: { ...process.env, PYTHONPATH: ROOT },
    });
  } else {
    status.resources.deepseek = {
      ok: false,
      skipped: true,
      reason: paidRoutingAllowed
        ? 'DEEPSEEK_API_KEY missing from runtime environment'
        : 'NEXUS_DEEPSEEK_PAID_ROUTING_ALLOWED is not 1',
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

  // Stale/conflicting Project Memory is explicitly non-authoritative but does not
  // block independent queue work. Only mandatory runtime components fail the cycle.
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

module.exports = { assessProjectMemory, cycle };
