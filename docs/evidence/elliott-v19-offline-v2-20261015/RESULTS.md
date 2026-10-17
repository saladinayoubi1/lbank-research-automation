# NEXUS Elliott V19 — isolated offline source-bound Bybit trade archive pilot

**Execution:** 2026-10-15, Laptop2 `DESKTOP-F4SA4VL`, research-only. **Native result:** `PASS_TWO_DAY_OFFLINE_V2_ARCHIVE_NO_FUTURE_BRIDGE`. The new dataset is **NOT eligible** for a prospective Elliott backtest or Demo.

## Objective and execution

Build and independently qualify a **fresh, separately versioned** raw-trade-aggregation archive without changing historical source, Paper state, or relying on the blocked public Bybit API.

- New physical destination: `E:\NEXUS-QA\elliott-v19-trades-v2-20261015`. This did not exist before the operation. Code [build_two_day_source_bound_v2.py](build_two_day_source_bound_v2.py) **refuses preexisting roots** and any root overlapping original source/cache directories. It does **not** call the provider or network.
- Existing unmodified local trade source directory: `C:\NEXUS\research-cache\a9-spot-20260703-20260801`.
- Dates: **July 31–August 1, 2026 inclusive**. Symbols: BTCUSDT and ETHUSDT. Full official repo `bybit_spot_backfill.run_backfill` v2 path, with **injected explicit offline archive inventories and read-only local-source loader**, was used rather than a new ad hoc resampler.
- Four local gzip files fed the engine. SHA-256s below are of the existing files, with no claimed independently re-attested exchange origin:

| Pair | 2026-07-31 raw trade .csv.gz | 2026-08-01 raw trade .csv.gz |
|---|---|---|
| BTCUSDT | `3d2a7d32eed34a28ee90c2861b29fc2d5fbf1461f7f6b0223ae9bc05836aae7a` | `be6bf75c371f8cd1afd302bad339e91a17bc6b189343b6712a587b0fba5f7d94` |
| ETHUSDT | `1b81677c2afdaacb9492c01d0a55c5a47ba73d93909405691814f25c9ad8f851` | `c70b166659252a288f77ffbf409b90e6896bf6fd2bdc1aba6da14e1f2f7429f5` |

Generated six fully contiguous series in the **new** V2 model:

| Pair | 15-minute bars | 1-hour bars | 4-hour bars |
|---|---:|---:|---:|
| BTCUSDT | 192 | 48 | 12 |
| ETHUSDT | 192 | 48 | 12 |

The new archive includes `_candle_model.json`, `_source_manifest.json`, `_checkpoint.json`, the official repo's backfill status/report and six independent parquet files. `bybit_spot_backfill.validate_candle_model_state` accepted the separate v2 root with original source row-order tie handling; the full two-day source grid passed its existing integrity checks.

## Independent preservation and reconciliation

1. Before comparing price values, we checked each of the six original July archive **raw parquet SHA-256 identities** against the frozen `REPLAY_DATASET_MANIFEST.json` values: **all six matched**. Original research and frozen trading losses remain unchanged.
2. Compared July 31 overlap for all 5 OHLCV fields and 3 timeframes, each across BTC and ETH: `(96 + 24 + 6) × 5 × 2 = 1,260` numerical comparisons, at `1e-8` absolute representation tolerance, and exact UTC timestamp order: **1,260 compared, zero material differences**.
3. Independently hash-recorded all four raw gzip inputs and all six new parquet artifacts in [NATIVE_OFFLINE_V2_PILOT_RECEIPT.json](NATIVE_OFFLINE_V2_PILOT_RECEIPT.json), taken from Laptop2 actual execution; **no claim of source freshness**.
4. **168/168** Elliott research native unit/regression tests passed on Laptop2 at exact source revision before this report. **12/12** native `pytest` tests of `tests/test_bybit_spot_backfill.py` and `tests/test_bybit_backfill_semantics_migration.py` passed. Eight new V19 fail-closed isolation/offline/source-identity regressions are included in the 168.

This expands the earlier V18 eight July 15m candles per symbol to a **full-day raw-trade reproduction across all three timeframes**. The small previously transcribed public Kline API observation still disagrees at 13 OPEN values and one ETH LOW; no source has been overwritten, and that un-attested API transcription is not treated as canonical.

## What this DOES NOT solve

- A two-day V2 pilot starting July 31 is **not** the required full independent trade-derived July/2022–October historical replay or a complete gap-fill from **2026-08-02 through the V17 prospective window**. It cannot simply be attached to the original version-ambiguous 2022–July archive. The continuation must remain **one end-to-end model version** with a source manifest and no gap.
- The cached gzip files are independently hashed but not separately proven to originate from a specific present-day official provider endpoint; prior public API access became HTTP 403. Further collection must use supported, permitted official/public sources and retain raw downloads, not work around restrictions.
- No new 2026-10-16+ 15m closed Bybit market samples, Elliott event outcomes, recursive wave counts, historical backtest reruns, prospectively verified target/stop fills, positive net expectancy, or exchange orders were produced.

## Architecture / disposition

DATA-20 (only independently versioned and source-bound candles) → RES-31/32 (V15 and V14 source provenance) → VAL-40 (V17 fixed research exit contract) → QA-41 (independent receipts). **Promotion to REG-50 / PAPER-62 is blocked** pending complete source, economic, and recursive-label qualification. This pilot generated no Bybit private API calls, trading signals, live orders or Demo changes. Laptop1's installed application, 500 USDT reference balance, research journals and paused VPS were untouched.

**GitHub:** Research stacked Draft PR #2673, related Issue #2672. This file is explanatory evidence; the source-of-truth machine result is the JSON receipt and the six generated files kept locally on Laptop2.
