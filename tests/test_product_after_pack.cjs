'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { createRequire } = require('node:module');
const { execFileSync } = require('node:child_process');

const product = path.join(__dirname, '../desktop/nexus-product');
const productRequire = createRequire(path.join(product, 'package.json'));
const asar = productRequire('@electron/asar');
const afterPack = productRequire('./after-pack.js');
const sdkManifest = path.join('node_modules', '@modelcontextprotocol', 'sdk', 'package.json');

async function fixture(t, { production = false, version = '1.32.0', missing } = {}) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'nexus-asar-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const app = path.join(root, 'app');
  const resources = path.join(root, 'output', 'resources');
  fs.mkdirSync(resources, { recursive: true });
  const write = (name, content) => {
    const filename = path.join(app, name);
    fs.mkdirSync(path.dirname(filename), { recursive: true });
    fs.writeFileSync(filename, content);
  };
  write('package.json', JSON.stringify({ name: 'nexus-asar-fixture', version: '1.0.0' }));
  for (const name of ['tradingview-bridge.js', 'tradingview-ipc.js']) {
    write(name, fs.readFileSync(path.join(product, name)));
  }
  if (production) {
    const lock = JSON.parse(fs.readFileSync(path.join(product, 'package-lock.json'), 'utf8'));
    const copied = [];
    for (const [name, metadata] of Object.entries(lock.packages)) {
      if (!name.startsWith('node_modules/') || metadata.dev || copied.some(parent => name.startsWith(parent + '/'))) continue;
      fs.cpSync(path.join(product, name), path.join(app, name), { recursive: true });
      copied.push(name);
    }
  } else {
    write(sdkManifest, JSON.stringify({ version }));
    for (const name of ['index.js', 'streamableHttp.js']) {
      write(path.join('node_modules', '@modelcontextprotocol', 'sdk', 'dist', 'cjs', 'client', name), 'module.exports = {};');
    }
  }
  if (missing) fs.rmSync(path.join(app, missing));
  const archive = path.join(resources, 'app.asar');
  await asar.createPackage(app, archive);

  // A real, isolated shallow Git seed keeps the existing bootstrap gates active.
  const seed = path.join(resources, 'nexus-source-seed.git');
  const git = (args, input) => execFileSync('git', [
    '-c', 'user.name=NEXUS Packaging Test', '-c', 'user.email=packaging@example.invalid',
    '--git-dir', seed, ...args,
  ], { encoding: 'utf8', input, stdio: ['pipe', 'pipe', 'pipe'], windowsHide: true }).trim();
  git(['init', '--bare', '--quiet']);
  const tree = git(['mktree'], '');
  const sha = git(['commit-tree', tree], 'Isolated packaging fixture\n');
  git(['update-ref', 'refs/heads/nexus-package-source', sha]);
  git(['symbolic-ref', 'HEAD', 'refs/heads/nexus-package-source']);
  fs.writeFileSync(path.join(seed, 'shallow'), sha + '\n');
  fs.writeFileSync(path.join(resources, 'source-sha.txt'), sha);
  fs.mkdirSync(path.join(resources, 'scripts'));
  for (const name of ['bootstrap_nexus_runner_from_gui.ps1', 'install_nexus_owner_autostart_from_gui.ps1']) {
    fs.writeFileSync(path.join(resources, 'scripts', name), '# Isolated fixture; never executed\n');
  }
  return { root, archive, context: { electronPlatformName: 'win32', appOutDir: path.join(root, 'output') } };
}

test('a real ASAR passes the Windows hook and its pinned SDK dependencies load after extraction', async t => {
  const { root, archive, context } = await fixture(t, { production: true });
  const entries = asar.listPackage(archive).map(name => name.replaceAll('\\', '/'));
  assert.ok(entries.includes('/node_modules/@modelcontextprotocol/sdk/package.json'));
  assert.equal(JSON.parse(asar.extractFile(archive, sdkManifest)).version, '1.32.0');
  if (process.platform === 'win32') {
    // ASAR 3.4.1 splits directory components with path.sep even though listings normalize to '/'.
    assert.throws(() => asar.extractFile(archive, 'node_modules/@modelcontextprotocol/sdk/package.json'), /not found/);
  }
  await afterPack(context);
  const extracted = path.join(root, 'extracted');
  asar.extractAll(archive, extracted);
  const packagedRequire = createRequire(path.join(extracted, 'package.json'));
  assert.equal(typeof packagedRequire('@modelcontextprotocol/sdk/client/index.js').Client, 'function');
  assert.equal(typeof packagedRequire('@modelcontextprotocol/sdk/client/streamableHttp.js').StreamableHTTPClientTransport, 'function');
  assert.equal(typeof packagedRequire('@modelcontextprotocol/sdk/client/auth.js').auth, 'function');
});

test('a missing SDK manifest still rejects packaging when both client files exist', async t => {
  const { context } = await fixture(t, { missing: sdkManifest });
  await assert.rejects(afterPack(context), /package\.json.*not found/);
});

test('an unpinned SDK version still rejects packaging', async t => {
  const { context } = await fixture(t, { version: '0.0.0' });
  await assert.rejects(afterPack(context), /MCP SDK version mismatch/);
});

test('a missing SDK client still rejects packaging', async t => {
  const missing = path.join('node_modules', '@modelcontextprotocol', 'sdk', 'dist', 'cjs', 'client', 'index.js');
  const { context } = await fixture(t, { missing });
  await assert.rejects(afterPack(context), /packaged TradingView connector missing/);
});

test('a missing TradingView connector still rejects packaging', async t => {
  const { context } = await fixture(t, { missing: 'tradingview-bridge.js' });
  await assert.rejects(afterPack(context), /packaged TradingView connector missing/);
});
