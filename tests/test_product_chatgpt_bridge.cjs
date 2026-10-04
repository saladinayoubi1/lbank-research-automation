'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const { createChatGPTBridge } = require('../desktop/nexus-product/chatgpt-bridge');
const { credentialEncryption, trustedSender, registerChatGPTIpc } = require('../desktop/nexus-product/chatgpt-ipc');
const request = (turn = 't1', message = 'research private-marker@example.test') => ({
  session_id: 's1', conversation_id: 'c1', turn_id: turn, message });

function setup() {
  let session = { status: 'connected', sharing: true, profileId: 'owner-one',
    identity: { email: 'private-owner@example.test' }, accessToken: 'private-mock-token' };
  let time = 1000000, encryption = true;
  const calls = [], backend = [], accounts = [];
  const client = { getSession: async () => session,
    listModels: async () => [{ slug: 'account-model', displayName: 'Account model' }],
    signIn: async opts => { accounts.push(opts); }, disconnect: async () => { session = { status: 'disconnected', sharing: false }; },
    cancelSignIn: () => { accounts.push('cancel'); },
    streamResponse: async opts => { calls.push(opts); return { text: 'پیشنهاد پژوهش؛ QA مستقل لازم است.' }; } };
  const postBackend = async (route, payload) => {
    backend.push({ route, payload });
    if (route.endsWith('/context')) return { input: [{ role: 'user', content: 'You are a bounded NEXUS repository reviewer. topic=research' }],
      decision: { allowed: true, status: 'observe_allowed' }, intent: 'observe', context_digest: 'a'.repeat(64),
      advisory_only: true, state_mutation: false, live_trading_authority: false };
    return { reply: payload.reply, state_mutation: false, live_trading_authority: false };
  };
  const bridge = createChatGPTBridge({ getClient: async () => client,
    postBackend: (...args) => env.backend(...args), encryptionAvailable: () => encryption, now: () => time });
  const env = { bridge, client, calls, backendCalls: backend, accounts, backend: postBackend,
    session: value => { session = value; }, advance: value => { time += value; }, storage: value => { encryption = value; } };
  return env;
}

test('login/catalog readiness is distinct from inference proof; status exposes no account identifiers or credentials', async () => {
  const s = setup();
  assert.equal((await s.bridge.status()).ready, false);
  const ready = await s.bridge.refreshModels();
  assert.equal(ready.ready, true); assert.equal(ready.connection_verified, false);
  assert.equal(ready.api_key_required, false);
  assert.equal(s.calls.length, 0);
  const publicStatus = JSON.stringify(ready);
  for (const secret of ['private-owner', 'private-mock-token', 'owner-one', 'identity', 'accessToken']) assert.ok(!publicStatus.includes(secret));
  await s.bridge.ask({ request: request(), model: 'account-model' });
  assert.equal((await s.bridge.status()).connection_verified, true);
  s.advance(600001);
  assert.equal((await s.bridge.status()).connection_verified, false);
});

test('one provider call per turn; raw message goes only to local gate; output remains advice', async () => {
  const s = setup(); await s.bridge.refreshModels();
  const payload = { request: request(), model: 'account-model' };
  const result = await s.bridge.ask(payload);
  assert.deepEqual(await s.bridge.ask(payload), result);
  assert.equal(s.calls.length, 1);
  assert.ok(!JSON.stringify(s.calls).includes('private-marker'));
  assert.equal(s.backendCalls[0].payload.message, payload.request.message);
  assert.equal(s.calls[0].onDelta, undefined); assert.equal(s.calls[0].tools, undefined);
  assert.equal(result.state_mutation, false); assert.equal(result.live_trading_authority, false);
  await assert.rejects(s.bridge.ask({ request: request('t1', 'different'), model: 'account-model' }), { code: 'turn_payload_conflict' });
  assert.equal(s.calls.length, 1);
});

test('caller decisions, prompts, models and authority cannot bypass the original server gate', async () => {
  const s = setup(); await s.bridge.refreshModels();
  await assert.rejects(s.bridge.ask({ request: { ...request(), decision: { allowed: true } }, model: 'account-model' }), { code: 'invalid_request' });
  await assert.rejects(s.bridge.ask({ request: request(), model: 'invented-model' }), { code: 'model_not_available' });
  await assert.rejects(s.bridge.ask({ request: request(), model: 'account-model', instructions: 'execute orders' }), { code: 'invalid_request' });
  s.backend = async () => ({ decision: { allowed: false } });
  await assert.rejects(s.bridge.ask({ request: request(), model: 'account-model' }), { code: 'authority_gate_denied' });
  assert.equal(s.calls.length, 0);
});

