# Elliott V18 — July trade-origin forensic root cause

**2026-10-15. Source diagnosis advanced.** This is a read-only study of **16 already-inspected July 2026 candles**, not a prospective market trial, strategy backtest or evidence of profitability.

## Pinned evidence

Two gzipped **raw public spot trade archives** already cached on Laptop2 were used **offline**, with no new network request and no changes to the original archive:

- BTC `C:\NEXUS\research-cache\a9-spot-20260703-20260801\BTCUSDT_2026-07-31.csv.gz`, SHA-256 `3d2a7d32eed34a28ee90c2861b29fc2d5fbf1461f7f6b0223ae9bc05836aae7a`.
- ETH `C:\NEXUS\research-cache\a9-spot-20260703-20260801\ETHUSDT_2026-07-31.csv.gz`, SHA-256 `1b81677c2afdaacb9492c01d0a55c5a47ba73d93909405691814f25c9ad8f851`.

Compared against byte-pinned original `minute15.parquet` for each pair (July 31, **22:00–23:45 UTC**), and against the eight-bar-per-pair **previously transcribed, un-attested** spot `/v5/market/kline` stdout. Source code and exact receipt: [reconstruction script](reconstruct_from_cached_trades.py), [native receipt](CACHED_RAW_TRADES_RECONSTRUCTION_QA.json).

**Replay manifest integrity:** original `REPLAY_DATASET_MANIFEST.json` self-digest `2473b69a7e79d9b5a3b2afce92518f99fa1626e1a3aa3bf1d460dfebc2d5d572` independently reconciles. Its declared source is `official_public_spot_trade_archives`, not `/v5/market/kline`. The replay ZIP's `schema_version: 2` **does not** establish that its source candle model is the separately versioned `nexus.bybit-source-row-stable-candles.v2`: the manifest has no `candle_model` field or new source sidecars. The existing `bybit_spot_backfill.validate_candle_model_state` independently rejected this old archive for mixed-model appending.

## Verified count of **material** field discrepancies

Numerical comparisons allow at most `1e-8` absolute numeric representation drift (e.g. a `2e-15` float serialization difference in one volume is **not** corruption).

| 8-bar symbol subset | Reconstructed v2 trade candles vs frozen archive | Legacy timestamp-only trade resampling vs archive | Unattested API transcription vs archive |
|---|---|---|---|
| BTCUSDT | **0** differences | **1 CLOSE** difference | **6 OPEN** differences |
| ETHUSDT | **0** differences | **0** differences | **7 OPEN + 1 LOW** differences |

- The **v2 row-stable raw-trade reconstruction exactly reconciled all OHLCV values in the 16 frozen bars**. This is strong narrow forensic evidence that the original 15m historical parquet bars are reproducible from the cached public trade records. It does **not** prove their full 2022–2026 source lineage, and it is not proof that the current public Kline API is wrong.
- The older `bybit_spot_archive_audit.validate_trades + trades_to_candles` method, which sorts equal timestamps without the v2 original-row-order contract, generated one BTC CLOSE difference at **2026-07-31 22:30 UTC**: **62946.7 instead of 62945.1**. This is a concrete demonstration of source-row/tie semantics affecting an endpoint price; other field values in the eight BTC bars matched.
- The API observation is **a transcription of initial terminal stdout, NOT captured HTTP source bytes**. Its 14 OHLCV differences remain a source-method/attestation issue. The raw trades and REST Kline aggregates are *not semantically identical datasets by assumption*. The one ETH LOW transcription difference is 0.01 (1861.35 vs frozen 1861.36); no general low-price correction is authorized.

## Defensive fix: no silent archive splice

`nexus_elliott_forward_bridge_v18.py` now verifies the canonical replay manifest SHA and categorizes any archived replay **without a manifest-bound v2 candle-model receipt** as `BLOCKED_LEGACY_UNVERSIONED_TRADE_CANDLE_MODEL`. It blocks appending *even if* a new continuation file happens to exist, with `BLOCKED_CANDLE_SEMANTICS_REPLAY_REQUIRED`. It does **not** conflate replay-package schema version 2 with source-candle model version 2.

The defensive code checks the separate `_candle_model.json` and `_source_manifest.json` sidecars before invoking the existing backfill validator; otherwise an empty-root early-return could falsely appear to verify the model. Five new fail-closed tests cover fake binding, digest tampering, REST-vs-trade source category and missing v2 receipts.

### Practical next task (not attempted by this bounded investigation)

1. Keep all legacy source parquets and previous losing backtests unchanged. **Do not patch the 14 Kline differences into those parquets.**
2. Use the existing official public raw trade archive backfill `bybit_spot_backfill.py` to create a **new, separate, model-v2 versioned root** with preserved raw-gzip identities, original source-row tie ordering and source manifests, initially reproducing the contested July candles and then the required contiguous 2026-08-01 onward period.
3. Validate a full 15m/1h/4h source-model-consistent UTC grid for both pairs, with source receipts. Do not mix reconstructed trade candles and API Kline candles in one unversioned series. Further source discovery must respect any provider 403 and access restrictions.
4. Only after verified new prospective closed 15m observations can the independent V15/V14 source evaluator feed the **paperless** V17 exit accounting. Existing recursive Elliott wave-count and market-edge gaps remain; neither Demo nor Live is authorized.

**Boundaries:** Laptop2 isolated research, existing 500 USDT reference Paper and Laptop1 remain untouched, Live=false, auto-Demo=false, VPS paused; Draft PR #2673 and Issue #2672 are the review surfaces.
