# NEXUS Elliott V102 — Bybit V5 public Spot future 1m data-intake contract

**Completed deliverable: offline source schema + future request plan + strict page parsing and fail-closed full-period verification. NOT a fetch, live connection test, Elliott research result or trading strategy.**

## Frozen upstream rulebook and untouched market period

- V101 is a committed and byte-verified research-only preregistration, commit `64d12f7c16d2f31e874aac4850c7a0f0e56588a0`; its `V101_PREREGISTRATION.json` SHA256 is `735d942cdcbf802f6079e5435473e91b7d5b597831087ab4a7439ab04984e221`.
- Immutable future source window: **2026-11-16T00:00:00Z inclusive – 2026-11-30T00:00:00Z exclusive**. Exactly 14 × 1,440 = **20,160** complete 1m candles each for **BTCUSDT / ETHUSDT** (40,320 total). This window is separate from the protected **V52 October 18–November 15** interval.
- Required future source is **Bybit Spot public GET /v5/market/kline, interval=1**. No auth/API keys, no testnet prices, no Bybit Futures/linear sources, no Binance substitution. No network calls in V102, including no premature window probe. The V101 Wave grammar is unchanged; no V101 source window, trading threshold or Wave count was modified.

## Published API reference and request-specific invariants

Official Bybit V5 documentation: https://bybit-exchange.github.io/docs/v5/market/kline (consulted October 2026). The published response is `retCode`, `retMsg`, `result.category`, `result.symbol`, `result.list` with each one-minute kline as **seven string fields**: startTime, open, high, low, close, volume, turnover. The result is **reverse sorted by candle start time**; parameter `limit` cannot exceed **1000**. An unclosed bar's close is the **last traded price**, not a final close, so incomplete minute data may never be admitted.

V102 freezes **21 non-overlapping request pages per symbol**: 20 × 1,000 + 1 × 160 bars, **42 pages overall**. Every descriptor specifies immutable `category=spot`, exact uppercase symbol, `interval=1`, inclusive first candle open timestamp `start`, last expected candle open timestamp `end`, and exact `limit`. The requested end is the **last allowed candle start**, not the first moment after the period. Any API pagination or cursor behavior deviating from that expected exact contract **fails closed** and requires an explicit new protocol rather than silently dropping/reordering data.

## Raw-payload verification gates

Implementation: `research/elliott_v102_bybit_intake/intake_v102.py`.

- Raw bytes retained at collection by the future caller. Each response must be valid UTF-8 JSON under a strict byte cap, with **no duplicate JSON keys** and `retCode` of exact integer 0. It must echo the expected `spot` category, uppercase symbol and **precisely** the requested number of candles.
- Every row must consist of exactly seven typed strings. Candle start timestamps must equal the expected page minute open, **strictly descending in the original Bybit response**, without duplicate, shift, gap, overlap, reordering or substitution. Numeric OHLC, volume and turnover must be finite Decimals; `0 < low <= open,close <= high`; volume and turnover nonnegative.
- The candidate response-receipt timestamp must be after every candle's 1-minute closing instant. A reported server timestamp, where present, must likewise be no earlier than the last row's close. The global dataset **cannot be accepted before 2026-11-30T00:00:00Z by the host clock**, even if a forged receipt claims a future time.
- A full-period source object must contain **all 42 expected page keys and no extras**. All pages must claim receipt after the entire frozen window closed; the concatenated ascending data must have exactly 20,160 contiguous opens per pair and exact period endpoints. Every raw response receives a SHA256; the combined canonical 7-field physical candle list receives a separate SHA256.
- These digests detect later modification **but do NOT cryptographically prove Bybit signed those data**. The public endpoint's normal JSON payload has no origin signature. Future collection therefore requires a separately audited trusted transport, original HTTPS response metadata and collection-time checks. A region-inaccessible Bybit response, API error, stale cache, missing source receipt or source conflict must be reported **BLOCKED**, never swapped to another exchange or passed as validated.

The source-intake method is **deliberately offline**: it receives supplied raw bytes, does not perform HTTP, use credentials, save any Bybit order, construct Elliott signals, call Demo or enable Live. Full acceptance returns *data-integrity accounting only*; it never starts V101 scoring, nor claims an independent pattern certificate. Future V103 may design transport/archive capture but may not fetch the as-yet-unoccurred window.

## QA and research gates

Dedicated test suite: `tests/test_nexus_elliott_v102_bybit_intake.py`. Its samples are explicitly **synthetic future-timestamp fixtures**, not downloaded or real market observations. They verify the correct page plan and 7-field reverse-sorted syntax, complete fake 40,320-bar reconstruction, duplicate/missing/shifted candles, Bybit error, wrong spot category or symbol, unclosed/future bar, NaN, invalid OHLC, tampered manifest, malformed JSON and premature full-source acceptance. Mocking the test clock simulates post-window full ingestion only inside tests, never bypasses the production clock gate.

Immutable plan: `docs/evidence/elliott-v102-bybit-future-intake-20261017/V102_FROZEN_REQUEST_PLAN.json`. Its SHA256 is `3e994e02d3ef1af2f7ab9a9067558dfe00accca8d191d547b8fdc951a5e9a3e6`. Freezer outcome: **42 page requests planned; 0 market rows fetched; 0 real candidate evaluations; 0 orders**.

### Deployment status

PR #2673 remains Draft/unmerged. V52, Laptop1 installation, paper journal and VPS are untouched. Research-only; Bybit Demo/Paper only for any *later separately approved* deployment, Live disabled. **No real Elliott wave, P/L or favorable entry/exit is certified by V102.**

## Completed QA and publication prerequisites

- V102-specific **22/22 synthetic offline tests PASS**, `V102_DEDICATED_EXIT=0`. Complete fake archive tests are NOT Bybit market verification or successful exchange connectivity.
- Full Elliott-specific Laptop2 regression **885/885 PASS**, `Ran 885 tests in 52.075s`, `OK`, `V102_FULL_EXIT=0`. SHA256 of local test log `$env:TEMP\V102_FULL_ELLIOTT_REGRESSION.txt`: `39c207a20dbea51102039fcb0499368d2f45d2b878dead6d1b3c8bc87b1127e8`.
- Frozen, read-only source request plan written and hashed **without sending HTTP**, `V102_PLAN_FREEZE_EXIT=0`; SHA256 `3e994e02d3ef1af2f7ab9a9067558dfe00accca8d191d547b8fdc951a5e9a3e6`.
- V101 predecessor GitHub CI: `Test`, `Research Evidence Refresh`, and `Workflow Permissions Policy` all SUCCESS, prior SHA `64d12f7c16d2f31e874aac4850c7a0f0e56588a0`. V102 GitHub CI requires independent verification after publishing; no success is claimed before the checks return.
