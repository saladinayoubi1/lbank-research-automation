# Causal Elliott-inspired wave 1–2 v9 — implementation and source tests

The proposed wave-two low cannot be traded at the instant it forms. The new helper confirms strict alternating O/A/B pivots with three right closed bars, stores the setup for a subsequent decision, emits only a fresh closed crossing above the proposed wave-one high and leaves execution to the existing next-open engine. Completed lows that touch/break O or an expired setup deny the price event before any same-bar breakout.

This implementation follows immutable preregistration f6537760618ac5b8b7878946ff230975e7c5a1e9, semantic digest 2845fbc71ce1c5ee5ee986a7206bd19a05776fd6185d5f914475f35f57638301. The JSON lifecycle field describes its historical state when preregistered; it does not mean implementation is still absent after this source commit.

## Source behavior

One price event per O/A pair is consumed even when separate body/4h/1h/ATR strategy gates deny entry. A replacement B does not reopen an already consumed pair. Current events use only the state stored after the prior bar; newly confirmed pivots change future state after the current decision. No current/future observation rewrites already emitted output.

The fixed retracement 0.382–0.786, O-to-B span 192 bars, eligible ages 1–32 after B confirmation, 3+3 strict pivots and existing completed regime gates match the proposal. B at j is known at close j+3; earliest decision is close j+4 and earliest fill is open j+5. Origin invalidation governs observed setup/decision bars; shared next-open gap/slippage rules and ATR stops are retained rather than adding a different wave-based execution model.

This is an Elliott-inspired early-wave proxy, not a complete five-wave or subwave-degree count. Future wave-three/four/five properties do not select past entries. The publicly cited theory and our numeric engineering choices remain distinguished in the prospective precheck.

## Integration and history preservation

Appended one helper and one contract to the existing factory/pipeline/frontier. Inventory is now 94 factory specs/121 mechanisms; the previous 93/120 contract objects, IDs, order and frontier configurations remain exact. All prior frontier tiers retain priority. The completed v8 ledger advances to exactly one Elliott configuration with frozen contract 96c8d7106e88a93f53a789251f76ea00d68c1678235b40575dd982a2e934c976 and fingerprint f2bf31b05394380c36aefc85d29344433d22714a392e235d63d4029717bd68b9.

The shared backtest function SHA256 remains e44e2bada1efbf2427edfee224d75e96067bfcf1e3fa07b79fa39a09782b9bfb under the registered AST-source extraction. No risk/cost, drawdown/daily loss, quantity, fill, fee, stop-first, position-cap or global trade-count rule changed. Previous-generation tests compare their exact historical subsets while excluding the later additive Elliott ID; the new fixture separately asserts the full previous 120 mechanism inventory.

The fast-frontier bounded-boolean schema fixture gained inactive Elliott fields. No existing candidate contract was retuned, no old producer was replayed and the completed v8 ledger/report were retained.

## Verification completed locally

33 new Elliott methods and39 changed source Butterfly/slot-volume regressions passed as one 72-test unittest suite, actual tool process exit 0, 0.898 s. Coverage includes hand-calculated geometry/bounds, strict confirmation plus lag, every-prefix/future-tail invariance, timezone/grid/scale checks, whole-interval origin invalidation, same-bar precedence, confirmation/cross timing, expiry boundary, weak/replaced pivots, consumed identities, distinct setup events, exact prior contracts/order/frontier/risk, denied regime/body/ATR gates, next-open and stop-first, and pipeline event wiring.

The exact modified fast-frontier boolean schema function was additionally extracted from its source AST and executed successfully for all 110 frontier mechanisms; its full pytest module was not run locally. This is a separate source regression function, not a claim of full repository pytest completion.

Local Python 3.12.14/numpy 2.3.5/pandas 2.2.3 differs from the pinned native Windows pandas 2.3.3 environment. Pytest/pyarrow are absent locally; no package installation was performed. Exact-source hosted full checks and a separate hash-bound native Windows gate with true OS exit remain required before any first market producer. The tool transcript is partial because the first verbose output was truncated; the final 72-test OK/count and actual zero exit are preserved in the local receipt.

## Remaining gate and authority

Market runs for Elliott: 0. No profitability or Demo readiness is established. After hosted/native source gates, freeze a fresh source/data/ledger-bound one-candidate first producer with exclusive lease, durable parent/child actual OS exits, fixed four-cell Training screen and twelve exploratory diagnostics. Preserve prior ledger 9199c1d27e28bdc2de7f068dd1f99efa7d6315c793265d1c3215a860344b152c and exact file SHA c42ec37a0e7461e5939cb960196e99b6a9e55df954489ffd7d001efe4bd59115. Numeric/Decimal/market leakage and unseen prospective data remain separate qualification gates.

Map DATA-21 / RES-30 / RES-31 / RES-32 / VAL-40 / QA-41. Existing research components and isolated Laptop2 lane only. Laptop1 remains sole owner Paper writer, failover disabled. Live=false, automatic Demo=false, owner admission=false, official Coordinator advancement=false. Owner install/profile/journal/checkpoint/authentication, remote recovery tasks, Windows and VPS were not modified.
