# NEXUS portfolio v3 — future Bybit Spot source freeze and independent validation boundary

**Frozen research proposal date: 2026-10-18 UTC. Status: source blocked; no scored future results exist.**

## Action taken, not a profitable strategy claim

The existing Bybit Spot BTC/ETH portfolio-v3 source-of-truth research runner is fixed to `dual_rotation` ID `b4e4a2c33304aec1`, a one-wallet **500 USDT** research balance, unchanged 4-hour next-open/sell-first long-only fills and three already declared fee + slippage profiles. PR #2723 added a research-only **default-off** 20% high-watermark drawdown switch: it can react **only after a completed 4h close** and liquidates at the next actual 4h opening price, with worse-gap prices not concealed. That PR is merged under commit `2f7ec90a5b01753ec58e5959b0fec6aaa4c2ff01`. Previous isolated source-bound historical economics are already inspected and **not** unobserved future evidence.

The remaining hard blocker is not writing another Elliott/rotation strategy. It is obtaining **independently authenticated, truly newer Bybit Spot candles**, with a frozen pre-scoring protocol and independent QA. The official public read-only endpoints on isolated Laptop2 were checked on 2026-10-18 and returned **HTTP 403 Forbidden** for both `https://api.bybit.com/v5/market/time` and `https://api.bybit.com/v5/market/kline?category=spot&symbol=BTCUSDT&interval=240&limit=2`. That result does **not** prove Bybit is globally down; it verifies a material limitation of the current authorized research device/network. This work does not bypass network restrictions, solicit credentials, pretend another exchange is Bybit or change any live trading authority.

## Exact physical archive tail verified

Isolated Laptop2 original canonical cache, read-only:

| BTC/ETH original 4h archived source fact | Observed value |
|---|---|
| Source symbols | `btc_usdt`, `eth_usdt` |
| Rows in each 4h original Parquet file | **8,034** |
| First 4h bar opening UTC | **2022-12-01T00:00:00Z** |
| Last 4h bar opening UTC | **2026-07-31T20:00:00Z** |
| First required later 4h bar opening UTC | **2026-08-01T00:00:00Z** |
| Duplicate source timestamps | **0** |

The original six cached Bybit Spot BTC/ETH 15m/1h/4h source blobs remain protected by the independently validated per-file immutable SHA locks from #2716, and original v3 shared-cash engine and FIFO evidence from #2720–#2723 remain untouched.

## Prospective time boundaries frozen **before** the new scoring period

`research/portfolio_v3_forward_bybit_source_freeze_20261018.json` is an exact PR-versioned machine-readable study preregistration. The new `scripts/nexus_portfolio_v3_forward_source_preflight.py` rejects a changed original candidate ID, frozen strategy/risk contract, altered 500 USDT capital, cost profiles, 4h granularity, earlier scoring date, unapproved Live/paper authority and swapped source type. It must be considered alongside the GitHub base/merge commits for immutable review—not a merely self-editable runtime config.

- **Historical archive extension**: 2026-08-01 00:00 UTC onward, to bridge the exact known end of July source without one missing original 4h bar.
- **Warmup-only source**: 2026-08-01 through 2026-10-18 23:59 UTC; this history can be used to compute already-fixed rolling regime/risk features but **cannot count as prospective performance** of the 20% risk policy.
- **Scored source start**: **2026-10-19T00:00:00Z**, after this preregistration and after previously inspected historical evidence.
- **Scored source end, exclusive**: **2027-01-17T00:00:00Z** (a precommitted 90-calendar-day prospective study). The result is **not ready** before the horizon is finished and every BTC/ETH 4h bar through the last eligible close is independently authenticated.
- **Unchanged models for future review**: `dual_rotation` without guard versus the exact versioned 20% closed-4h/next-open/no-reentry risk option, and passive BTC, passive ETH, passive 50/50 and cash-only controls under the same common Spot cash and declared normal/stress/severe cost assumptions.
- **No automatic economic winner-selection**: log net USDT, separately count buy/sell executions and FIFO lot segments, maximum drawdown (including any threshold overshoot), source timestamps, fees, and portfolio-relative metrics. There is **no minimum trade count threshold**. Do not change parameters after the first future results or call Q1/2023–2026 historical events a fresh holdout. Any later risk-engine version change needs a new explicitly dated study and another truly future horizon.

## Fail-closed integrity preflight and its hard limit

`scripts/nexus_portfolio_v3_forward_source_preflight.py` accepts **only** a declared original direct Bybit Spot HTTP 4h source receipt and two original-source-parsed Parquet datasets, BTCUSDT and ETHUSDT. It does **not** scrape/fetch or override the observed HTTP 403. It checks exact byte SHA of each raw file against the claimed receipt, exact 4h UTC grid from 2026-08-01 through 2027-01-17 exclusive (without any implicit resampling or gap filling), no duplicates, both peers on the same grid, physically valid positive OHLC/nonnegative volume, completed entire scored horizon, and explicit UTC timestamps. It rejects the claimed source from Bitget/LBank, any modified source digest, wrong source HTTP code, naive local clock conversion, in-progress future reporting, out-of-range dates, changed 500 cash/risk policy and false Live authorization.

**A user-supplied receipt, an HTTP status field and even matching raw SHA256 do NOT prove the exchange supplied those bytes.** The preflight therefore **always** states `market_data_real_exchange_provenance_independently_verified=false`, `external_provider_qa_still_required=true`, `ready_for_strategy_result_or_paper=false`, `paper_eligible=false`, `live_enabled=false`, `orders=0`. Only a separate verifiable capture and external independent QA review can approve source provenance; only later, separately approved research code could execute the frozen study. No alternate research feed inherits the Bybit provenance label. If direct Bybit remains unavailable, the study stays source-blocked, without manufactured outcomes.

This preflight is strictly **coverage/integrity checking, not a source authentication certificate, trading strategy, order adapter, backtest or Paper/Live authorization**.

## Independent local QA evidence

On isolated Laptop2, exact checked-in branch content was copied into a separate `E:\NEXUS-QA\portfolio-v3-forward-source-20261018` tree. Native **18/18 pytest tests PASS** (purely adversarial and explicitly generated **synthetic test fixtures**, not a real future market replay): original freeze content and start time, preventing changes to candidate/cash/risk/time/authority, rejecting today's date even if someone supplies fabricated future-looking candles, full-grid happy path that **still disclaims independent provider authenticity**, missing/duplicated 4h records, tampered source bytes, substituting another exchange, falsified collection time, illegal OHLC and volume, and timezone-naive data. Source root uses the existing GitHub project, never the installed product runtime.

**No automated recurring monitoring was created.** No new future market file has been accepted. No installed Laptop1 Demo/Paper/Bybit credential or running Windows runner was modified. No speculative next-week trading availability promise is made.

## Honest gate decision

`BLOCKED_BY_DIRECT_BYBIT_PUBLIC_HTTP_403__FUTURE_SOURCE_NOT_AVAILABLE__NO_FUTURE_ALPHA_RESULT`.

The preregistration provides a fixed boundary that later independent QA can apply, but it cannot supply future evidence today. Continue the actual NEXUS trading research only once the official source can be independently collected and authenticated; then execute the frozen research model with exact next-open fills, original 500-cash FIFO accounting, risk/no-risk comparison and costed passive benchmarks, **without retuning after observing results**. Even positive prospective results would trigger an independent Paper-only operational review, **never live trading**.
