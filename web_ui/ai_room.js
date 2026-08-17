(() => {
  'use strict';

  const room = document.querySelector('[data-surface="ai"]');
  if (!room) return;

  const API_CONTRACT = 'nexus.dashboard.read.v1';
  const ROOM_CONTRACT = 'nexus.ai-room.v1';
  const STORAGE_KEY = 'nexus.ai-room.session.v1';
  const MAX_HISTORY = 40;
  const MAX_MESSAGE = 8000;

  function identifier(prefix) {
    if (globalThis.crypto && typeof globalThis.crypto.randomUUID === 'function') {
      return `${prefix}-${globalThis.crypto.randomUUID()}`;
    }
    return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }

  function freshState() {
    return {
      sessionId: identifier('session'),
      conversationId: identifier('conversation'),
      turn: 0,
      messages: [],
    };
  }

  function restoreState() {
    try {
      const parsed = JSON.parse(sessionStorage.getItem(STORAGE_KEY) || 'null');
      if (!parsed || typeof parsed !== 'object') return freshState();
      if (typeof parsed.sessionId !== 'string' || typeof parsed.conversationId !== 'string') return freshState();
      const messages = Array.isArray(parsed.messages)
        ? parsed.messages.slice(-MAX_HISTORY).filter((item) => item && ['user', 'assistant'].includes(item.role) && typeof item.text === 'string')
        : [];
      return {
        sessionId: parsed.sessionId.slice(0, 160),
        conversationId: parsed.conversationId.slice(0, 160),
        turn: Number.isInteger(parsed.turn) && parsed.turn >= 0 ? parsed.turn : 0,
        messages,
      };
    } catch (_) {
      return freshState();
    }
  }

  let chatState = restoreState();

  function persist() {
    const bounded = {...chatState, messages: chatState.messages.slice(-MAX_HISTORY)};
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(bounded));
    } catch (_) {
      // Browser storage is optional; failure never changes server/control authority.
    }
  }

  const existingGrid = room.querySelector('.workspace-grid');
  const workspace = document.createElement('div');
  workspace.className = 'ai-room-layout';

  const main = document.createElement('article');
  main.className = 'panel ai-room-main';
  const top = document.createElement('div');
  top.className = 'ai-room-top';
  const titleWrap = document.createElement('div');
  const title = document.createElement('h3');
  title.textContent = 'NEXUS AI Room';
  const subtitle = document.createElement('small');
  subtitle.textContent = 'Session-bound · policy-gated · paper/research only';
  titleWrap.append(title, subtitle);
  const newSession = document.createElement('button');
  newSession.type = 'button';
  newSession.className = 'ai-room-secondary';
  newSession.textContent = 'New session';
  top.append(titleWrap, newSession);

  const log = document.createElement('div');
  log.className = 'ai-room-log';
  log.setAttribute('aria-live', 'polite');

  const form = document.createElement('form');
  form.className = 'ai-room-form';
  const input = document.createElement('textarea');
  input.name = 'message';
  input.rows = 3;
  input.maxLength = MAX_MESSAGE;
  input.placeholder = 'Ask NEXUS to inspect, propose, stage a paper action, or route a bounded workflow…';
  input.autocomplete = 'off';
  const actions = document.createElement('div');
  actions.className = 'ai-room-form-actions';
  const hint = document.createElement('small');
  hint.textContent = 'Raw history stays in this browser session. No external AI provider is called from this endpoint.';
  const send = document.createElement('button');
  send.type = 'submit';
  send.textContent = 'Send';
  actions.append(hint, send);
  form.append(input, actions);
  main.append(top, log, form);

  const side = document.createElement('article');
  side.className = 'panel ai-room-side';
  const gateTitle = document.createElement('h3');
  gateTitle.textContent = 'Authority / Runtime';
  const gate = document.createElement('dl');
  gate.className = 'ai-room-gate';
  const runtime = document.createElement('div');
  runtime.className = 'ai-room-runtime';
  side.append(gateTitle, gate, runtime);

  workspace.append(main, side);
  if (existingGrid) existingGrid.replaceWith(workspace);
  else room.append(workspace);

  function gateRow(label, value) {
    const row = document.createElement('div');
    const dt = document.createElement('dt');
    const dd = document.createElement('dd');
    dt.textContent = label;
    dd.textContent = value;
    row.append(dt, dd);
    return row;
  }

  function renderGate(result = null) {
    gate.replaceChildren();
    gate.append(
      gateRow('L0–L1', 'Observe / propose'),
      gateRow('L2', 'Paper proposal only'),
      gateRow('L3', 'Bounded reversible route'),
      gateRow('L4', 'Owner required'),
      gateRow('State mutation', 'OFF in chat endpoint'),
    );
    runtime.replaceChildren();
    if (!result) {
      const p = document.createElement('p');
      p.className = 'muted';
      p.textContent = 'No evaluated turn yet.';
      runtime.append(p);
      return;
    }
    const decision = result.decision || {};
    const operations = result.operations || {};
    const facts = [
      ['Intent', result.intent || 'unknown'],
      ['Decision', decision.status || 'blocked'],
      ['Authority', `L${Number(decision.authority_level ?? 0)}`],
      ['Route', decision.route || 'none'],
      ['Mission', operations.mission_status || 'unknown'],
      ['Agents', String(Array.isArray(operations.agents) ? operations.agents.length : 0)],
      ['Runners', String(Array.isArray(operations.runners) ? operations.runners.length : 0)],
      ['External provider', result.privacy?.external_provider_called ? 'ON' : 'OFF'],
    ];
    for (const [label, value] of facts) {
      const line = document.createElement('div');
      const strong = document.createElement('strong');
      strong.textContent = label;
      const span = document.createElement('span');
      span.textContent = value;
      line.append(strong, span);
      runtime.append(line);
    }
  }

  function addBubble(item) {
    const bubble = document.createElement('div');
    bubble.className = `ai-room-bubble ${item.role}`;
    const role = document.createElement('strong');
    role.textContent = item.role === 'user' ? 'You' : 'NEXUS';
    const text = document.createElement('p');
    text.textContent = item.text;
    bubble.append(role, text);
    if (item.meta) {
      const meta = document.createElement('small');
      meta.textContent = item.meta;
      bubble.append(meta);
    }
    log.append(bubble);
  }

  function renderHistory() {
    log.replaceChildren();
    if (!chatState.messages.length) {
      const empty = document.createElement('div');
      empty.className = 'ai-room-empty';
      const strong = document.createElement('strong');
      strong.textContent = 'AI Room ready';
      const p = document.createElement('p');
      p.textContent = 'Messages are evaluated through the deterministic authority gate before any route is proposed.';
      empty.append(strong, p);
      log.append(empty);
      return;
    }
    for (const item of chatState.messages) addBubble(item);
    log.scrollTop = log.scrollHeight;
  }

  function appendMessage(role, text, meta = '') {
    chatState.messages.push({role, text: String(text).slice(0, MAX_MESSAGE), meta: String(meta).slice(0, 320)});
    chatState.messages = chatState.messages.slice(-MAX_HISTORY);
    persist();
    renderHistory();
  }

  async function sendTurn(message) {
    chatState.turn += 1;
    const turnId = `turn-${chatState.turn}`;
    persist();
    const response = await fetch('/api/ai-room/message', {
      method: 'POST',
      headers: {'Accept': 'application/json', 'Content-Type': 'application/json'},
      cache: 'no-store',
      body: JSON.stringify({
        session_id: chatState.sessionId,
        conversation_id: chatState.conversationId,
        turn_id: turnId,
        message,
      }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload.detail || payload.error || `HTTP ${response.status}`);
    }
    if (payload.contract_version !== API_CONTRACT || payload.ai_room?.contract_version !== ROOM_CONTRACT) {
      throw new Error('AI Room contract mismatch');
    }
    return payload.ai_room;
  }

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const message = input.value.trim();
    if (!message || message.length > MAX_MESSAGE) return;
    input.value = '';
    appendMessage('user', message);
    input.disabled = true;
    send.disabled = true;
    send.textContent = 'Evaluating…';
    try {
      const result = await sendTurn(message);
      const decision = result.decision || {};
      const route = decision.route ? ` · route ${decision.route}` : '';
      appendMessage(
        'assistant',
        result.reply || 'No response text.',
        `L${Number(decision.authority_level ?? 0)} · ${decision.status || 'blocked'} · ${decision.reason_code || 'unknown'}${route}`,
      );
      renderGate(result);
    } catch (error) {
      appendMessage('assistant', `🔴 AI Room unavailable: ${error.message || 'request failed'}`, 'No state mutation occurred');
      renderGate(null);
    } finally {
      input.disabled = false;
      send.disabled = false;
      send.textContent = 'Send';
      input.focus();
    }
  });

  input.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      form.requestSubmit();
    }
  });

  newSession.addEventListener('click', () => {
    chatState = freshState();
    persist();
    renderHistory();
    renderGate(null);
    input.focus();
  });

  renderHistory();
  renderGate(null);
})();
