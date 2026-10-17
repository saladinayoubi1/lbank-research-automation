# NEXUS — Butterfly V8 independent first-producer cost gate (17 October 2026)

## Result: REJECTED. No Demo/Paper qualification and no Live

**Purpose**: establish an unambiguous fail-closed research decision for the previously executed causal Butterfly V8, without repeating its backtest, retuning Fibonacci thresholds, silently discarding negative cells, inventing a backtest sample, or altering the unrelated Elliott V117 prospective freeze.

### Exact provenance

Read ONLY the existing first producer report:
`docs/evidence/causal-butterfly-v8-20261014/first-producer/native-artifacts/producer/research-report.json` from Elliott research branch `codex/elliott-causal-quality-research-20261015`.

- Producer source SHA `2b89f6e89abdacc16b3288b9fd9ebcb3bdea7e69`.
- Archived historical source semantic SHA256 `2455a725886d81adaec9d3478e8f3b2daaba6c0c9645a691e71737eb64f67422`.
- Immutable expected report digest `21be76c6f276c0d71ed4f87a2a045eee7ee9050d4d789ee1a862be8ad333c4c0`. Read-only consumer verifies both canonical rehash and original *pinned digest*. Full report local physical file SHA256 `5e0588eaa9803287c8b1d4a0f4dc292ea308a502f570c539e38ecfa46ecd8728`.
- Frozen factory fingerprint `c451551fdb8bacd867e865eb494a14ba506061cbffd9542aca04e13df3f56f02`. Original study uses BTCUSDT/ETHUSDT; 10,000 USDT **per symbol/per isolated cell**, not the user's 500 USDT shared Demo balance.
- Result file `docs/evidence/causal-butterfly-v8-20261017/V8_INDEPENDENT_COST_GATE_REJECTION.json`, digest `1e22eac7ec079ea1579beb3b2844f7e02056dded0efe6f9a14324ce9ab64b6f4`.

### All 12 original cells, preserved without cherry-picking

| Partition | Profile | BTC trades | BTC net P/L | ETH trades | ETH net P/L | Sum of two **independent** P/Ls |
|---|---|---:|---:|---:|---:|---:|
| Training | Conservative | 2 | +5.4032 | 1 | +3.1778 | **+8.5810 USDT** |
| Training | Stress | 2 | -2.6153 | 1 | -9.3033 | **-11.9186 USDT** |
| Validation | Conservative | 1 | -6.5202 | 1 | -8.8644 | **-15.3846 USDT** |
| Validation | Stress | 1 | -10.4832 | 1 | -12.8157 | **-23.2988 USDT** |
| Historically-inspected test | Conservative | 0 | 0 | 0 | 0 | **0; NO ACTIVITY** |
| Historically-inspected test | Stress | 0 | 0 | 0 | 0 | **0; NO ACTIVITY** |

Do not call the two independent cell P/L sums returns on one shared account or actual Bybit fills. The training figures have only three roundtrips across both symbols (no arbitrary minimum-trade threshold is imposed) and are insufficient to establish robust edge. Stress at a larger but pre-existing fee/slippage assumption makes both training symbol returns negative. Both validation symbol cells are negative even in conservative conditions, and zero old-test trades **cannot** be interpreted as a winning or nonlosing future validation.

### Gate logic, independent scope, and adversarial QA

The new `research/causal_butterfly_v8_cost_audit.py` accepts the **single exact immutable artifact** only if original source SHA, source archive SHA, factory config fingerprint, report signature and all 12 original symbol/split/cost tuples are unchanged. It rejects duplicate/missing cells, nonfinite or inconsistent reported P/L, forged future-pristine claims, positive-label tampering, extra test trades, altered fee results, and any Live/Demo authority.

Produces explicit `REJECTED_FRAGILE_TRAIN_NEGATIVE_VALIDATION_NO_TEST_ACTIVITY`, `qualifies_for_paper_demo=false`, `live_trading_authority=false`. It does **not** reproduce original Bybit source byte provenance, independently backtest original event signals, or certify market profitability. Those proofs require distinct data/agent authority; this gate is **existing-source economic triage**, not new strategy research.

Laptop2 isolated 2026-10-17 check: **16/16 pytest PASS**, CLI audited unchanged first producer report exit 0; local result SHA256 `4eccf94af6eb124c67095c059641e034d4157c1585e32127a54b77b17f5dd830`. No changes to installed applications, Paper trades/journal/profile, remote, Windows runner, DeepSeek or VPS.

### Elliott V117 not conflated

Elliott V117 three preregistered event grammar arms are locked for **future Bybit Spot one-minute 2026-11-16T00:00Z to 2026-11-30T00:00Z exclusive**. As of October 17 2026 this period has not occurred. It has 0 actual prospective market rows and no realized return outcomes. This Butterfly triage neither uses V117 future rows nor relaxes its original V106 gates. The Elliott parent PR #2673 remains a **research draft**, not main Paper code.

### Next economic objective

Reject Butterfly V8 exactly as measured; do **not** rerun it with secretly adjusted pivot widths or favorable stops against the inspected archive. Future candidate work must use preregistered **distinct causal entry/exit mechanics** and independent physical source/fill/time QA; claim no future holdout until it truly exists. If no such new input is currently available, stop costly redundant discovery, preserve the rejection ledger and retain Paper/Demo disabled.
