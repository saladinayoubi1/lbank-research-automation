# Closed macro breakout / first retest v10 — implementation gate

The candidate adds one closed-4h identity, its first fully subsequent closed-1h touch and a later closed-15m crossing. It uses the frozen v10 preregistration at e5a0fed7cc327bfbfab5e197219f7da34e7e3ce1. Horizons, costs, risk and lifecycle are unchanged from registration. No market computation has run for this source.

## Behavior and ordering

The 4h band excludes the displacement bar and freezes the previous six highs/lows. A macro closes at tau. WAIT state checks every fully subsequent closed 15m candle: low<=L or close<=H disarms it before other processing. Only a later completed 1h with open>=tau and close<=tau+6h can supply the first touch. A bullish touch-and-hold freezes that hour's high K; a failed first touch consumes the identity. At each decision the previous stored READY state is examined before new H1 or H4 observations. A new accepted 4h macro replaces future state last; a nonaccepted 4h close leaves it intact. The first price cross in steps 1..8 consumes the identity independently of body, context, ATR or cost admission.

The helper validates aligned complete UTC grids and OHLCV for all three frames. Future or overlapping higher bars cannot arm a current decision. A macro that closed before the available 15m history starts is not armed retroactively because its intervening invalidation path is unobserved. Audit-only lifecycle rows record identities, confirmation times, invalidations, expiry, replacement, first-touch rejection and price events with cost-screen inputs/denial reasons. These rows do not enter the factory grammar.

The stress screen under both simulation profiles uses current closed C, lagged preceding-14 high-low mean a and frozen R. It requires finite positive inputs/stop, strict R>2C(f+s) and a positive hypothetical target net, with f=.0025 and s=.0015. The unknown next open is not used. Actual gaps, fills, stop priority, size and guards remain the shared simulator's behavior. The earliest example decision is 05:15 after a 04:00 macro and 05:00 retest confirmation; the next bar opens at the same 05:15 UTC boundary with a later bar index.

## Integration and compatibility

One contract and three approved fields are appended. Factory contracts/IDs/configs and ordering of all 94 previous contracts, 121 mechanisms and 110 frontier configs match the frozen inventory. Prior frontier tiers remain ahead of v10. The new totals are 95 contracts, 122 mechanisms and 111 frontier configs. Every old feature column matches the frozen previous builder on a 1008-bar synthetic fixture. Historical tests exclude this later generation when checking their older inventories; their frozen fixtures and candidate assertions remain intact.

The shared backtest AST-source SHA256 remains e44e2bada1efbf2427edfee224d75e96067bfcf1e3fa07b79fa39a09782b9bfb. Neither its economic logic nor its source was edited. The previous engine fixture is test-only, byte bound to 15bece0ef68256a625532651d10e11f6c32444040f9c9d720ffcc5e29685afeb; it is not a second runtime or market producer.

## Observational gate

`nexus_backtest_observer.observe_backtest` calls the original function once under a CPython line observer. It binds the exact AST-source hash and the loaded code against compilation of the entire unchanged module, then traces only that code object. It reads copies of locals after actual entry/exit assignments, without writing simulator state or changing orders/values. It captures actual reference/slipped entry and exit, quantities, fees, ATR, stop/target, reason, decision/fill/exit indices and timestamps, setup/cost inputs, price-event admission and actual entry attempts. Existing tracing, unsupported implementation, source mismatch, incomplete capture or unmatched executions block observation. Trace state is cleared in `finally`. The API boundary follows the primary CPython documentation: https://docs.python.org/3.12/library/sys.html#sys.settrace.

Hand fixtures independently calculate fills and net PnL for target, adverse-priority stop, stop gap, 64-bar and terminal exits under 10/5 and 25/15 bps. Observed and ordinary aggregate results are identical as sorted JSON bytes. Tests also cover a real synthetic macro's next-open gap, denied regime, multiple trips, zero activity, rejected actual stop, offsets, source mismatch, pre-existing trace and cleanup on engine exceptions. This proves local single-cell observation only. Native capability, full archive coverage, aggregate Decimal QA and isolated producer integration remain pending. This observer adds diagnostic overhead; native producer deadlines must be prospectively bounded after the exact-source gate, before submission.

## Validation and remaining gates

The final owned child exited 0 without timeout: 106 unittest methods (34 new, 72 previous), then one separately AST-extracted frontier schema function covering 111 mechanisms. The full pytest module was not executed locally. The first local attempt had six errors caused by fixture-relative contract resolution and isolated-function compilation differing from module-import-aware CPython opcodes; both were corrected, with one bounded rerun. All source and fixture bindings, final logs, execution script and actual child exit are preserved in the adjacent evidence directory.

Local runtime: CPython 3.12.14, NumPy 2.3.5, pandas 2.2.3. No Parquet archive was read. This is not a full hosted or native Windows gate. The six checks on the proposal-only e5a0fed head succeeded, including Windows; those results do not qualify the new computational source. The historical parent Windows UI timeout remains historical evidence.

Next gate: all exact-commit hosted checks and a fresh native source/observation gate with an owned child OS exit, then qualification of the isolated producer hook and one prospective invocation bound to the 42-file computational closure, frozen market files and completed v9 ledger. Ledger semantic digest b784b409c16b77fa5d6dd5d65b7f8ed67e13e65aa6d230a74e843f9e63720e8f; byte SHA256 14cc329d8acd02fbc3a13268826446f44d05dcf9eb299a6c13738558342f401c. No earlier producer replay or later-fold retuning.

Research only; Live=false, automatic Demo=false, owner admission=false. Laptop1 stays the sole Paper writer; failover remains disabled. No owner install/profile/journal/checkpoint/authentication, machine recovery or VPS changes.
