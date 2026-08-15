# NEXUS Phase 4 UI Surface

Parent: #510
Version: `phase4-ui-surface/v1`

The UI is designed from the start, but controls remain non-authoritative until their owning backend Gate passes.

## Primary navigation
- Dashboard / Mission Control
- AI Chat Room
- Research / Experiments
- Strategy Registry
- Paper Trading / Positions
- Portfolio / PnL / Journal
- Risk / Kill Switch
- Data Registry / Readiness
- Agents / Queue / Providers
- Events / Audit Explorer
- Notifications
- Settings / System Status

## Global state language
Every page/component must support explicit `loading`, `ready`, `stale`, `degraded`, `blocked`, `recovering`, `failed`, and `empty` states where applicable. No degraded or stale state may be visually indistinguishable from healthy/authoritative state.

## Mobile-first behavior
Primary workflows must remain usable on phone-width layouts. Dense operational detail may collapse into drill-down views, but health, risk, block, kill-switch and owner-required indicators must remain visible.

## Command boundary
UI actions emit versioned commands with actor/session identity, correlation ID, expected policy/config version and idempotency key where mutation is possible. The UI never writes directly to Portfolio/Event Store. Paper-affecting commands pass through deterministic validation and Risk.

## AI Chat Room surface
Must visibly expose, per action where relevant: session, selected agent/model/provider, authority level, context freshness, proposed action, policy result, tool/action result, audit reference and owner-required status. Chat text alone is not authoritative evidence.

## Paper Trading surface
Must show paper/demo mode prominently. Positions display side, size, entry, stop, target, current simulated PnL, originating signal/strategy and active risk-policy version. Manual test signals are visibly marked `manual` and use the same validation/risk path as automatic signals.

## Mission Control
Shows queue depth/state, agents, runners/local-node status, data readiness, provider state/budget, strategy eligibility, paper state, circuit breakers, recent recovery events and owner-required notifications.

## Security boundary
Default local exposure remains fail-closed. Non-local/authenticated deployment is future work unless separately versioned and approved. Host validation, DNS-rebinding defenses, bounded parsing/response, no-store semantics and safe error responses are mandatory before stronger control surfaces are enabled.

## API rule
Frontend/backend communication uses explicit versioned API contracts. UI implementation details cannot become domain authority or redefine risk/data/strategy/event semantics.
