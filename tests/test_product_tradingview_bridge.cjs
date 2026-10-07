'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const crypto = require('node:crypto');
const { createTradingViewBridge, callbackCode, checkedURL, queryInput, displayResult, SERVER, ISSUER } =
  require('../desktop/nexus-product/tradingview-bridge');
const { registerTradingViewIpc } = require('../desktop/nexus-product/tradingview-ipc');

function fixture(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'nexus-tv-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const key = crypto.randomBytes(32);
  const encryption = { id: 'test-aes', isAvailable: () => true,
    encrypt: raw => { const iv = crypto.randomBytes(12), cipher = crypto.createCipheriv('aes-256-gcm', key, iv);
      const data = Buffer.concat([cipher.update(raw, 'utf8'), cipher.final()]); return Buffer.concat([iv, cipher.getAuthTag(), data]); },
    decrypt: bytes => { const cipher = crypto.createDecipheriv('aes-256-gcm', key, bytes.subarray(0, 12));
      cipher.setAuthTag(bytes.subarray(12, 28)); return Buffer.concat([cipher.update(bytes.subarray(28)), cipher.final()]).toString(); } };
  return { filename: path.join(root, 'oauth.enc.json'), encryption };
}
class UnauthorizedError extends Error {}
function authorizedFactory(calls, onTools) {
  return ({ provider }) => ({
    async connect() {
      calls.push('connect');
      if (!provider.tokens()) {
        await provider.saveCodeVerifier('proof-verifier');
        await provider.saveClientInformation({ client_id: 'public-client', issuer: ISSUER });
        const url = new URL(ISSUER + '/mcp/oauth/authorize');
        for (const [k, v] of Object.entries({ state: provider.state(), redirect_uri: provider.redirectUrl,
          code_challenge_method: 'S256', code_challenge: 'challenge', scope: 'mcp:read' })) url.searchParams.set(k, v);
        await provider.redirectToAuthorization(url);
        throw new UnauthorizedError();
      }
    },
    async finishAuth(code) { assert.equal(code, 'valid-code'); assert.equal(provider.codeVerifier(), 'proof-verifier');
      provider.saveTokens({ access_token: 'private-access', refresh_token: 'private-refresh', issuer: ISSUER }); },
    async listTools() { return { tools: [{ name: 'get_ohlcv' }, { name: 'get_technicals_rating' }, { name: 'create_alert' }] }; },
    async callTool(name, args) { calls.push({ name, args }); if (onTools) return onTools(name, args);
      return { content: [{ type: 'text', text: '<script>display-only</script>' }] }; },
    async close() { calls.push('close'); }
  });
}
async function authorize(bridge) { const s = await bridge.connect(); assert.equal(s.ready, true); }
const browserCallback = async raw => {
  const u = new URL(raw), callback = new URL(u.searchParams.get('redirect_uri'));
  callback.searchParams.set('state', u.searchParams.get('state')); callback.searchParams.set('code', 'valid-code'); callback.searchParams.set('iss', ISSUER);
  const r = await fetch(callback); assert.equal(r.status, 200);
};

test('status and invalid queries perform no HTTP or browser actions; no plaintext storage fallback', async t => {
  const calls = []; const config = fixture(t);
  const bridge = createTradingViewBridge({ ...config, openBrowser: () => calls.push('browser'), makeSession: () => { calls.push('session'); } });
  assert.equal((await bridge.status()).signed_in, false);
  assert.deepEqual(calls, []);
  await assert.rejects(bridge.snapshot({ symbol: 'BYBIT:ETHUSDT', interval: '4h', count: 100 }), { code: 'sign_in_required' });
  await assert.rejects(bridge.snapshot({ tool: 'create_alert' }), { code: 'invalid_request' });
  assert.deepEqual(calls, []);
  const unavailable = createTradingViewBridge({ ...config, encryption: { isAvailable: () => false } });
  await assert.rejects(unavailable.connect(), { code: 'storage_unavailable' });
  assert.equal(fs.existsSync(config.filename), false);
});

test('OAuth loopback uses state and issuer; tokens survive only encrypted; only two display tools run', async t => {
  const config = fixture(t), calls = [];
  const bridge = createTradingViewBridge({ ...config, openBrowser: browserCallback, makeSession: authorizedFactory(calls) });
  t.after(() => bridge.close()); await authorize(bridge);
  const disk = fs.readFileSync(config.filename, 'utf8');
  for (const secret of ['private-access', 'private-refresh', 'proof-verifier', 'public-client']) assert.equal(disk.includes(secret), false);
  const s = await bridge.snapshot({ symbol: 'BYBIT:ETHUSDT', interval: '4h', count: 100 });
  assert.equal(s.usage, 'human_display_only'); assert.equal(s.source, SERVER);
  assert.equal(s.bars, '<script>display-only</script>');
  assert.deepEqual(calls.filter(x => x.name).map(x => x.name), ['get_ohlcv', 'get_technicals_rating']);
  assert.equal(JSON.stringify(await bridge.status()).includes('private'), false);
  await bridge.disconnect(); assert.equal(fs.existsSync(config.filename), false); assert.equal((await bridge.status()).signed_in, false);
});

