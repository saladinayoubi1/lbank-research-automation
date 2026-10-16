# NEXUS Elliott V84 — V83 as-of isolation and regression QA

**Scope:** Correct a research-only V83 defect and add deterministic synthetic quality gates. No change to wave rules, Bybit Demo, V52 protocol, or Live settings.

## Defect, reproduction and correction

At V83 commit `91de74b`, `check_candidate()` validated every element of the caller-supplied minute array, **including bars strictly after the historical as-of decision**. A future unclosed/invalid or gapped tail could therefore turn an unchanged historical decision into an error. This is a future-tail dependence defect, not proof that the original V83 historical prices were contaminated, nor a demonstrated false fill.

**Correction:** Derive the exact number of completed 1-minute bars up to the decision UTC instant; require a contiguous, aligned, complete **prefix** and use only that prefix for witness price validation and all intraleg physical OHLC checks. Ignore later bars, including malformed future observations. Invalid, missing, or gapped bars **within** the decision prefix still fail closed.

## Explicit tests and result

`tests/test_nexus_elliott_v83_geometry.py` includes **11 deterministic tests**: bullish/bearish hard geometry without trading claims; wave-2 origin, wave-3 advance/shortest, wave-4 overlap, wave-5 non-truncation; extra pivots; forged source price; future pivot confirmation; missing source; minute gap; intraleg wick exceeding endpoint; invariant valid future tail; invariant incomplete/invalid future tail; unordered centers. Subtests cover individual reasons. Dedicated result **11/11 OK** after fix; initial failing test is retained to prevent regression.

**Physical historical replay after the fix:** independent SHA-bound Binance BTCUSDT and ETHUSDT March 1–2 2024 replay outputs are exactly equal to previously stored V83 per-symbol result objects (`BTCUSDT=True, ETHUSDT=True`). No new synthetic or historical P/L is claimed. Original `V83_RESULT.json` historical receipt is preserved unchanged.

## Verification scope and safety

Original V83 identified one five-leg motive *skeleton* per pair, both rejected under ordinary-impulse geometry. Those records remain a **limited exploratory, not fully recursive** classification; an overlap may require separate diagonal studies, not automatic reclassification. No signal is generated, and zero Demo positions or profitability is inferred. V52 remains frozen, Bybit remains sole eventual Paper-Demo execution venue, and Laptop1 install and VPS are untouched.

The full Elliott-focused regression on Laptop2 completed: **594 tests, OK, native EXIT_CODE=0**; the dedicated V83 suite completed **11 tests, OK**. Earlier native PowerShell stderr red text was a stream-wrapping `NativeCommandError` with exit code zero, not a Python test failure. Commit this evidence on the existing Draft PR branch only; do **not** merge PR #2673.
