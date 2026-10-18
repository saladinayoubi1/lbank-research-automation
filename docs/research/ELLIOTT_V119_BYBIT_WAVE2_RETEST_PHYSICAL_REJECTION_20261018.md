# NEXUS V119 — Wave2 physical support/retest economic research (18 Oct 2026)

## Verdict: REJECT this fixed exploratory mechanism on all three historical partitions

**Purpose and distinction.** V118's physical Wave1 **breakout** next-open entry was cost-negative on original 2024 Binance minute history. V119 is a separately frozen, **non-breakout** mechanism: independently observed strict physical low-high-low candidate (Wave0/1/2-like; no certified Elliott degree), retest of Wave2 **true candle low**, confirmed closed-bar reclaim below Wave1, *then* next-bar open buy. All trade exits are physical 15-minute OHLC with adverse fees and slippage, one 500-USDT cash book, no borrow/short. Does NOT claim an Elliott-wave-qualified entry, market return proof, Demo readiness or live trade.

### Original source, non-optimization, provenance

Two exact archived, continuously aligned historical Bybit **Spot** 15-minute parquet archives; each has **128,544** closed bars from **2022-12-01 through 2026-07-31 UTC**. BTC SHA256 `c3afe92899dda8fe52937c955323cc8e04bf8f200a68eb8651e55d6020981226`, ETH SHA256 `ce603440650d0022b1a17a7922da743a3b6219ba9afd89ad4362b70fbe3bbfa1`. The reader verifies archive file SHA, identity, timeline, OHLC consistency and exact shared UTC grid; fails closed. The historical validation and final test windows **were already inspected in earlier NEXUS research**. The fixed implementation, every parameter and tests were committed **before the physical replay**; **no post-result changes or parameter optimization** were made. No pure forward holdout is claimed.

Source: `research/elliott_v119_wave2_support/retest_v119.py`, tests `tests/test_nexus_elliott_v119_wave2_support.py`. Exact original read-only local raw replay file `E:\NEXUS-QA\elliott-v119-20261018\physical-v119-fixed-eval.json` (SHA256 `46be9c744f14d73d0be391f3b164d127ef93e5bcc80f701225b34ab8838e2546`), canonical result digest `bd27b37d66caabfd79e7d19ad158bdf665e0efce51772167e98ea05957f90fb8`. Structured summary, fixed parameters, physical funnel and 74 monthly entries remain in `docs/evidence/elliott-v119-wave2-support-20261018/V119_REJECTED_RECONCILED_MONTHLY.json`. The main integration additionally preserves the complete original 111,981-byte ledger at `product_ui/research-reports/elliott-v119-completed-study.json` and independently audits its recorded paths against the exact historical source, without rerunning the backtest. See `ELLIOTT_V119_MAIN_INTEGRATION_20261018.md` for pins, scope and main API/UI consumers. The historical negative decision is unchanged.

### One fixed causal design, no after-the-fact changes

- Every strictly confirmed 15m pivot appears at center+3 physically completed candles. No same-kind favorable historical pivot pruning or rewriting previously seen pivots; ambiguous high+low pivot centers abstain.
- Original three *consecutive* strict events are `LOW → HIGH → LOW`, max 128 bars, minimum original Wave1 move 0.6% of Wave0 price, W2 retracement 38.2%–88.6% of physical W0/W1 extreme movement, W2 strictly above W0. All are **arbitrary frozen exploratory choices**, not wave truth.
- Within 48 bars after physically confirming W2, the physical W2 low must hold. A candle retests within 15% of initial leg height while closing at least 4% of leg above W2, followed by a **separate fully closed bullish reclaim** above the retest candle high but below W1. Signal only after that closed candle; next 15m open fill. Any W2 support breach **before entry** abstains and cannot be retroactively repaired by a profitable rebound.
- Stop at physical W2 low minus 0.2% buffer, but must remain above W0 physical low. Fixed target is lesser of W1 high and 2R measured from next-open mid; reject trade if available structural reward/risk is under 1.5R. This is not optimized from test returns; it was committed before replay.
- Simulated single **500 USDT** shared spot balance per independent partition, max 250 USDT gross per long, at most 2.5 USDT nominal gapless stop risk including full round-trip conservative/stress frictions. No overlap, shorts, leverage or borrowing. Limit is NOT guaranteed for real gaps.
- Every accepted fill is next-bar open with pessimistic slippage. Exit at actual stop-first (including same-candle simultaneous stop/target), worse opening price on adverse gap, predeclared target or 96-bar 24-hour timeout/partition end at **open**, never unknown close. Per-side conservative 10bps assumed fee + 5bps slippage; stress 25bps + 15bps. Exchange tick-size and actual bid/ask liquidation fill were **not** independently proved.

