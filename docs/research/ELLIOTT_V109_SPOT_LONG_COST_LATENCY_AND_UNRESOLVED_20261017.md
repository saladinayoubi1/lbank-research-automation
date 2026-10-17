# NEXUS Elliott V109 — preregistered synthetic Spot-long latency, cost and unresolved-exit stress

**Research only, no market trade or market profit.** This is a deliberately **non-executable illustrative stress diagnostic** for V107's early Wave-1/2 contour decisions and V108's frozen forward four-hour physical-barrier observations. It is NOT a Bybit Demo strategy, verified market fill, genuine Elliott degree certification, margin/borrow model, or deployable risk engine.

## Source and preregistration authority

- Branch `codex/elliott-causal-quality-research-20261015`, Draft PR #2673, canonical `saladinayoubi1/lbank-research-automation`. Frozen parent V108 commit `0432359ad4724cc886c5e6414aafc8e5ba749747`, immutable V108 rulebook SHA256 `0777098b0801f8753df6a1743a9bbe8a4dcf9df5048a5e7e1aa78d3f65ee81a8`.
- Unchanged prospective source: Bybit **public Spot** BTCUSDT/ETHUSDT closed 1m period **Nov 16 00:00 through Nov 30 00:00 UTC 2026 exclusive**, 20,160 bars each. **Zero future period candles fetched, inspected, evaluated or traded** as of V109 construction on Oct 17. Protected V52 prospective period Oct 18–Nov 15, Laptop1 Demo, journals, runner, VPS and live-trading safeguards remain untouched.
- V109 module: `research/elliott_v109_spot_stress/stress_v109.py`; synthetic QA `tests/test_nexus_elliott_v109_spot_stress.py`. Frozen V109 rulebook `docs/evidence/elliott-v109-spot-stress-20261017/V109_FROZEN_SPOT_STRESS_RULEBOOK.json`, SHA256 **`86b4b02c33204e020065481def1c0b332da3e060e93883eab7153504d2444dd4`**. Immutable parent V108 Git bytes must match before freezing.

## The non-executable fixed Spot stress scenario

**Only synthetic Long Spot exposure is stress-modeled.** Bullish necessary V106/V107 candidates that already passed the original decision-time grammar may enter the counterfactual screen. Every bearish candidate remains in all original denominators and outcome ledgers, but the stress category must be `SPOT_SHORT_UNSUPPORTED_NO_BORROW_ASSUMED` (public Spot data do not demonstrate spot-borrowing/short permissions, leverage, margin facilities or actual Bybit account eligibility). Rejected Long or Short candidates are retained as `REJECTED_ORIGINAL_V107_GATE` and never retroactively promoted because of future price gains.

The model **does not trade**. The 1-minute candle **immediately following Wave-2 right-confirmation is treated entirely as a latency interval**, with **no modeled entry**. If either already-frozen Wave-0 origin or Wave-1 endpoint barrier is touched during that minute, the scenario abstains. After one full completed minute, the **second 1m candle's historical OPEN** is treated as an *illustrative* Long entry reference, but the model knows that minute's actual high/low **only after it closes**. This is a retrospective accounting convention, not a proof that any order could fill at this open; it never sends an order.

Illustrative and intentionally conservative **fixed stress costs**:
- **10 basis points** presumed taker fee per side.
- **2 basis points** half-spread per side.
- **5 basis points** adverse slippage per side.
- Total **17 bps per side** applied adversely both at hypothetical buy and sell. These are artificial predefined stress inputs, **not verified Bybit fees, bid/ask quotes, price impact or actual account charges**. No calibration to future results is permitted.

The only price barriers are the original **Wave-0** origin (illustrative stop reference) and **Wave-1** endpoint (illustrative target reference), with no optimization. The scenario abstains if the hypothetical delayed open is at/outside either barrier or if after adverse entry and target exit costs the target is no longer economically positive. No favorable fill inside a future candle is inferred.

After the delayed entry, for the remainder of the **original fixed 240-minute V108 horizon**, classify:
- `STRESS_ORIGIN_STOP_FIRST`: source low touched Wave-0 after entry. If the one-minute OPEN gapped *below* Wave-0, the illustrative exit reference is that **worse opening price**, not a magically filled stop at Wave-0.
- `STRESS_SAME_BAR_BOTH_ASSUME_STOP_FIRST`: both Wave-0 and Wave-1 touched within one minute; stop is **always assumed first**. One-minute OHLC cannot show the intrabar order.
- `STRESS_WAVE1_TARGET_TOUCH`: source high touched Wave-1, with no Wave-0 stop touch in the same or any earlier eligible minute.
- `STRESS_NO_EXIT_WITHIN_FIXED_HORIZON`: no barrier was touched within all 240 closed minutes. This is **open/unresolved**, not a winning trade or forced profitable close.
- `STRESS_RIGHT_CENSORED_UNCLOSED_POSITION`: original source stops before the whole 240 minutes and no eligible barrier was touched. **Neither zero return nor any realized return is fabricated.**
- `CENSORED_BEFORE_LATENCY_ENTRY`, `LATENCY_BARRIER_TOUCHED_ABSTAIN`, `SECOND_BAR_OPEN_OUTSIDE_STOP_TARGET_ABSTAIN`, `STRESS_COST_REMOVES_POSITIVE_REWARD`, `NONCOMPARABLE_ORIGINAL_BARRIERS`, and rejected/unsupported Spot-short categories remain explicitly separate.

