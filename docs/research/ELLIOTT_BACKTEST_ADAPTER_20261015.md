# Elliott five-swing research adapter — 2026-10-15

The causal closed-OHLC features now feed one explicit, preregistered research
candidate through `nexus_elliott_five_swing_research.py`. It uses the unchanged
parent feature builder, risk contract and next-open simulator. It does not
register an automatic Strategy Finder candidate or connect to Paper. No new
market evaluation has run; complete recursive Elliott classification and
positive expectancy remain unproved. VPS work stays owner-paused.

## Fixed candidate and timestamp boundary

`research/elliott_five_swing_candidate_preregistration.json` freezes one
configuration before any candidate market outcome. Its digest is
`ede171e4dc320d72b32e8b8241d0a468c3a85ebdb1e410617b72a5734eabe6ec`.
The already frozen seven-pivot geometry/lifecycle and cost function are reused
byte-for-byte. The candidate adds no parameter sweep, cost relaxation or
minimum/maximum trade count.

Canonical archive timestamps mean candle OPEN. The parent derives
`decision_at=timestamp+15min`. The adapter copies that decision time into the
new helper's CLOSE timestamp exactly once. It preserves every old output
column and input frame, then appends the new Elliott columns. It rejects a
collision rather than silently overriding a field. Future higher/15m bars
cannot change earlier decisions.

The fixed entry contract requires completed causal `h4_up=1`, `h1_vol_ok=1`,
the lagged active shape, the first fresh Elliott close-break event, stress-cost
feasibility, `close>open`, `close>previous_close`, and finite positive prices
and lagged range. The event has already consumed its identity before body,
context or cost denials. The stress screen is identical under both simulation
profiles; it still uses the decision close, not the unknown actual next open.

`backtest_elliott_candidate` supports only conservative fee/slippage 10/5 bps
and stress 25/15 bps per leg, risk variant 0. It calls the unchanged shared
simulator: separate simulated cash 10,000 USDT, long/flat only, 10% cash
exposure, 0.1% stop risk, 5% daily pause, 10% drawdown halt, stop 1.5 lagged
ranges, target 2R, time exit 64 bars and stop-first same-bar ambiguity. This
simulation never uses the owner's Paper balance or account.

## Actual fill observation

The existing `nexus_backtest_observer.observe_backtest` gains an explicit
`event_profile="elliott_five_swing"`; its default macro profile remains
unchanged. The adapter always supplies the Elliott profile. No simulator
locals, source, pricing, quantity, ordering or risk values are changed.
Existing source/code binding and isolated untraced CPython requirements stay
in force; unsupported profiles or missing Elliott events fail closed.

The observer records the actual decision, next-open fill and exit indices/UTC,
lagged origin/fifth-high/correction identity and confirmation, reference and
slipped prices, quantity, both fees, stop/target/range, exit reason, price-event
admission and cost inputs. Fold offsets preserve global bar/pivot identities.
A hypothetical cost-feasible decision can still have a different actual
next-open price or a rejected nonpositive stop; neither is reported as the
hypothetical fill.

## Verified source and numeric gate

**163 research methods passed locally and on LAPTOP2**, plus the unchanged
pure source-schema function checking all 111 registered frontier mechanisms.
The 163 methods comprise 106 inherited research tests, 16 structural review,
26 closed-OHLC and 15 new adapter/observer methods. This native child does not
run the full control-plane pytest module; hosted CI exercises that scope.

The actual native owned child exited 0 without timeout. All 50 bound source
and fixture files were checked before and after execution; 41 of the parent's
42 bound files remain byte-identical. The only changed parent component is
the observer. The shared backtest AST hash remains
`e44e2bada1efbf2427edfee224d75e96067bfcf1e3fa07b79fa39a09782b9bfb`.
The engine and prior observer also matched their exact parent Git blobs.
Narrow `.gitattributes` entries keep the four hash-pinned source files and
previous-observer fixture LF under Windows checkout.

New tests prove exact old-column equality and unchanged inputs, corrected
open-to-close timing, changed-future-tail invariance, body/context/cost/range
denials, frozen configuration, fold indices and distinct macro/Elliott event
profiles. An independently calculated fixture matrix covers target, stop,
adverse open gap, 64-bar exit and terminal liquidation under both cost
profiles. Observed fees/prices/P&L match those calculations; aggregate metrics
match the original engine. The entire default macro observation JSON also
matches the frozen previous observer under both profiles.

Registered inventory stays **95 contracts / 122 mechanisms / 111 frontier
configs**. Factory-spec-only digest is
`c47a42bf6d9fcba239f99a1eaa63d46fcff24b81a1921e0f49b26a9bf6e515fe`;
the full inventory including ordered mechanism IDs/configs has digest
`683ca4fa3f373276f7255b5cf5afa797b434e182d264cd4ea18f140739053de2`.
The new explicit candidate remains outside that automatic inventory. No
registered contract, approved-field set, frontier tier or coordinator changes.

Evidence under `docs/evidence/elliott-backtest-adapter-20261015/` contains the
source binding, local/native worker and process receipts, exact gate worker
and owned native invocation. Receipt exports are canonical JSON snapshots;
the native process receipt separately binds the actual native worker-file
bytes retained at the recorded LAPTOP2 stage.

## Remaining market gate

After the exact new-head hosted checks pass, freeze one complete
source/data/terminal-ledger/gate/invocation-bound exclusive producer. Then
evaluate this single candidate on the immutable Bybit archive with actual
fill diagnostics and perform independent market/numeric QA. Preserve the
completed v9 producer and its terminal ledger; do not replay it or retune
from its already inspected later folds. The archive's historical folds are
diagnostic, not a pristine holdout. Market replays remain 0. Live=false, no
auto-Demo or failover; LAPTOP1 remains the sole Paper writer.
