'use strict';
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const crypto = require('node:crypto');

const SERVER = 'https://mcp.tradingview.com/mcp';
const ISSUER = 'https://www.tradingview.com';
const INTERVALS = new Set(['1m', '5m', '15m', '30m', '1h', '4h', '1D', '1W', '1M']);
const fail = code => Object.assign(new Error(code), { code });
const ERROR_CODES = new Set(['storage_unavailable', 'invalid_request', 'connection_busy', 'sign_in_required',
  'cancelled', 'sign_in_timeout', 'callback_unavailable', 'oauth_callback_rejected', 'oauth_destination_rejected',
  'provider_destination_rejected', 'provider_response_rejected', 'provider_unavailable', 'tool_unavailable']);
const safeError = e => ERROR_CODES.has(e?.code) ? e.code : 'provider_unavailable';

function queryInput(value) {
  if (!value || Object.getPrototypeOf(value) !== Object.prototype ||
      Object.keys(value).sort().join(',') !== 'count,interval,symbol' ||
      typeof value.symbol !== 'string' || !/^[A-Z0-9_]{2,24}:[A-Z0-9_.!\-]{2,40}$/.test(value.symbol) ||
      !INTERVALS.has(value.interval) || !Number.isInteger(value.count) || value.count < 1 || value.count > 300) {
    throw fail('invalid_request');
  }
  return { symbol: value.symbol, interval: value.interval, count: value.count };
}

// All HTTP/OAuth destinations are fixed; provider discovery cannot redirect credentials elsewhere.
function checkedURL(raw) {
  const url = new URL(raw instanceof Request ? raw.url : raw);
  if (url.username || url.password || url.hash || url.protocol !== 'https:') throw fail('provider_destination_rejected');
  const mcp = url.origin === 'https://mcp.tradingview.com' &&
    ['/mcp', '/.well-known/oauth-protected-resource/mcp', '/.well-known/oauth-protected-resource'].includes(url.pathname);
  const oauth = url.origin === ISSUER &&
    ['/mcp/oauth/register', '/mcp/oauth/token', '/mcp/oauth/jwks.json',
      '/.well-known/oauth-authorization-server', '/.well-known/openid-configuration'].includes(url.pathname);
  if (!mcp && !oauth) throw fail('provider_destination_rejected');
  return url;
}

function encryptedStore(filename, encryption) {
  let cached;
  const requireStorage = () => { if (!encryption.isAvailable()) throw fail('storage_unavailable'); };
  return {
    read() {
      requireStorage();
      if (cached) return cached;
      try {
        if (fs.statSync(filename).size > 262144) throw fail('storage_unavailable');
        const wrapper = JSON.parse(fs.readFileSync(filename, 'utf8'));
        if (wrapper.version !== 1 || wrapper.encryption !== encryption.id) throw fail('storage_unavailable');
        cached = JSON.parse(encryption.decrypt(Buffer.from(wrapper.ciphertext, 'base64')));
        if (!cached || typeof cached !== 'object' || Array.isArray(cached)) throw fail('storage_unavailable');
      } catch (e) { if (e.code !== 'ENOENT') throw fail('storage_unavailable'); cached = {}; }
      return cached;
    },
    write(value) {
      requireStorage();
      fs.mkdirSync(path.dirname(filename), { recursive: true, mode: 0o700 });
      const body = JSON.stringify({ version: 1, encryption: encryption.id,
        ciphertext: encryption.encrypt(JSON.stringify(value)).toString('base64') });
      const temp = filename + '.' + crypto.randomUUID() + '.tmp';
      try { fs.writeFileSync(temp, body, { mode: 0o600, flag: 'wx' }); fs.renameSync(temp, filename); cached = value; }
      finally { try { fs.unlinkSync(temp); } catch {} }
    },
    clear() { requireStorage(); try { fs.unlinkSync(filename); } catch (e) { if (e.code !== 'ENOENT') throw e; } cached = {}; }
  };
}

function callbackCode(request, { redirectUrl, state }) {
  if (request.method !== 'GET' || request.headers.host !== new URL(redirectUrl).host || request.url.length > 8192) {
    throw fail('oauth_callback_rejected');
  }
  const url = new URL(request.url, redirectUrl);
  if (url.origin !== new URL(redirectUrl).origin || url.pathname !== '/tradingview/callback' ||
      url.searchParams.getAll('state').length !== 1 || url.searchParams.get('state') !== state ||
      url.searchParams.has('error') || url.searchParams.getAll('code').length !== 1 ||
      !url.searchParams.get('code') || url.searchParams.get('code').length > 4096 ||
      (url.searchParams.has('iss') && (url.searchParams.getAll('iss').length !== 1 || url.searchParams.get('iss') !== ISSUER))) {
    throw fail('oauth_callback_rejected');
  }
  return url.searchParams.get('code');
}

