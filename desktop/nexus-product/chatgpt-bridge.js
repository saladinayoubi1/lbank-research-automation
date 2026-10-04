'use strict';

const { createHash } = require('node:crypto');
const MAX_TURNS = 128;
const PROOF_TTL = 600000;
const USAGE_URL = 'https://chatgpt.com/settings/usage';
const SAFE_ERRORS = new Set(['sign_in_required', 'sharing_not_enabled', 'connection_busy',
  'cancelled', 'reauth_required', 'storage_unavailable', 'invalid_id_token', 'account_mismatch',
  'subscription_sharing_usage_limit_exceeded', 'subscription_sharing_usage_unavailable',
  'stream_interrupted', 'response_incomplete', 'invalid_stream', 'invalid_model_catalog',
  'authority_gate_denied', 'unsafe_provider_response', 'invalid_provider_response',
  'invalid_request', 'model_not_available', 'turn_payload_conflict', 'turn_in_progress',
  'advisory_capacity_reached', 'provider_outcome_ambiguous', 'gateway_unavailable']);
const fail = code => { const e = new Error(code); e.code = code; throw e; };
const safeCode = e => SAFE_ERRORS.has(e?.code) ? e.code : 'chatgpt_unavailable';

function validTurn(raw) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw) ||
      Object.keys(raw).sort().join(',') !== 'conversation_id,message,session_id,turn_id') fail('invalid_request');
  for (const key of ['session_id', 'conversation_id', 'turn_id']) {
    if (typeof raw[key] !== 'string' || !/^[a-zA-Z0-9_.:-]{1,128}$/.test(raw[key])) fail('invalid_request');
  }
  if (typeof raw.message !== 'string' || !raw.message.trim() || Buffer.byteLength(raw.message) > 12000) fail('invalid_request');
  return Object.fromEntries(['session_id', 'conversation_id', 'turn_id', 'message'].map(k => [k, raw[k]]));
}