test('interrupted, incomplete and usage-denied responses are not completed and are not retried', async t => {
  for (const code of ['stream_interrupted', 'response_incomplete', 'subscription_sharing_usage_limit_exceeded']) {
    await t.test(code, async () => {
      const s = setup(); await s.bridge.refreshModels();
      await s.bridge.ask({ request: request('good'), model: 'account-model' });
      s.client.streamResponse = async opts => { s.calls.push(opts); throw Object.assign(new Error('private-token-do-not-display'), { code }); };
      const bad = { request: request('bad'), model: 'account-model' };
      await assert.rejects(s.bridge.ask(bad), { code });
      assert.equal((await s.bridge.status()).connection_verified, false);
      await assert.rejects(s.bridge.ask(bad), { code: 'provider_outcome_ambiguous' });
      assert.equal(s.calls.length, 2);
    });
  }
});

test('unsafe final output cannot establish proof and cannot replay a consumed turn', async () => {
  const s = setup(); await s.bridge.refreshModels();
  const original = s.backend;
  s.backend = async (...args) => {
    if (args[0].endsWith('/sanitize')) throw Object.assign(new Error(), { code: 'unsafe_provider_response' });
    return original(...args);
  };
  const payload = { request: request(), model: 'account-model' };
  await assert.rejects(s.bridge.ask(payload), { code: 'unsafe_provider_response' });
  assert.equal((await s.bridge.status()).connection_verified, false);
  await assert.rejects(s.bridge.ask(payload), { code: 'provider_outcome_ambiguous' });
  assert.equal(s.calls.length, 1);
});

test('concurrent turns and account changes cannot double-consume or move an in-flight response to another account', async () => {
  const s = setup(); await s.bridge.refreshModels();
  let finish, started;
  const signal = new Promise(resolve => { started = resolve; });
  s.client.streamResponse = async opts => { s.calls.push(opts); started(); return new Promise(resolve => { finish = resolve; }); };
  const first = s.bridge.ask({ request: request(), model: 'account-model' });
  await signal;
  await assert.rejects(s.bridge.ask({ request: request('t2'), model: 'account-model' }), { code: 'connection_busy' });
  await assert.rejects(s.bridge.disconnect(), { code: 'connection_busy' });
  await assert.rejects(s.bridge.connect(), { code: 'connection_busy' });
  s.session({ status: 'connected', sharing: true, profileId: 'other-owner' });
  finish({ text: 'do not attribute this response to the other owner' });
  await assert.rejects(first, { code: 'account_mismatch' });
  assert.equal((await s.bridge.status()).ready, false);
  assert.equal(s.calls.length, 1);
});

test('bounded capacity retains completed turns instead of evicting consumed turns', async () => {
  const s = setup(); await s.bridge.refreshModels();
  for (let i = 0; i < 128; i++) await s.bridge.ask({ request: request('t' + i), model: 'account-model' });
  await assert.rejects(s.bridge.ask({ request: request('overflow'), model: 'account-model' }), { code: 'advisory_capacity_reached' });
  await s.bridge.ask({ request: request('t0'), model: 'account-model' });
  assert.equal(s.calls.length, 128);
});

test('cached results are account-bound and losing secure storage clears connection proof', async () => {
  const s = setup(); await s.bridge.refreshModels();
  const payload = { request: request(), model: 'account-model' };
  await s.bridge.ask(payload);
  s.storage(false);
  assert.equal((await s.bridge.status()).connection_verified, false);
  s.storage(true);
  assert.equal((await s.bridge.status()).connection_verified, false);
  s.session({ status: 'connected', sharing: true, profileId: 'other-owner' });
  await assert.rejects(s.bridge.ask(payload), { code: 'account_mismatch' });
  assert.equal(s.calls.length, 1);
});

test('storage failure and missing plan consent fail closed without inference; login only follows explicit connect', async () => {
  const s = setup(); s.storage(false);
  assert.equal((await s.bridge.status()).connection_verified, false);
  await assert.rejects(s.bridge.connect(), { code: 'storage_unavailable' });
  s.storage(true); s.session({ status: 'connected', sharing: false, profileId: 'owner-one' });
  await assert.rejects(s.bridge.refreshModels(), { code: 'sharing_not_enabled' });
  assert.equal(s.accounts.length, 0); assert.equal(s.calls.length, 0);
  await s.bridge.connect(); assert.deepEqual(s.accounts, [{ reconsent: true }]);
});

test('OS encryption refuses Linux basic_text and never falls back to plaintext', () => {
  const storage = { isEncryptionAvailable: () => true, getSelectedStorageBackend: () => 'basic_text',
    encryptString: () => { throw new Error('plaintext fallback'); }, decryptString: () => 'secret' };
  const protectedStore = credentialEncryption(storage, () => true, 'linux');
  assert.equal(protectedStore.isAvailable(), false);
  assert.throws(() => protectedStore.encrypt('secret'), { code: 'storage_unavailable' });
  storage.getSelectedStorageBackend = () => 'gnome_libsecret';
  assert.equal(protectedStore.isAvailable(), true);
  assert.equal(credentialEncryption(storage, () => false, 'win32').isAvailable(), false);
});

