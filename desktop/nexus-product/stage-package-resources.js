'use strict';

const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const { pathToFileURL } = require('url');

const desktopRoot = __dirname;
const repoRoot = path.resolve(desktopRoot, '..', '..');
const sidecarRoot = path.join(desktopRoot, 'sidecar');
const packageRef = 'refs/heads/nexus-package-source';

function runGit(args, options = {}) {
  return execFileSync('git', args, {
    cwd: options.cwd || repoRoot,
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
copyScript('provision_nexus_github_runner.ps1');
copyScript('install_nexus_owner_autostart_from_gui.ps1');

const head = runGit(['rev-parse', 'HEAD']).toLowerCase();
if (!/^[0-9a-f]{40}$/.test(head)) throw new Error('repository HEAD is not a full SHA');
const expected = String(process.env.GITHUB_SHA || head).trim().toLowerCase();
if (expected !== head) throw new Error(`build source mismatch: GITHUB_SHA=${expected} HEAD=${head}`);

// Keep the packaged source small and self-contained: create a depth-1 bare seed
// from the exact build commit. Git preserves the original commit/tree identity and
// records the missing ancestry as a shallow boundary. No GitHub credential/config
// is copied into the package.
const seedPath = path.join(sidecarRoot, 'nexus-source-seed.git');
fs.rmSync(seedPath, { recursive: true, force: true });
try {
  runGit(['update-ref', packageRef, head]);
  const sourceUrl = pathToFileURL(repoRoot + path.sep).href;
  execFileSync('git', [
    'clone', '--depth', '1', '--bare', '--branch', 'nexus-package-source',
    sourceUrl, seedPath,
  ], {
    cwd: repoRoot,
    stdio: ['ignore', 'pipe', 'pipe'],
    windowsHide: true,
  });

  // A bare clone commonly stores the branch only in packed-refs, leaving refs/
  // empty. Electron-builder does not preserve empty directories, while Git's
  // repository validation expects refs/ to exist on the installed owner machine.
  // Deleting and recreating the staged branch forces Git to materialize a loose
  // refs/heads/nexus-package-source file without changing the exact commit.
  runGit(['--git-dir', seedPath, 'update-ref', '-d', packageRef], { cwd: repoRoot });
  runGit(['--git-dir', seedPath, 'update-ref', packageRef, head], { cwd: repoRoot });
} finally {
  try { runGit(['update-ref', '-d', packageRef]); } catch {}
}

const looseRefPath = path.join(seedPath, 'refs', 'heads', 'nexus-package-source');
if (!fs.existsSync(looseRefPath)) throw new Error('exact-source seed loose ref is missing');
const looseRef = fs.readFileSync(looseRefPath, 'utf8').trim().toLowerCase();
if (looseRef !== head) throw new Error(`seed loose ref mismatch: expected ${head} got ${looseRef}`);

const seeded = runGit(['--git-dir', seedPath, 'rev-parse', packageRef], { cwd: repoRoot }).toLowerCase();
if (seeded !== head) throw new Error(`seed source mismatch: expected ${head} got ${seeded}`);
if (!fs.existsSync(path.join(seedPath, 'shallow'))) throw new Error('exact-source seed is not shallow bounded');
if (!fs.existsSync(path.join(seedPath, 'objects'))) throw new Error('exact-source seed object database is missing');

process.stdout.write(`NEXUS_PACKAGE_SOURCE_SHA=${head}\n`);
process.stdout.write(`NEXUS_PACKAGE_SOURCE_SEED=${seedPath}\n`);