function displayResult(result) {
  if (!result || result.isError || Buffer.byteLength(JSON.stringify(result)) > 200000) throw fail('provider_response_rejected');
  // No provider instruction, link, image or executable HTML is dispatched to another component.
  if (result.structuredContent && typeof result.structuredContent === 'object') return JSON.stringify(result.structuredContent, null, 2);
  const text = (result.content || []).filter(x => x.type === 'text' && typeof x.text === 'string').map(x => x.text).join('\n');
  if (!text || text.length > 180000) throw fail('provider_response_rejected');
  return text;
}

function createTradingViewBridge({ filename, encryption, openBrowser, fetchImpl = fetch, makeSession,
  authTimeoutMs = 120000, now = () => new Date().toISOString() }) {
  const store = encryptedStore(filename, encryption);
  let session = null, flow = null, busy = false, verifiedAt = null, cancelled = false;
  const persist = (key, value) => store.write({ ...store.read(), [key]: value });
  const provider = {
    get redirectUrl() { return flow?.redirectUrl; },
    get clientMetadata() { return { client_name: 'NEXUS AI Room human analytics', redirect_uris: [flow?.redirectUrl],
      grant_types: ['authorization_code', 'refresh_token'], response_types: ['code'], token_endpoint_auth_method: 'none', scope: 'mcp:read' }; },
    state() { if (!flow) throw fail('sign_in_required'); return flow.state; },
    clientInformation: () => store.read().client,
    saveClientInformation: info => persist('client', info),
    tokens: () => store.read().tokens,
    saveTokens: tokens => { if (cancelled) throw fail('cancelled'); persist('tokens', tokens); },
    saveCodeVerifier: verifier => { if (!flow) throw fail('sign_in_required'); flow.verifier = verifier; },
    codeVerifier: () => { if (!flow?.verifier) throw fail('sign_in_required'); return flow.verifier; },
    validateResourceURL: (serverUrl, resource) => {
      if (String(serverUrl) !== SERVER || String(resource) !== SERVER) throw fail('provider_destination_rejected');
      return new URL(SERVER);
    },
    invalidateCredentials: scope => {
      const x = { ...store.read() };
      if (scope === 'all' || scope === 'client') delete x.client;
      if (scope === 'all' || scope === 'tokens') delete x.tokens;
      if (scope === 'all' || scope === 'verifier') { if (flow) flow.verifier = null; }
      store.write(x);
    },
    redirectToAuthorization: async url => {
      if (!flow || flow.cancelled) throw fail('sign_in_required');
      if (url.origin !== ISSUER || url.pathname !== '/mcp/oauth/authorize' || url.username || url.password || url.hash ||
          url.searchParams.getAll('state').length !== 1 || url.searchParams.get('state') !== flow.state ||
          url.searchParams.get('redirect_uri') !== flow.redirectUrl || url.searchParams.get('code_challenge_method') !== 'S256' ||
          !url.searchParams.get('code_challenge')) throw fail('oauth_destination_rejected');
      if (url.searchParams.get('scope') !== 'mcp:read') throw fail('oauth_destination_rejected');
      // One explicit click can open the official sign-in page once, never a retry loop.
      if (flow.opened) throw fail('sign_in_required');
      flow.opened = true;
      await openBrowser(url.href);
    }
  };
  const guardedFetch = async (raw, init = {}) => {
    checkedURL(raw);
    return fetchImpl(raw, { ...init, redirect: 'error', signal: AbortSignal.any(
      [AbortSignal.timeout(20000), ...(init.signal ? [init.signal] : [])]) });
  };
  const sessionFactory = makeSession || (() => {
    const { Client } = require('@modelcontextprotocol/sdk/client/index.js');
    const { StreamableHTTPClientTransport } = require('@modelcontextprotocol/sdk/client/streamableHttp.js');
    const transport = new StreamableHTTPClientTransport(new URL(SERVER), { authProvider: provider, fetch: guardedFetch,
      redirectPolicy: 'same-origin', reconnectionOptions: { maxRetries: 0, initialReconnectionDelay: 1000,
        maxReconnectionDelay: 1000, reconnectionDelayGrowFactor: 1 } });
    const client = new Client({ name: 'nexus-ai-room-display', version: '1.0.0' }, { capabilities: {} });
    client.onclose = () => { verifiedAt = null; };
    client.onerror = () => { verifiedAt = null; };
    return { connect: () => client.connect(transport, { timeout: 20000 }), finishAuth: code => transport.finishAuth(code),
      listTools: () => client.listTools({}, { timeout: 20000 }),
      callTool: (name, args) => client.callTool({ name, arguments: args }, undefined, { timeout: 20000 }), close: () => client.close() };
  });
  const dropSession = async () => { const old = session; session = null; verifiedAt = null; if (old) { try { await old.close(); } catch {} } };
  const status = async () => {
    if (!encryption.isAvailable()) {
      await dropSession();
      return { available: false, signed_in: false, ready: false, reason: 'storage_unavailable' };
    }
    const signedIn = Boolean(store.read().tokens?.access_token);
    const age = Date.parse(now()) - Date.parse(verifiedAt);
    return { available: true, signed_in: signedIn, ready: Boolean(session && verifiedAt && age >= 0 && age <= 300000), busy,
      verified_at: verifiedAt, source: SERVER, usage: 'human_display_only' };
  };
  const establish = async () => {
    const candidate = sessionFactory({ provider, fetch: guardedFetch });
    try { await candidate.connect(); if (cancelled) throw fail('cancelled'); return candidate; }
    catch (e) { try { await candidate.close(); } catch {} throw e; }
  };
  const connect = async () => {
    if (busy) throw fail('connection_busy');
    store.read(); busy = true; cancelled = false;
    let listener, timer, callbackResolve, callbackReject;
    const callback = new Promise((resolve, reject) => { callbackResolve = resolve; callbackReject = reject; });
    // Mark the promise handled while discovery/registration is in progress.
    callback.catch(() => {});
    try {
      await dropSession();
      const currentFlow = { state: crypto.randomBytes(32).toString('hex'), verifier: null, opened: false };
      flow = currentFlow;
      listener = http.createServer((req, res) => {
        try {
          const code = callbackCode(req, currentFlow);
          if (!currentFlow.opened || currentFlow.used || currentFlow.cancelled) throw fail('oauth_callback_rejected');
          currentFlow.used = true;
          res.writeHead(200, { 'Content-Type': 'text/plain; charset=utf-8', 'Cache-Control': 'no-store', 'Content-Security-Policy': "default-src 'none'" });
          res.end('TradingView authorization received. Return to NEXUS.'); callbackResolve(code);
        } catch { res.writeHead(400, { 'Content-Type': 'text/plain', 'Cache-Control': 'no-store' }); res.end('Authorization callback rejected.'); }
      });
      listener.requestTimeout = 5000; listener.headersTimeout = 5000;
      await new Promise((resolve, reject) => { listener.once('error', () => reject(fail('callback_unavailable')));
        listener.listen(store.read().port || 0, '127.0.0.1', resolve); });
      currentFlow.redirectUrl = 'http://127.0.0.1:' + listener.address().port + '/tradingview/callback';
      persist('port', listener.address().port);
      timer = setTimeout(() => callbackReject(fail('sign_in_timeout')), authTimeoutMs); timer.unref();
      currentFlow.cancel = () => { currentFlow.cancelled = true; callbackReject(fail('cancelled')); };
      try { session = await establish(); }
      catch (e) {
        if (e?.constructor?.name !== 'UnauthorizedError' || !currentFlow.opened) throw e;
        const code = await callback;
        const exchange = sessionFactory({ provider, fetch: guardedFetch });
        try { await exchange.finishAuth(code); } finally { try { await exchange.close(); } catch {} }
        session = await establish();
      }
      if (currentFlow.cancelled) throw fail('cancelled');
      verifiedAt = now();
      return await status();
    } catch (e) { await dropSession(); throw e; }
    finally { clearTimeout(timer); listener?.close(); listener?.closeAllConnections(); flow = null; busy = false; }
  };
  const cancel = async () => { cancelled = true; flow?.cancel?.(); await dropSession(); return { cancelled: true }; };
  const disconnect = async () => {
    if (busy) throw fail('connection_busy');
    await dropSession(); store.clear(); return await status();
  };
  const snapshot = async input => {
    const args = queryInput(input);
    if (busy) throw fail('connection_busy');
    if (!store.read().tokens?.access_token) throw fail('sign_in_required');
    busy = true; cancelled = false;
    try {
      if (!session) session = await establish();
      const available = new Set((await session.listTools()).tools.map(t => t.name));
      if (!available.has('get_ohlcv') || !available.has('get_technicals_rating')) throw fail('tool_unavailable');
      const bars = displayResult(await session.callTool('get_ohlcv', args));
      const technicals = displayResult(await session.callTool('get_technicals_rating', { symbol: args.symbol, interval: args.interval }));
      if (cancelled) throw fail('cancelled');
      const receivedAt = now(); verifiedAt = receivedAt;
      return { source: SERVER, symbol: args.symbol, interval: args.interval, requested_count: args.count,
        received_at: receivedAt, usage: 'human_display_only', bars, technicals };
    } catch (e) { await dropSession(); throw e; } finally { busy = false; }
  };
  return { status, connect, cancel, disconnect, snapshot, close: cancel };
}
module.exports = { createTradingViewBridge, queryInput, checkedURL, callbackCode, displayResult, safeError, SERVER, ISSUER };
