# NEXUS — Shared-cash BTC/ETH relative rotation V1 (17 October 2026)

## Status: REJECTED after physical archive replay

This was one **new exploratory research implementation**, not a profitable mechanism. It is **NOT** connected to the NEXUS Strategy Finder dispatcher, owner Paper account, Demo, exchange API, runtime, or Live trading. Draft-only until reviewed. Source-bound real historical Bybit Spot bars produced negative costs-adjusted results in every independent time partition. No parameter optimization was performed after seeing this result.

### Hypothesis and distinction

The historical `nexus_composite_strategy_research.py` peer-reclaim mechanisms simulate one collateralized **per-symbol** net long/flat book, never buy peer/short own or switch one common cash balance. This experimental hypothesis assigns **one shared 500-USDT account** to *at most one* of BTC or ETH, then moves to cash or the stronger asset according to completed 15-minute close rankings.

This is a different execution/accounting topology than previous per-symbol peer confirmation; **global semantic novelty is not independently attested**. The NEXUS Elliott V110 capacity ledger tracks hypothetical reservation/risk limits, not this physical entry-fill P&L portfolio state machine. This test does not certify novelty or profitability.

### Pre-frozen execution model

- Two exact pinned physical source parquet archives, 128,544 continuous 15m bars per symbol from 2022-12-01 through 2026-07-31 UTC. Actual hashes:
  - BTC SHA256 `c3afe92899dda8fe52937c955323cc8e04bf8f200a68eb8651e55d6020981226`
  - ETH SHA256 `ce603440650d0022b1a17a7922da743a3b6219ba9afd89ad4362b70fbe3bbfa1`
- Check SHA256 **before** using data; strictly verify all candle values, timestamps and **exact shared UTC grid**; source-backed signal decision uses previous fully closed bar only. Next `open` price is filled; no same-bar close execution.
- One account starts at **500 USDT separately per partition**, no leverage, no short, at most one symbol. Asset selection every 16 bars (4h) using last 16 closed bar momentum, BTC 48-bar crash guard, a predeclared positive momentum gate 0.5%, and leader-return gap 0.2%. Full available cash is allocated after entry fees.
- At a rank switch, **SELL then BUY at the same next-open observation**, charging per-side fee/slippage on both legs, with cash never negative. Predeclared hard stop 1.5% from executed fill; stop first on ambiguous intrabar touch, gap at the worse of open/stop; 96-bar maximum holding and fixed 16-bar cooldown. A known partition end flattens at the last candle **open**, not future close.
- Fixed splits: first 60% training (with warmup), next 20% already-inspected validation, final 20% already-inspected historical test. No promotion to Demo. Both historical "holdouts" had been seen in prior NEXUS work and are **not pristine future OOS**.
- Per side friction: conservative fee 10 bps + slip 5 bps; stress fee 25 bps + slip 15 bps. No minimum number of positions gate. Code and fixed parameters committed **before** physical replay.
- Raw full trade/event/month evidence retained in the isolated Laptop2 QA directory only; raw result SHA256 `89931e68784a9bcffc74e4f88084b60cb5d2f1e0b9fb9edf50b396abc3a9a8fb`; result canonical digest `cfbd50da127abc814fc8fa8fb64165cd34d70546d34a47e5c2b5c2b02df69918`. GitHub summary: `docs/evidence/shared-cash-rotation-20261017/v1-rejection-summary.json`. Raw artifact is **not** falsely claimed to be uploaded. The script reproduces it given the unchanged exact SHA-pinned parquet sources.

### Source-bound measured losses

All USDT values refer to independent 500-USDT simulations, not the user's actual account.

| Independent partition | Conservative roundtrips | Conservative net P/L (USDT) | Average P/L/trade (USDT) | Max DD | Stress net P/L (USDT) |
|---|---:|---:|---:|---:|---:|
| Training | 912 | -462.3560 | -0.5070 | 92.77% | -499.6417 |
| Already-inspected validation | 364 | -291.3388 | -0.8004 | 58.60% | -465.4922 |
| Already-inspected historical test | 282 | -327.5593 | -1.1616 | 66.59% | -455.9856 |

The conservative **entry/exit fee-only** sums were 396.8727 USDT in training, 266.6186 in validation and 175.1141 in historical test; slippage losses are additional. Conservative closed trade wins were 270 / 912, 111 / 364 and 80 / 282. The reported losses include trading frictions and stop/gap handling. There were respectively 167, 84 and 62 triggered hard stops in the conservative replay.

### Diagnostic: friction decomposition (NOT a tradable strategy)

The same fixed mechanism replayed with **zero fee and zero slippage** for causal explanation only: Training **+61.5895 USDT**, previously-inspected validation **+121.3154 USDT**, previously-inspected historical test **-96.2163 USDT**. Thus any apparent nominal edge is fragile, and future/test regime performance is still negative even before costs.

As a simple static comparator, equal 50/50 buy-and-hold BTC and ETH with a single entry and final exit under conservative costs produced respectively **+1456.0928, +79.2943, -214.1908 USDT** in the same three partitions. No inference of risk-adjusted comparative superiority is drawn; gross exposures and holding times differ.

### Decision and next exact action

**REJECT** this fixed version; never retrofit its parameters to the inspected windows to fabricate a winner. No auto-dispatch, no Demo authority, no Live. The failure is economic **turnover/cost dominance plus absent robust positive historical-test edge**, not a runner failure.

Further research should not replay this entire mechanism or simply retune `MOMENTUM_MIN`, `INTERVAL`, stop %, etc. Independently review a **causally distinct** entrance/exit hypothesis (e.g. independently sourced Elliott/Butterfly with event-driven structural invalidation, not generic indicator recombination) against prior evaluated topology; predeclare costs and guardrails; execute source-bound prospective work with separate independent QA and genuinely unseen future data before Paper/Demo promotion.

### Verification

Laptop2 isolated `pytest -q tests/test_nexus_shared_cash_rotation_v1.py`: **9 passed** (OS exit 0). Source archive actual hashes matched. Physical execution completed (OS exit 0). No laptop1 install or Paper journal modified. Live trading remains disabled.