For categories where a hypothetical exit touches a barrier, the algorithm records **illustrative stressed net R** = ((adversely stressed hypothetical exit) − (adversely stressed hypothetical entry)) / (hypothetical entry − Wave-0 source origin). This numerical R is **not** real profit, actual net P/L, realized fee performance, a Bybit fill, or an economic backtest. Costs can make a target touch worth less than +1R and a stop/gap worth worse than −1R. Unresolved, censored, and abstaining categories have **null** illustrative R and null actual P/L.

## Source-bound accounting and boundaries

- For each original V107 six-consecutive-coarse event window, all original causal candidate decisions and V108 price-barrier observations are recomputed and checked against the *exact separately preserved original ledgers*. A changed V107 pass flag, altered 1-minute V108 result or mismatch in original cohort count **fails closed**. Every previously rejected/accepted window remains in the denominator and is assigned exactly one mutually exclusive stress category.
- The future-only source adapter requires completion of Nov 30 UTC, original immutable V108 evidence, V108's two-auditor V103/V104 42-page original archive pipeline, exact original 7-field source SHA matching, full source period completeness, original V99 event recreation, and unchanged original V107/V108 candidate decisions before any outcome classification. It performs no HTTP; original archive copies can still be unauthenticated if the collector was compromised because two parsers on the same files are not independent Bybit-signed observations.
- A successful synthetic test or favorable illustrative R **does not prove** Elliott Wave-3 probability, full 5-wave confirmation, market prediction precision, trade win rate, executable entry/exit, net P/L, portfolio return or Demo eligibility. No short, margin, leverage, Bybit order adapters or live trading are added. There is **no** modification to protected V52, Laptop1 Demo or paper journal.
- The next research gate would require independently verifying authentic Bybit data, exact account-specific fees/bid-ask spreads, realistic order fill assumptions and funding/margin restrictions, full multi-pair non-overlapping position accounting, unresolved position policy and an untouched prospective holdout, rather than deriving a profitable strategy from synthetic unit tests.

## Verified V109 QA / no-market integration

- Dedicated synthetic V109 tests: **25/25 PASS**, native `V109_25_UNIT_EXIT=0`. A prerelease 42-page synthetic smoke exposed a genuine protocol-interface mismatch: V108's archived-source adapter adds exactly `source_candles`, `physical_source_sha256`, and `authenticity_caveat` to its core outcome record. The V109 checker now compares every core original V108 field, permits exactly those three provenance fields together (or no provenance fields in pure synthetic unit fixtures), and independently computes the **complete original seven-field physical candle SHA256**. New regression tests reject a changed source SHA or an unexpected metadata field.
- End-to-end V103/V104/V107/V108/V109 integration smoke **PASS**, `V109_FULL_SYNTHETIC_PIPELINE_EXIT=0`, using **42 entirely fabricated HTTP-shaped responses / 40,320 artificial flat 1-minute candles**, with a simulated future host clock. **No actual market data, no certified Elliott wave, no real order, no P/L**. The two parser implementations inspect the *same* fabricated archive; this is not independent real Bybit authentication. Temporary smoke code and logs remain outside Git.
- Final Laptop2 full Elliott regression after this correction: **1035/1035 PASS** (`Ran 1035 tests in 61.916s`, `OK`, native `V109_FULL_EXIT=0`). SHA256 of `$env:TEMP\V109_FULL_ELLIOTT_REGRESSION.txt`: `ea06ce8860d857901013f7c2cfcc11cb8ac90c319ec5379b4ae5ba46fbef2d04`.
- V109 write-once protocol manifest `V109_FROZEN_SPOT_STRESS_RULEBOOK.json`: SHA256 `86b4b02c33204e020065481def1c0b332da3e060e93883eab7153504d2444dd4`, verified against the generated source bytes; `V109_FREEZE_EXIT=0`, **0 market rows/0 real orders**.
- GitHub predecessor V108 CI: `Test`, `Workflow Permissions Policy`, `Research Evidence Refresh` **all SUCCESS** at commit `0432359ad4724cc886c5e6414aafc8e5ba749747`. This is NOT yet V109 CI, which requires independent post-push confirmation.
