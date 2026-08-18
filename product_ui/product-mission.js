(() => {
  'use strict';

  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const fmt = (value, digits = 2) => Number.isFinite(Number(value)) ? Number(value).toFixed(digits) : '—';
  const stateClass = state => `state state-${String(state || 'UNKNOWN').toUpperCase().replace(/[^A-Z0-9_-]/g, '_')}`;

  async function api(path, options = {}) {
    const response = await fetch(path, {cache:'no-store', credentials:'same-origin', ...options});
    const text = await response.text();
    let body = {};
    try { body = text ? JSON.parse(text) : {}; } catch (_) { body = {detail:text}; }
    if (!response.ok) throw new Error(body.detail || body.error || `HTTP ${response.status}`);
    return body;
  }

  function ensureOverview() {
    const view = $('view-overview');
    if (!view || $('missionNow')) return;
    const strip = document.createElement('div');
    strip.id = 'missionNow';
    strip.className = 'mission-now';
    view.insertBefore(strip, view.firstChild);
  }

  function ensureAgents() {
    const host = $('agentState');
    if (!host || $('missionAgentRuntime')) return;
    host.className = '';
    host.innerHTML = `
      <div class="mission-toolbar">
        <button id="missionRefresh" class="small-btn">Refresh Mission</button>
        <button id="missionExport" class="small-btn">Export Snapshot</button>
        <input id="missionImportFile" type="file" accept="application/json,.json">
        <button id="missionImport" class="small-btn">Import Snapshot</button>
        <span id="missionSyncState" class="mission-meta">—</span>
      </div>
      <div id="missionOwnerActions"></div>
      <div class="mission-section-label">LOCAL SUPERVISOR / BUILD EVIDENCE</div>
      <div id="missionSystemEvidence" class="mission-grid"></div>
      <div class="mission-section-label" style="margin-top:14px">RESOURCES / WORKERS</div>
      <div id="missionResources" class="mission-grid"></div>
      <div class="mission-section-label" style="margin-top:14px">TASK QUEUE / ASSIGNMENTS</div>
      <div class="table-wrap"><table class="mission-table"><thead><tr><th>Task</th><th>State</th><th>Worker / transport</th><th>Lease / heartbeat</th><th>Evidence / blocker</th></tr></thead><tbody id="missionTasks"></tbody></table></div>
      <div class="mission-section-label" style="margin-top:14px">CONTROL-PLANE EVENTS</div>
      <div id="missionEvents"></div>
      <div id="missionAgentRuntime" hidden></div>`;
    $('missionRefresh')?.addEventListener('click', refreshMission);
    $('missionExport')?.addEventListener('click', exportSnapshot);
    $('missionImport')?.addEventListener('click', importSnapshot);
  }

  function ensureStrategies() {
    const view = $('view-strategies');
    if (!view || $('strategyMissionLeader')) return;
    const leader = document.createElement('div');
    leader.id = 'strategyMissionLeader';
    leader.className = 'strategy-leader';
    const firstPanel = view.querySelector('.panel');
    if (firstPanel) view.insertBefore(leader, firstPanel); else view.appendChild(leader);
    const history = document.createElement('article');
    history.className = 'panel';
    history.innerHTML = `<header><div><span>QUALIFICATION EVIDENCE</span><h2>تاریخچه Strategyهای واقعی</h2></div></header><div class="table-wrap"><table class="mission-table"><thead><tr><th>Strategy</th><th>Status</th><th>Dataset</th><th>OOS / Walk-forward</th><th>Stress / Regime / DD</th><th>Failure / Benchmark</th></tr></thead><tbody id="strategyMissionRows"></tbody></table></div>`;
    view.appendChild(history);
  }

  function renderNow(m) {
    ensureOverview();
    const host = $('missionNow'); if (!host) return;
    const active = m.control_plane?.active_tasks || [];
    const blocked = m.control_plane?.blocked_or_triage || [];
    const resources = m.resources || [];
    const leader = m.strategy_center?.leading_candidate;
    const owner = m.owner_actions || [];
    const supervisor = m.local_supervisor || {};
    const build = m.build_evidence || {};
    const current = active[0];
    const currentText = current ? `${esc(current.id)} · ${esc(current.title)}` : (m.control_plane?.runtime_present ? 'No active task / control plane idle' : 'Runtime state not present on this laptop');
    const resourceText = resources.length ? resources.map(r => `${esc(r.id)}:${esc(r.state)}`).join(' · ') : 'No runtime resource evidence';
    const strategyText = leader ? `${esc(leader.request?.family)} · ${esc(leader.qualification?.status)}` : 'No qualified candidate recorded';
    const recoveryText = blocked.length ? `${esc(blocked[0].id)} · ${esc(blocked[0].status)}` : `Supervisor ${esc(supervisor.status || 'unknown')} · restart ${esc(supervisor.restart_count ?? 0)}/${esc(supervisor.restart_limit ?? 3)}`;
    host.innerHTML = `
      <div><span>NOW</span><b>${currentText}</b><small>${active.length} active · ${fmt(m.control_plane?.verified_progress_percent,1)}% verified</small></div>
      <div><span>RESOURCES</span><b>${resourceText}</b><small>${esc(m.source)}${m.stale ? ' · STALE SNAPSHOT' : ''}</small></div>
      <div><span>LEADING STRATEGY</span><b>${strategyText}</b><small>${leader ? `OOS ${fmt(leader.evidence?.oos_score,4)} · DD ${fmt(leader.evidence?.max_drawdown_pct,2)}%` : 'Requires real qualification evidence'}</small></div>
      <div><span>BLOCKER / RECOVERY</span><b>${recoveryText}</b><small>${blocked.length} blocked/triage · build ${esc(build.status || 'unavailable')}</small></div>
      <div class="${owner.length ? 'owner-needed' : 'owner-clear'}"><span>OWNER ACTION</span><b>${owner.length ? `🔴 ${owner.length} owner-required` : 'No owner action required'}</b><small>${owner.length ? esc(owner[0].title || owner[0].id) : 'Only actual OWNER_REQUIRED L4 is surfaced here'}</small></div>`;
  }

  function renderOwner(m) {
    const host = $('missionOwnerActions'); if (!host) return;
    const rows = m.owner_actions || [];
    host.innerHTML = rows.length
      ? rows.map(row => `<div class="owner-action-box"><b>🔴 ${esc(row.id)} — ${esc(row.title)}</b><div class="mission-meta">${esc(row.blocked_reason || 'L4 owner approval required')} · authority L${esc(row.authority)}</div></div>`).join('')
      : `<div class="owner-action-box clear"><b>OWNER ACTION: NONE</b><div class="mission-meta">هیچ تصمیم L4 واقعی در snapshot فعلی نیازمند دخالت مالک نیست.</div></div>`;
  }

  function renderSystemEvidence(m) {
    const host = $('missionSystemEvidence'); if (!host) return;
    const supervisor = m.local_supervisor || {};
    const build = m.build_evidence || {};
    const buildState = build.status === 'verified' && build.exact_source === true ? 'VERIFIED' : 'UNKNOWN';
    host.innerHTML = `
      <div class="mission-card"><h3>local-supervisor</h3><p class="${stateClass(supervisor.status)}">${esc(String(supervisor.status || 'unknown').toUpperCase())}</p><p>Restart: ${esc(supervisor.restart_count ?? 0)} / ${esc(supervisor.restart_limit ?? 3)}</p><p>${esc(supervisor.reason || 'bounded restart policy active')}</p></div>
      <div class="mission-card"><h3>exact-source-build</h3><p class="${stateClass(buildState)}">${buildState}</p><p>SHA: ${esc((build.source_sha || '').slice(0,12) || 'unavailable')}</p><p>Run: ${esc(build.run_id || '—')} · ${esc(build.workflow || 'no build evidence')}</p></div>`;
  }

  function renderResources(m) {
    const host = $('missionResources'); if (!host) return;
    const resources = (m.resources || []).map(r => `<div class="mission-card"><h3>${esc(r.id)}</h3><p class="${stateClass(r.state)}">${esc(r.state)}</p><p>Workers: ${esc((r.workers || []).join(', ') || '—')}</p><p>Active: ${esc((r.active_workers || []).join(', ') || 'none')}</p><p>Routed: ${esc((r.routed_tasks || []).join(', ') || 'none')}</p></div>`);
    const workers = (m.workers || []).map(w => `<div class="mission-card"><h3>${esc(w.id)}</h3><p class="${stateClass(w.state)}">${esc(w.state)}${w.verifier ? ' · verifier' : ''}</p><p>${esc((w.resources || []).join(' / ') || 'no resource')}</p><p>Active: ${esc((w.active_tasks || []).join(', ') || 'none')}</p><p>Authority ≤ L${esc(w.authority_max)}</p></div>`);
    host.innerHTML = [...resources, ...workers].join('') || `<div class="mission-empty">No real resource/worker runtime evidence is available.</div>`;
  }

  function renderTasks(m) {
    const host = $('missionTasks'); if (!host) return;
    const tasks = [...(m.tasks || [])].sort((a,b) => (b.priority||0)-(a.priority||0));
    host.innerHTML = tasks.map(t => {
      const evidence = t.verification_evidence || t.result_evidence || t.failure_evidence;
      const reason = t.blocked_reason || t.triage_reason || t.failure_class || (evidence ? JSON.stringify(evidence).slice(0,180) : '—');
      const lease = [t.leased_at && `leased ${t.leased_at}`, t.heartbeat_at && `hb ${t.heartbeat_at}`, t.lease_expires_at && `exp ${t.lease_expires_at}`].filter(Boolean).join('<br>') || '—';
      return `<tr><td><span class="mission-task-title">${esc(t.id)} — ${esc(t.title)}</span><span class="mission-meta">P${esc(t.phase)} / G${esc(t.gate)} · L${esc(t.authority)} · priority ${esc(t.priority)}</span></td><td><b class="${stateClass(t.status)}">${esc(t.status)}</b><div class="mission-meta">attempt ${esc(t.attempt)} / retry ${esc(t.transient_retries)}</div></td><td>${esc(t.assigned_worker || 'unassigned')}<div class="mission-meta">${esc(t.dispatch_transport || 'no transport evidence')}</div></td><td class="mission-meta">${lease}</td><td>${esc(reason)}</td></tr>`;
    }).join('') || `<tr><td colspan="5">No task runtime evidence.</td></tr>`;
  }

  function renderEvents(m) {
    const host = $('missionEvents'); if (!host) return;
    const events = (m.events || []).slice(-30).reverse();
    host.innerHTML = events.map(e => `<div class="mission-event"><span>${esc(e.at || e.generated_at || '—')}</span><b>${esc(e.kind || 'event')}</b><code>${esc(JSON.stringify(e))}</code></div>`).join('') || `<div class="mission-empty">No durable Agent Manager events imported or generated locally.</div>`;
  }

  function renderStrategy(m) {
    ensureStrategies();
    const center = m.strategy_center || {};
    const leader = center.leading_candidate;
    const host = $('strategyMissionLeader');
    if (host) {
      host.innerHTML = leader
        ? `<span class="mission-section-label">CURRENT LEADER · NOT A PROFITABILITY CLAIM</span><h3>${esc(leader.request?.family)} · ${esc(leader.dataset?.instrument || leader.request?.symbol)}</h3><div class="strategy-evidence-grid"><div><span>OOS</span><b>${fmt(leader.evidence?.oos_score,4)}</b></div><div><span>WALK-FORWARD</span><b>${fmt(leader.evidence?.walk_forward_score,4)}</b></div><div><span>ROBUSTNESS</span><b>${fmt(leader.evidence?.robustness_score,4)}</b></div><div><span>MAX DRAWDOWN</span><b>${fmt(leader.evidence?.max_drawdown_pct,2)}%</b></div><div><span>COST STRESS LOSS</span><b>${fmt(leader.evidence?.cost_stress_loss_pct,2)}%</b></div><div><span>REGIME PASS</span><b>${fmt(leader.evidence?.regime_pass_ratio,3)}</b></div><div><span>FAILURE SEVERITY</span><b>${fmt(leader.evidence?.failure_mode_severity,3)}</b></div><div><span>BENCHMARK</span><b>${fmt(leader.evidence?.benchmark_score,4)}</b></div></div><p class="mission-meta">Dataset ${esc(leader.dataset?.binding_sha256 || '—')} · fees/slippage ${esc(JSON.stringify(leader.cost_model || {}))}</p>`
        : `<span class="mission-section-label">CURRENT LEADER</span><h3>هنوز Paper Candidate واقعی ثبت نشده است</h3><p class="mission-meta">Strategy فقط بعد از OOS / walk-forward / stress / regime / failure-mode qualification وارد این بخش می‌شود.</p>`;
    }
    const rowsHost = $('strategyMissionRows'); if (!rowsHost) return;
    rowsHost.innerHTML = (center.runs || []).slice().reverse().map(r => `<tr><td><b>${esc(r.request?.family)}</b><div class="mission-meta">${esc(r.request?.symbol)} · ${esc(r.request?.timeframe)}</div></td><td><b class="${stateClass(r.qualification?.status === 'paper_candidate' ? 'DONE' : 'BLOCKED')}">${esc(r.qualification?.status || 'unknown')}</b><div class="mission-meta">${esc((r.qualification?.kill_reasons || []).join(', ') || 'accepted path')}</div></td><td>${esc(r.dataset?.source || '—')}<div class="mission-meta">${esc((r.dataset?.binding_sha256 || '').slice(0,18))}…</div></td><td>OOS ${fmt(r.evidence?.oos_score,4)}<br>WF ${fmt(r.evidence?.walk_forward_score,4)}</td><td>Stress ${fmt(r.evidence?.cost_stress_loss_pct,2)}%<br>Regime ${fmt(r.evidence?.regime_pass_ratio,3)} · DD ${fmt(r.evidence?.max_drawdown_pct,2)}%</td><td>Failure ${fmt(r.evidence?.failure_mode_severity,3)}<br>Benchmark ${fmt(r.evidence?.benchmark_score,4)}</td></tr>`).join('') || `<tr><td colspan="6">No durable strategy evidence yet.</td></tr>`;
  }

  function renderSync(m) {
    const host = $('missionSyncState'); if (!host) return;
    const age = m.snapshot_age_seconds;
    const ageText = Number.isFinite(Number(age)) ? `${Math.round(Number(age))}s old` : 'age unknown';
    host.className = `mission-meta ${m.stale ? 'snapshot-stale' : 'snapshot-fresh'}`;
    host.textContent = `${m.source} · ${ageText}${m.stale ? ' · STALE' : ''}`;
  }

  function renderMission(m) {
    if ($('buildLabel')) $('buildLabel').textContent = '5.0.0';
    const badge = $('missionBadge');
    if (badge) {
      badge.textContent = m.control_plane?.runtime_present ? 'CONTROL PLANE' : (m.source === 'imported_snapshot' ? 'IMPORTED STATE' : 'NO RUNTIME');
      badge.className = `badge ${m.stale ? 'warn' : (m.control_plane?.runtime_present ? 'good' : 'neutral')}`;
    }
    renderNow(m); renderOwner(m); renderSystemEvidence(m); renderResources(m); renderTasks(m); renderEvents(m); renderStrategy(m); renderSync(m);
  }

  async function refreshMission() {
    try { renderMission(await api('/api/product/mission/full')); }
    catch (err) {
      ensureOverview(); ensureAgents(); ensureStrategies();
      if ($('missionNow')) $('missionNow').innerHTML = `<div class="owner-needed"><span>MISSION CONTROL</span><b>UNAVAILABLE</b><small>${esc(err.message)}</small></div>`;
      if ($('missionSyncState')) $('missionSyncState').textContent = `unavailable · ${err.message}`;
    }
  }

  async function exportSnapshot() {
    try {
      const payload = await api('/api/product/mission/export');
      const blob = new Blob([JSON.stringify(payload, null, 2)], {type:'application/json'});
      const url = URL.createObjectURL(blob); const a = document.createElement('a');
      a.href = url; a.download = 'nexus-mission-control-snapshot.json'; a.click(); URL.revokeObjectURL(url);
    } catch (err) { alert(`Mission export failed: ${err.message}`); }
  }

  async function importSnapshot() {
    const file = $('missionImportFile')?.files?.[0];
    if (!file) { alert('یک فایل Mission snapshot انتخاب کن.'); return; }
    if (file.size > 2_000_000) { alert('Snapshot بیش از حد بزرگ است.'); return; }
    try {
      const payload = JSON.parse(await file.text());
      await api('/api/product/mission/import', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
      await refreshMission();
    } catch (err) { alert(`Mission import rejected: ${err.message}`); }
  }

  function init() {
    ensureOverview(); ensureAgents(); ensureStrategies(); refreshMission();
    setInterval(refreshMission, 15000);
    window.addEventListener('focus', refreshMission);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, {once:true}); else init();
})();