### Entire physical source-signal and cash funnel

| Historical partition | Causal support-reclaim source signals | Denied: reward/risk under 1.5R | Denied: next open invalid | Denied: occupied shared cash | Closed fills |
|---|---:|---:|---:|---:|---:|
| Train | 674 | 551 | 71 | 10 | **42** |
| Validation (preinspected) | 224 | 179 | 23 | 3 | **19** |
| Historical test (preinspected) | 211 | 164 | 23 | 8 | **16** |
| **Total** | **1,109** | **894** | **117** | **21** | **77** |

All 1,109 original signal outcomes are represented; no minimum trade count gate or favorable exclusion after a result. **894/1,109 (80.6%)** have already structurally inadequate target-to-stop geometry. These are rejected *before* paper participation, not 894 losing exchange trades.

### Physical 500 USDT single-account P/L, independent splits

| Partition | Conservative trades/winners | Conservative net | Mean/trade | Stress net | Physical conservative exits |
|---|---|---:|---:|---:|---|
| Train | 42 / 16 | **−22.803146 USDT** | −0.542932 | **−55.037047** | 25 structure stops, 14 targets, 3 timeouts |
| Validation | 19 / 5 | **−19.941467** | −1.049551 | **−30.123315** | 14 structure stops, 5 targets |
| Historical test | 16 / 7 | **−6.407786** | −0.400487 | **−18.817756** | 9 structure stops, 7 targets |

Independent starting cash resets to 500 USDT at each partition; **do not add these as one continuous account P/L**. 74 exact monthly records (37 × 2 cost profiles) in the committed evidence match all six profile trade counts and net P/L sums, with numerical rounding tolerance less than 1e−5 USDT. Across all three independent profiles, normal-cost physical exit causes are **48 structure stops, 26 predeclared targets and 3 timeouts**. Some wins are real outputs of the historical model, but every partition's total cost-adjusted account result is negative.

### Interpretation, verification, and safeguards

The V119 failure is **not** equivalent to V118's four losses; this is a different geometry/entry with a wider multiyear Bybit source, yet it still fails after frictions. The primary economic bottleneck is the overwhelming count of structurally poor next-open target/stop configurations (894 original signals rejected on reward/risk before orders), followed by a majority of stop exits among filled trades and turnover costs. **No parameter tuning on already inspected validation/test partitions** should be used to disguise these outcomes.

- Laptop2 isolated adversarial QA: **17/17 pytest PASS**, native exit 0. Tests enforce strict future-independent pivot timestamp, confirmation+next open, negative high/low geometry, support breach abort, stop-first and gap exit, next-open price and cash cap, fee stress, shared-account overlap, and prohibition on unpinned data.
- Exact physical Bybit archived replay executed on Laptop2 with exit **0**, full source SHA identity verified. Raw result SHA `46be9c...`; compressed documented summary SHA `063dd75d...`; 74 monthly rows reconciled on the same device. This isn't a truly independent strategy performance replication or future OOS.
- **REJECT V119 candidate; no paper/Demo enablement.** No change to laptops' installed NEXUS applications, journals or trading accounts. `live_enabled=false`. Protected Elliott V117 November 16–30 2026 prospective source, frozen grammar and parent V52 remained untouched.
- Scientific next objective should NOT be to retune the above 1.5R/2R/0.2% parameters against these seen windows. Required is an independently proposed **different causally observed market mechanism** (or an original not-yet-inspected future sample), with actual paper exchange connection/fill and safety QA before qualification. The V119 code is retained for falsification/deduplication, not activation.