test('host, callback path, state, duplicate code and mismatched issuer cannot finish OAuth', () => {
  const options = { redirectUrl: 'http://127.0.0.1:54321/tradingview/callback', state: 'expected' };
  const valid = { method: 'GET', headers: { host: '127.0.0.1:54321' }, url: '/tradingview/callback?state=expected&code=ok' };
  assert.equal(callbackCode(valid, options), 'ok');
  for (const changed of [{ method: 'POST' }, { headers: { host: 'attacker.example' } },
    { url: '/wrong?state=expected&code=ok' }, { url: '/tradingview/callback?state=other&code=ok' },
    { url: valid.url + '&code=second' }, { url: valid.url + '&iss=https%3A%2F%2Fattacker.example' }]) {
    assert.throws(() => callbackCode({ ...valid, ...changed }, options), { code: 'oauth_callback_rejected' });
  }
});

test('discovery URLs and renderer fields cannot introduce credential or account-write destinations', () => {
  for (const raw of ['https://attacker.example/mcp', 'http://mcp.tradingview.com/mcp', 'https://www.tradingview.com/account',
    'https://mcp.tradingview.com/mcp#secret', 'https://secret@mcp.tradingview.com/mcp']) assert.throws(() => checkedURL(raw));
  assert.equal(checkedURL(SERVER).href, SERVER);
  const input = { symbol: 'BYBIT:ETHUSDT', interval: '4h', count: 100 };
  for (const changed of [{ count: 301 }, { count: NaN }, { interval: 'bad' }, { symbol: 'https://evil' },
    { tool: 'create_alert' }, { credentials: 'private' }]) assert.throws(() => queryInput({ ...input, ...changed }), { code: 'invalid_request' });
  assert.throws(() => displayResult({ isError: true, content: [] }));
  assert.throws(() => displayResult({ content: [{ type: 'text', text: 'x'.repeat(200001) }] }));
});

test('cancellation does not persist tokens or establish a connection after the sign-in callback', async t => {
  const config = fixture(t), calls = []; let opened;
  const openedPromise = new Promise(resolve => { opened = resolve; });
  const bridge = createTradingViewBridge({ ...config, makeSession: authorizedFactory(calls), openBrowser: () => opened() });
  const pending = bridge.connect(); await openedPromise; await bridge.cancel();
  await assert.rejects(pending, { code: 'cancelled' });
  assert.equal((await bridge.status()).signed_in, false); assert.equal((await bridge.status()).ready, false);
});

test('an expired account cannot open sign-in automatically during a snapshot', async t => {
  const config = fixture(t), calls = []; let expired = false, browsers = 0;
  const factory = authorizedFactory(calls);
  const bridge = createTradingViewBridge({ ...config, openBrowser: async u => { browsers++; await browserCallback(u); },
    makeSession: options => { const s = factory(options); if (expired) s.connect = async () => options.provider.redirectToAuthorization(new URL(ISSUER)); return s; } });
  await authorize(bridge); await bridge.cancel(); expired = true;
  await assert.rejects(bridge.snapshot({ symbol: 'BYBIT:ETHUSDT', interval: '4h', count: 100 }), { code: 'sign_in_required' });
  assert.equal(browsers, 1); assert.equal((await bridge.status()).ready, false);
});

test('connection proof expires and loss of OS encryption closes the session without more provider calls', async t => {
  const config = fixture(t), calls = []; let available = true, time = Date.parse('2026-10-03T20:00:00Z');
  config.encryption.isAvailable = () => available;
  const bridge = createTradingViewBridge({ ...config, makeSession: authorizedFactory(calls), openBrowser: browserCallback,
    now: () => new Date(time).toISOString() });
  t.after(() => bridge.close()); await authorize(bridge);
  time += 6 * 60 * 1000;
  const before = calls.length;
  const stale = await bridge.status(); assert.equal(stale.ready, false); assert.equal(stale.signed_in, true);
  assert.equal(calls.length, before);
  available = false;
  assert.equal((await bridge.status()).reason, 'storage_unavailable');
  assert.equal(calls.at(-1), 'close');
  await assert.rejects(bridge.snapshot({ symbol: 'BYBIT:ETHUSDT', interval: '4h', count: 100 }), { code: 'storage_unavailable' });
});

