# Official Spot warmup capture and fixed portfolio preparation

This extends the existing reviewed daily Spot raw-trade adapter from PR2727. It supplies the missing historical context for the already fixed `dual_rotation` candidate `b4e4a2c33304aec1`; it does not search strategies, score a historical warmup as future evidence, or enable a trading account.

## Bounded data work

Run `python -m scripts.nexus_bybit_official_spot_warmup_capture --output <isolated-directory> --prior-sample-root <existing-six-sample-cache> --prior-sample-manifest research/bybit_official_spot_daily_raw_sample_claims_20261018.json`.

The only requested source is the direct HTTPS official Bybit Spot archive. Exactly 158 symbol/day files cover BTCUSDT and ETHUSDT from **2026-08-01 through 2026-10-18 UTC**. The four already pinned warmup samples are copied after their byte hashes are checked. New files require exact URL, HTTP200, no redirect, a complete bounded response body and successful parsing by the existing pinned adapter. No failed request is retried automatically. Memory is bounded to one download chunk and six candle buckets; the total gzip budget is1.5GB. Each completed day has an immutable hash-linked acquisition/parse checkpoint. A resumed run rechecks the same request/code identity and raw hashes; an incomplete or unreceipted file stops for explicit recovery.

The expected physical extension is474 closed4h candles per asset,948 in total. No future-scoring date can be requested through this command. New raw gzip files remain in the isolated research cache, not the Git repository or owner Paper journal.

## Independent numerical source QA

Run `python -m scripts.nexus_bybit_official_spot_warmup_qa --capture-root <isolated-directory> --original-archive-root <pinned-original-archive> --output <new-qa-receipt.json>`.

This implementation does not import the producer. It streams every raw tick through separate Decimal OHLCV aggregation, checks the158 exact paired days, tick identities/times, actual first/last tick, volume, HTTP acquisition receipts, byte hashes and all948 candle comparisons. It also re-attests all six original immutable BTC/ETH15m/1h/4h Parquet SHA256 identities before any future join. Source receipts and matching historical candles are not an exchange-signed payload or external provider attestation; those authority flags stay false. No old history is overwritten or joined by these commands.

Actual completed data/QA receipts, raw trade counts, byte totals, digests and execution state are recorded in issue2007 and the PR's verified execution section; expected coverage above is not a substitute for that evidence.

## Original system and Manager state

`research/portfolio_v3_fixed_source_handoff_20261019.json` binds the unchanged engine, calibration and original future freeze by LF-normalized SHA256. It explicitly preserves the30/90/180-day score, positive90-day eligibility,30-day volatility,30% annual volatility target,0.25 allocation increments, one shared500-USDT cash book, next-open sell-first execution and original source-anchored42-bar review cadence. Eligibility/targets are held between those original review rows. The original engine has no per-lot physicalSL/TP; this limitation is disclosed rather than silently replaced. The original unguarded and optional fixed post-hoc DD20 comparisons and all three cost profiles stay separate.

One **BLOCKED preparation task** is appended to the existing Manager definition. All26 previous task definitions, worker definitions and policy fields are preserved. The task is not represented as dispatched, active Research, economic QA or complete. It cannot be released by the ordinary PENDING-to-READY transition. The original factory's15m/250-USDT executor is not relabeled as the portfolio engine.

The fixed **2026-10-19 through2027-01-17 exclusive** prospective horizon is incomplete today. A separately reviewed official-archive source policy, complete future data and a reviewed exact-portfolio Research/QA handoff remain necessary before financial dispatch. The V5-only frozen future preflight and future windows are unchanged. No new monitor, recurring task, candidate search, owner installation change, Paper/Live authority or order is introduced.

## Validation

Native Laptop2:32 capture/source tests passed with one existing Windows symlink-privilege skip;7 independent Decimal QA tests passed;3 fixed-system/Manager tests passed. These42 passing tests exercise denied/redirected/truncated source requests, fixed historical date bounds, missing/invalid tick buckets, exact Decimal volume, unchanged system/source hashes and persistence of the blocked task. Required hosted checks must pass on the exact PR head before merge. Live=false; orders0.
