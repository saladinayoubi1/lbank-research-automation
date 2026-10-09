# NEXUS strategy validation: observation adequacy & independent arithmetic

Date: 2026-10-10. System map: DATA-21 -> RES-30/31/32 -> VAL-40 -> QA-41
-> QUAL-42 -> REG-50 -> RUNTIME-60/RISK-61 -> PAPER-62. This change
affects only the new **composite VAL-40 -> QA-41 issuance boundary**.
It does not register, approve, install or run a Paper/Live strategy.

## Verified deficiency (source-bounded)

- `ProductResearchRuntime.fetch_dataset(...)` caps a single dataset at
  **1,000 rows**. Composite runtime requalification requests 1,000 bars per
  15m/1h/4h, so the newest 15m slice can cover only **10.42 days**.
- The pre-existing VAL-40 producer v1 can report `QUALIFIED_FOR_REVIEW`
  with positive conservative+stress BTC/ETH returns and activity during
  that very short slice. That result is a *producer review invitation*,
  not a verified economic edge or pristine later holdout.
- Its verifier checks hash binding and deterministic replay, but the shared
  simulator and fee/PnL arithmetic had no independent reconciliation.
- Source-bound historical records and previous QA receipts are immutable;
  replacing old schemas would invalidate prior proof, so **do not rewrite**
  the VAL-40 producer or archived QA-task/receipt schemas.

## Implemented fail-closed boundary (new QA tasks only)

`nexus_composite_evidence_adequacy.assess` independently checks:

1. Exact BTC/ETH and 15m/1h/4h complete, contiguous, time-ordered
   closed-candle coverage from each source-bound dataset's row count and
   first/last open timestamps. Missing or inflated row counts fail closed.
2. Preregistered **30 calendar days of complete observed candles** before
   a *new* physical composite QA-41 task may be issued. This is a source
   coverage criterion, **not a minimum number of strategy trades**.
3. Reconcile `net_return_pct` against `net_pnl_usdt` and isolated **10,000
   USDT research capital** independently of the strategy/backtest engine.
   Require exact conservative (10+5 bps) and stress (25+15 bps) inputs;
   finite drawdown, turnover, exposure and win rate. Profile trade counts
   must not be conflated into independent trade sample size.
4. Zero closed trades over a *sufficient* window is `INCONCLUSIVE`,
   not a negative scientific verdict. An inadequate 10-day window with
   positive PnL is likewise `INCONCLUSIVE`.
5. Even when the observation check passes, it is labeled
   `READY_FOR_INDEPENDENT_QA_ONLY` with explicit:
   `statistical_significance_established=false`,
   `pristine_prospective_evidence_present=false`,
   `owner_demo_admission_allowed=false`, `live_trading_authority=false`.
   Positive ROI from one closed trade may proceed to **QA only**, not Demo.

The new QA task builder requires this extra assessment *after* successful
canonical VAL-40 source/digest verification. The transport treats only
an insufficient window as a reason-coded no-work result, not a permanent
CI failure loop; malformed/accounting-tampered evidence remains an error.
Legacy signed receipts remain unchanged and verifiable.

## Deliberate blocking condition, not a hidden workaround

The legacy physical ProductResearchRuntime single-call API remains capped at
1,000 bars. This source-only PR now adds an **explicit exact 3,072-bar
bounded, paged 15m canonical adapter** used by new VAL-40 evaluations
(1,000+1,000+1,000+72 official primary Bybit public pages), each separately
validated against the unchanged market registry and source/endpoint semantics.
The combined rows must cover 32 complete contiguous days, without duplicate,
missing, stale, forged/rehashed or substituted bars. A new *canonical*
provenance manifest binds all four physical page SHA256 identities.

The preexisting signed VAL-40 1,000-bar v1 records stay verifiable under the
legacy marker, but **cannot create new QA tasks** because they lack 30 days.
New paged 3,072-bar physical producers remain QA-eligible only if the
separate observation-and-arithmetic gate passes. The v1 schema/old receipt
digests and the owner app are unchanged. This does not make future
out-of-sample data pristine or prove profitability.

On 2026-10-10, a **read-only physical public Bybit probe from Laptop 2**
successfully collected *both* BTCUSDT and ETHUSDT official Spot
3,072-bar 15m windows, with first open 1788822900000 and last open
1791586800000, exactly four independently bound pages per symbol.
Verified combined canonical artifact SHA256 identities:
- BTCUSDT `40dfe73e86181c67675d72f7dccbd4a1b84b42432d30f381182c82ee4023b073`
- ETHUSDT `004fe2d018d36db8df6132ce37c4603007c27d48272d6087779943257845dc5f`

This physical source check was **not an Agent Manager strategy backtest**, not
an independently attested QA receipt, and not promotion evidence. It did not
read/write Paper or credentials. The approved next gate is exact PR-head tests
followed by real Agent Manager numerical tasks on the updated reviewed
mechanism, separate fill oracle, and prospective risk validation.

## NOT solved by this PR — further separate scientific and owner gates

- Independently coded order/fill accounting oracle (not just the above
  isolated-cash arithmetic identity). The existing QA replays the same
  simulator, so a shared stop/target or slippage bug remains possible.
- Chronologically purged/embargoed walk-forward, multiple non-overlapping
  regimes, uncertainty intervals and explicit multiple-comparison
  correction. The repeatedly inspected historical test is *not pristine*.
- Genuine **future** observation in the frozen candidate/strategy state,
  including **at least five actual closed prospective Paper trades**
  per issue #1811 and #1985 and separate owner-facing results review.
  This prospective minimum is not a Research trade-count cap.
- No `QUALIFIED_FOR_REVIEW`, QA `DONE` or
  `QUALIFIED_FOR_REGISTRY` is permitted to be portrayed as proven edge
  or Demo activation. REG-50, RISK-61, PAPER-62 remain separate deny gates.
  Existing 500-USDT journal, previous installation, and all old receipts
  are unchanged; Live=false.

## Verification and rollback

Tests cover both false-positive 10-day profitable replay and genuine
30-day+ source-bound *synthetic fixture*, source gap, forged independently
rehashed PnL, invalid stress costs, duplicate profiles, zero activity,
separate cost-profile effective sample, and no-work transport semantics.
Fixture testing does not certify an available live 30-day dataset.

Undo by reverting this source-only PR after preserving its test report.
Do not reset the Windows user profile or change the owner-installed app.