// The SDK and credentials exist only in the trusted local main process.
// No model tool output is interpreted, executed, queued or promoted here.
function createChatGPTBridge({ getClient, postBackend, encryptionAvailable, now = Date.now }) {
  let models = [], catalogProfile = null, proof = null, lastError = null, accountBusy = false;
  let active = null;
  const turns = new Map();
  const clearProof = () => { proof = null; };
  async function status() {
    if (!encryptionAvailable()) {
      models = []; catalogProfile = null; clearProof();
      return { status: 'unavailable', ready: false, connection_verified: false,
        reasons: ['storage_unavailable'], models: [], advisory_only: true, live_trading_authority: false };
    }
    const session = await (await getClient()).getSession();
    if (session.status !== 'connected' || !session.sharing || catalogProfile !== session.profileId) {
      models = []; catalogProfile = null; clearProof();
    }
    const ready = session.status === 'connected' && session.sharing && models.length > 0 && !accountBusy;
    const verified = Boolean(ready && proof?.profile === session.profileId && now() - proof.at < PROOF_TTL);
    return { provider: 'chatgpt', status: verified ? 'connected' : ready ? 'ready_unverified' : session.status,
      ready, signed_in: session.status === 'connected', sharing: Boolean(session.sharing),
      connection_verified: verified, last_verified_at: proof ? new Date(proof.at).toISOString() : null,
      models: models.map(m => ({ slug: m.slug, displayName: m.displayName })), account_busy: accountBusy,
      reasons: lastError ? [lastError] : session.status !== 'connected' ? ['sign_in_required'] :
        !session.sharing ? ['sharing_not_enabled'] : !models.length ? ['models_not_loaded'] : [],
      usage_url: USAGE_URL, billing: 'owner_consented_chatgpt_plan', api_key_required: false,
      advisory_only: true, live_trading_authority: false };
  }
  async function refreshModels() {
    if (accountBusy || active) fail('connection_busy');
    const client = await getClient();
    const session = await client.getSession();
    models = []; catalogProfile = null;
    if (session.status !== 'connected') fail('sign_in_required');
    if (!session.sharing) fail('sharing_not_enabled');
    try {
      const found = await client.listModels({ signal: AbortSignal.timeout(30000) });
      const after = await client.getSession();
      if (after.profileId !== session.profileId || after.status !== 'connected' || !after.sharing) fail('account_mismatch');
      if (!Array.isArray(found) || found.length > 200 || found.some(m =>
        typeof m.slug !== 'string' || !/^[a-zA-Z0-9._:-]{1,200}$/.test(m.slug) ||
        typeof m.displayName !== 'string' || !m.displayName.trim() || m.displayName.length > 200)) fail('invalid_model_catalog');
      models = found.map(m => ({ slug: m.slug, displayName: m.displayName })); catalogProfile = session.profileId;
      lastError = null;
      return await status();
    } catch (e) { clearProof(); lastError = safeCode(e); throw e; }
  }
  async function connect() {
    if (!encryptionAvailable()) fail('storage_unavailable');
    if (accountBusy || active) fail('connection_busy');
    accountBusy = true; models = []; catalogProfile = null; clearProof();
    try { await (await getClient()).signIn({ reconsent: true }); lastError = null; }
    catch (e) { lastError = safeCode(e); throw e; }
    finally { accountBusy = false; }
    const client = await getClient();
    const session = await client.getSession();
    return session.status === 'connected' && session.sharing ? refreshModels() : status();
  }
  async function disconnect() {
    if (accountBusy || active) fail('connection_busy');
    accountBusy = true; models = []; catalogProfile = null; clearProof();
    try { await (await getClient()).disconnect(); lastError = null; }
    finally { accountBusy = false; }
    return status();
  }
  async function ask(raw) {
    if (!raw || Object.keys(raw).sort().join(',') !== 'model,request') fail('invalid_request');
    const request = validTurn(raw.request);
    if (typeof raw.model !== 'string') fail('invalid_request');
    const key = JSON.stringify([request.session_id, request.conversation_id, request.turn_id]);
    const digest = createHash('sha256').update(JSON.stringify({ request, model: raw.model })).digest('hex');
    const previous = turns.get(key);
    if (previous) {
      if (previous.digest !== digest) fail('turn_payload_conflict');
      if (previous.result) {
        const current = await (await getClient()).getSession();
        if (current.profileId !== previous.profile || current.status !== 'connected' || !current.sharing) fail('account_mismatch');
        return previous.result;
      }
      fail(previous.error || 'turn_in_progress');
    }
    if (active || accountBusy) fail('connection_busy');
    const readiness = await status();
    if (!readiness.ready) fail(readiness.reasons[0] || 'sign_in_required');
    if (!models.some(m => m.slug === raw.model)) fail('model_not_available');
    const client = await getClient(), session = await client.getSession();
    const profile = session.profileId;
    if (profile !== catalogProfile) fail('account_mismatch');
    // Recheck after awaits; concurrent turns must not overwrite a reservation.
    if (active || accountBusy || turns.has(key)) fail('turn_in_progress');
    if (turns.size >= MAX_TURNS) fail('advisory_capacity_reached');
    const entry = { digest, profile }; turns.set(key, entry);
    const controller = new AbortController(); active = controller;
    let providerStarted = false;
    try {
      const prepared = await postBackend('/api/product/ai/chatgpt/context', request);
      if (prepared.decision?.allowed !== true || prepared.advisory_only !== true || prepared.state_mutation !== false ||
          prepared.live_trading_authority !== false || !Array.isArray(prepared.input) || prepared.input.length !== 1 ||
          prepared.input[0]?.role !== 'user' || typeof prepared.input[0]?.content !== 'string' ||
          !prepared.input[0].content.startsWith('You are a bounded NEXUS repository reviewer.')) fail('authority_gate_denied');
      providerStarted = true;
      // Official SDK supplies stream:true/store:false, no tools and no retry.
      // Do not display deltas; interrupted/failed/incomplete streams are failures.
      const answer = await client.streamResponse({ model: raw.model, input: prepared.input,
        signal: AbortSignal.any([controller.signal, AbortSignal.timeout(60000)]) });
      const sanitized = await postBackend('/api/product/ai/chatgpt/sanitize', { reply: answer.text });
      const after = await client.getSession();
      if (after.profileId !== profile || after.status !== 'connected' || !after.sharing) fail('account_mismatch');
      if (typeof sanitized.reply !== 'string' || !sanitized.reply.trim() ||
          Buffer.byteLength(sanitized.reply) > 12000 || sanitized.state_mutation !== false ||
          sanitized.live_trading_authority !== false) fail('invalid_provider_response');
      entry.result = { reply: sanitized.reply, provider: 'chatgpt', model: raw.model, source: 'external_advisory',
        intent: prepared.intent, decision: prepared.decision, context_digest: prepared.context_digest,
        advisory_only: true, state_mutation: false, live_trading_authority: false,
        privacy: { raw_message_egressed: false, paper_account_egressed: false, server_persisted_transcript: false } };
      proof = { profile, at: now() }; lastError = null;
      return entry.result;
    } catch (e) {
      clearProof(); lastError = safeCode(e);
      entry.error = providerStarted ? 'provider_outcome_ambiguous' : lastError;
      throw e;
    } finally { active = null; }
  }
  return { status, connect, disconnect, refreshModels, ask,
    cancel: async () => { active?.abort(); (await getClient()).cancelSignIn(); },
    close: () => { active?.abort(); } };
}

module.exports = { createChatGPTBridge, safeCode, USAGE_URL };