test('TradingView IPC rejects child frames, external windows and argument smuggling', async () => {
  const handlers = {}, invoked = [];
  const frame = { url: 'http://127.0.0.1:43210/' }, event = { senderFrame: frame, sender: { mainFrame: frame } };
  registerTradingViewIpc({ app: { isReady: () => true, getPath: () => '/private-user-data', on() {} },
    BrowserWindow: { fromWebContents: () => ({ isDestroyed: () => false }) }, ipcMain: { handle: (key, fn) => { handlers[key] = fn; } },
    safeStorage: {}, shell: {}, getOrigin: () => 'http://127.0.0.1:43210',
    makeBridge: () => Object.fromEntries(['status', 'connect', 'disconnect', 'cancel', 'snapshot'].map(name =>
      [name, async () => { invoked.push(name); return {}; }])) });
  const connect = handlers['nexus:tradingview:connect'];
  assert.equal((await connect({ ...event, senderFrame: { ...frame } })).error.code, 'untrusted_sender');
  assert.equal((await connect(event, { tool: 'create_alert' })).error.code, 'invalid_request');
  frame.url = 'https://attacker.example/'; assert.equal((await connect(event)).error.code, 'untrusted_sender');
  assert.deepEqual(invoked, []); frame.url = 'http://127.0.0.1:43210/'; assert.equal((await connect(event)).ok, true);
});

test('the pinned real MCP SDK completes discovery, PKCE, registration and bounded read calls',
  { skip: !fs.existsSync(path.join(__dirname, '../desktop/nexus-product/node_modules/@modelcontextprotocol/sdk/package.json')) }, async t => {
    const config = fixture(t), requests = [], toolCalls = [];
    const fakeProvider = async (raw, init = {}) => {
      const url = new URL(raw instanceof Request ? raw.url : raw);
      requests.push({ url: url.href, method: init.method || 'GET' });
      const reply = (value, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } });
      if (url.pathname.includes('oauth-protected-resource')) return reply({ resource: SERVER, authorization_servers: [ISSUER] });
      if (url.pathname === '/.well-known/oauth-authorization-server') return reply({ issuer: ISSUER,
        authorization_endpoint: ISSUER + '/mcp/oauth/authorize', token_endpoint: ISSUER + '/mcp/oauth/token',
        registration_endpoint: ISSUER + '/mcp/oauth/register', response_types_supported: ['code'],
        grant_types_supported: ['authorization_code', 'refresh_token'], token_endpoint_auth_methods_supported: ['none'],
        code_challenge_methods_supported: ['S256'] });
      if (url.pathname === '/mcp/oauth/register') {
        const metadata = JSON.parse(init.body); assert.equal(metadata.scope, 'mcp:read');
        assert.match(metadata.redirect_uris[0], /^http:\/\/127\.0\.0\.1:\d+\/tradingview\/callback$/);
        return reply({ ...metadata, client_id: 'sdk-public-client' }, 201);
      }
      if (url.pathname === '/mcp/oauth/token') {
        const params = new URLSearchParams(init.body);
        assert.equal(params.get('code'), 'valid-code'); assert.equal(params.get('grant_type'), 'authorization_code');
        assert.ok(params.get('code_verifier').length >= 43); assert.equal(params.get('resource'), SERVER);
        return reply({ access_token: 'sdk-private-access', refresh_token: 'sdk-private-refresh', token_type: 'Bearer', expires_in: 3600 });
      }
      assert.equal(url.href, SERVER);
      if (init.method === 'GET') return new Response(null, { status: 405 });
      if (new Headers(init.headers).get('Authorization') !== 'Bearer sdk-private-access') {
        return new Response(null, { status: 401, headers: { 'WWW-Authenticate': 'Bearer resource_metadata="https://mcp.tradingview.com/.well-known/oauth-protected-resource/mcp"' } });
      }
      const rpc = JSON.parse(init.body);
      if (rpc.id === undefined) return new Response(null, { status: 202 });
      let result;
      if (rpc.method === 'initialize') result = { protocolVersion: rpc.params.protocolVersion,
        capabilities: { tools: {} }, serverInfo: { name: 'test-official-provider', version: '1.0.0' } };
      else if (rpc.method === 'tools/list') result = { tools: ['get_ohlcv', 'get_technicals_rating', 'create_alert'].map(name =>
        ({ name, inputSchema: { type: 'object' } })) };
      else { assert.equal(rpc.method, 'tools/call'); toolCalls.push(rpc.params.name);
        result = { content: [{ type: 'text', text: '{"provider_market_values":true}' }] }; }
      return reply({ jsonrpc: '2.0', id: rpc.id, result });
    };
    const bridge = createTradingViewBridge({ ...config, fetchImpl: fakeProvider, openBrowser: browserCallback });
    t.after(() => bridge.close()); await authorize(bridge);
    const receipt = await bridge.snapshot({ symbol: 'BYBIT:ETHUSDT', interval: '4h', count: 100 });
    assert.equal(receipt.usage, 'human_display_only');
    assert.deepEqual(toolCalls, ['get_ohlcv', 'get_technicals_rating']);
    assert.ok(requests.some(x => x.url.endsWith('/mcp/oauth/register')));
    assert.equal(fs.readFileSync(config.filename, 'utf8').includes('sdk-private'), false);
  });
