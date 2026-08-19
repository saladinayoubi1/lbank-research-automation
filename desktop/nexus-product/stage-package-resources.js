'use strict';

const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const desktopRoot = __dirname;
const repoRoot = path.resolve(desktopRoot, '..', '..');
const sidecarRoot = path.join(desktopRoot, 'sidecar');
const packageRef = 'refs/heads/nexus-package-source';

function runGit(args) {
  return execFileSync('git', args, {
    cwd: repoRoot,
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'pipe'],
    windowsHide: true,
  }).trim();
}

function copyScript(name) {
  const source = path.join(repoRoot, 'scripts', name);
  const target = path.join(sidecarRoot, name);
  if (!fs.existsSync(source)) throw new Error(`required bootstrap script missing: ${name}`);
  fs.copyFileSync(source, target);
}

fs.mkdirSync(sidecarRoot, { recursive: true });
copyScript('bootstrap_nexus_runner_from_gui.ps1');
copyScript('install_nexus_owner_autostart_from_gui.ps1');

const head = runGit(['rev-parse', 'HEAD']).toLowerCase();
if (!/^[0-9a-f]{40}$/.test(head)) throw new Error('repository HEAD is not a full SHA');
const expected = String(process.env.GITHUB_SHA || head).trim().toLowerCase();
if (expected !== head) throw new Error(`build source mismatch: GITHUB_SHA=${expected} HEAD=${head}`);

// GitHub Actions normally checks out a shallow repository. A Git bundle made from
// that state may advertise the exact ref while omitting parent objects required by
// a fresh clone. Expand history only on the trusted build machine; no credentials
// or Git metadata are copied into the packaged resource.
if (runGit(['rev-parse', '--is-shallow-repository']) === 'true') {
  execFileSync('git', ['fetch', '--unshallow', '--no-tags', 'origin'], {
    cwd: repoRoot,
    stdio: ['ignore', 'pipe', 'pipe'],
    windowsHide: true,
  });
}

const bundlePath = path.join(sidecarRoot, 'nexus-source.bundle');
try {
  runGit(['update-ref', packageRef, head]);
  execFileSync('git', ['bundle', 'create', bundlePath, packageRef], {
    cwd: repoRoot,
    stdio: ['ignore', 'pipe', 'pipe'],
    windowsHide: true,
  });
  execFileSync('git', ['bundle', 'verify', bundlePath], {
    cwd: repoRoot,
    stdio: ['ignore', 'pipe', 'pipe'],
    windowsHide: true,
  });
} finally {
  try { runGit(['update-ref', '-d', packageRef]); } catch {}
}

if (!fs.existsSync(bundlePath) || fs.statSync(bundlePath).size < 128) {
  throw new Error('exact-source Git bundle was not created');
}

process.stdout.write(`NEXUS_PACKAGE_SOURCE_SHA=${head}\n`);
process.stdout.write(`NEXUS_PACKAGE_SOURCE_BUNDLE=${bundlePath}\n`);