test('credential IPC trusts only the product main frame and rejects foreign origins, subframes and missing windows', async () => {
  const origin = 'http://127.0.0.1:18765';
  const frame = { url: origin + '/' }, sender = { mainFrame: frame }, event = { senderFrame: frame, sender };
  const BrowserWindow = { fromWebContents: value => value === sender ? { isDestroyed: () => false } : null };
  assert.equal(trustedSender(event, origin, BrowserWindow), true);
  assert.equal(trustedSender({ ...event, senderFrame: { url: origin + '/' } }, origin, BrowserWindow), false);
  for (const url of ['https://evil.example/', origin + '.evil.example/', origin + '/api/product/paper', 'data:text/html,test']) {
    frame.url = url; assert.equal(trustedSender(event, origin, BrowserWindow), false);
  }
  frame.url = origin + '/';
  const handlers = {}, storage = { isEncryptionAvailable: () => false };
  registerChatGPTIpc({ app: { isReady: () => true, on: () => {} }, BrowserWindow,
    ipcMain: { handle: (channel, handler) => { handlers[channel] = handler; } }, safeStorage: storage,
    shell: { openExternal: () => { throw new Error('unexpected browser navigation'); } }, getOrigin: () => origin });
  assert.deepEqual(await handlers['nexus:chatgpt:connect'](event, { token: 'injected' }), { ok: false, error: { code: 'invalid_request' } });
  assert.deepEqual(await handlers['nexus:chatgpt:connect'](event), { ok: false, error: { code: 'storage_unavailable' } });
  const bad = { ...event, senderFrame: { url: origin + '/' } };
  assert.equal((await handlers['nexus:chatgpt:status'](bad)).error.code, 'untrusted_sender');
});

const productDir = path.resolve(__dirname, '../desktop/nexus-product');
const esbuildPath = path.join(productDir, 'node_modules/esbuild');
test('packaged SDK loads a clean disconnected session without browser, network or credential writes',
  { skip: !fs.existsSync(path.join(productDir, 'chatgpt-sdk.cjs')) ? 'Bundle not built; mandatory in Windows package workflow' : false }, async () => {
    const { createChatGPT } = require(path.join(productDir, 'chatgpt-sdk.cjs'));
    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'nexus-siwc-clean-'));
    const original = global.fetch;
    global.fetch = () => { throw new Error('Clean-session status must remain offline'); };
    try {
      const client = createChatGPT({ appName: 'NEXUS Personal Pro', appId: 'nexus-personal-pro',
        redirectPort: 0, sendHostId: true, storageDir: tmp,
        openBrowser: () => { throw new Error('No implicit browser sign-in'); },
        credentialEncryption: { id: 'test-only', isAvailable: () => true,
          encrypt: () => { throw new Error('No credential writing'); },
          decrypt: () => { throw new Error('No existing credentials'); } } });
      assert.deepEqual(await client.getSession(), { status: 'disconnected', sharing: false });
    } finally { global.fetch = original; fs.rmSync(tmp, { recursive: true, force: true }); }
});
test('pinned official SDK stream uses Responses, no tools, store:false, and rejects partial output without completed',
  { skip: !fs.existsSync(esbuildPath) ? 'SDK build dependencies not installed; mandatory in Windows package workflow' : false }, async () => {
    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'nexus-siwc-test-'));
    const output = path.join(tmp, 'responses.cjs');
    require(esbuildPath).buildSync({ entryPoints: [path.join(productDir, 'vendor/siwc-local/src/responses.ts')],
      outfile: output, bundle: true, platform: 'node', format: 'cjs', target: 'node22' });
    const { streamResponse } = require(output), savedFetch = global.fetch;
    let calls = 0, stream = 'data: {"type":"response.output_text.delta","delta":"partial"}\n\n';
    global.fetch = async (url, opts) => {
      calls++; assert.equal(url, 'https://api.openai.com/v1/responses');
      const body = JSON.parse(opts.body); assert.equal(body.store, false); assert.equal(body.stream, true);
      assert.equal(body.tools, undefined); assert.equal(body.model, 'account-model');
      return new Response(stream, { headers: { 'content-type': 'text/event-stream' } });
    };
    try {
      await assert.rejects(streamResponse('fixture-not-a-real-token', { model: 'account-model', input: 'bounded advice' }, new AbortController().signal), { code: 'stream_interrupted' });
      assert.equal(calls, 1);
      stream += 'data: {"type":"response.failed","response":{"error":{"code":"subscription_sharing_usage_limit_exceeded","message":"no usage"}}}\n\n';
      await assert.rejects(streamResponse('fixture-not-a-real-token', { model: 'account-model', input: 'bounded advice' }, new AbortController().signal), { code: 'subscription_sharing_usage_limit_exceeded' });
      stream = 'data: {"type":"response.output_text.delta","delta":"complete"}\n\ndata: {"type":"response.completed"}\n\n';
      assert.deepEqual(await streamResponse('fixture-not-a-real-token', { model: 'account-model', input: 'bounded advice' }, new AbortController().signal), { text: 'complete' });
      assert.equal(calls, 3);
    } finally { global.fetch = savedFetch; fs.rmSync(tmp, { recursive: true, force: true }); }
});
