'use strict';

const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');

module.exports = async function afterPack(context) {
  if (context.electronPlatformName !== 'win32') return;
  const resources = path.join(context.appOutDir, 'resources');
  const seed = path.join(resources, 'nexus-source-seed.git');
  const sourceShaPath = path.join(resources, 'source-sha.txt');
  const looseRefPath = path.join(seed, 'refs', 'heads', 'nexus-package-source');
  const required = [
    path.join(resources, 'scripts', 'bootstrap_nexus_runner_from_gui.ps1'),
    path.join(resources, 'scripts', 'install_nexus_owner_autostart_from_gui.ps1'),
    sourceShaPath,
    path.join(seed, 'HEAD'),
    path.join(seed, 'shallow'),
    path.join(seed, 'objects'),
    looseRefPath,
  ];
  for (const target of required) {
    if (!fs.existsSync(target)) throw new Error(`packaged owner bootstrap resource missing: ${target}`);
  }

  const expectedSha = fs.readFileSync(sourceShaPath, 'utf8').trim().toLowerCase();
  if (!/^[0-9a-f]{40}$/.test(expectedSha)) {
    throw new Error('packaged owner bootstrap source SHA is invalid');
  }

  const shallow = fs.readFileSync(path.join(seed, 'shallow'), 'utf8').trim();
  if (!/^[0-9a-f]{40}(?:\r?\n[0-9a-f]{40})*$/.test(shallow)) {
    throw new Error('packaged owner bootstrap shallow boundary is invalid');
  }

  const looseRef = fs.readFileSync(looseRefPath, 'utf8').trim().toLowerCase();
  if (looseRef !== expectedSha) {
    throw new Error(`packaged owner bootstrap loose ref mismatch: expected ${expectedSha} got ${looseRef}`);
  }

  let resolved;
  try {
    resolved = execFileSync('git', ['--git-dir', seed, 'rev-parse', 'refs/heads/nexus-package-source'], {
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true,
    }).trim().toLowerCase();
    execFileSync('git', ['--git-dir', seed, 'fsck', '--no-dangling'], {
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true,
    });
  } catch (error) {
    const stderr = error && error.stderr ? String(error.stderr).trim() : '';
    throw new Error(`packaged owner bootstrap Git seed is invalid${stderr ? `: ${stderr}` : ''}`);
  }

  if (resolved !== expectedSha) {
    throw new Error(`packaged owner bootstrap Git ref mismatch: expected ${expectedSha} got ${resolved}`);
  }
};
