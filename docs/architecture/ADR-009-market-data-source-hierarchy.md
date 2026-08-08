# ADR-009: Market-data source hierarchy and reconciliation authority

- Version: 1.0.0
- Status: Proposed
- Scope: public market-data ingestion, reconciliation, backfill eligibility, and downstream data-readiness authority
- Authority boundary: research and paper-trading data only; no credential, real-order, production-release, signing, billing, or live-financial authority

## Context

NEXUS requires a stable source hierarchy for market data used by Backtest, Strategy Lab, Decision Engine and Paper Trading. Cross-exchange data is useful for corruption/gap detection, but exchanges can legitimately differ in instrument identity, listing windows, contract semantics, volume units, candle finality and price formation. Therefore a secondary source cannot be treated as an implicit truth oracle or silently substituted into a primary exchange namespace.

Issue #131 defines the intended hierarchy: Bybit is the primary market/execution reference, Binance is secondary corroborating public-data evidence, and LBank is tertiary/research-only. Existing LBank datasets remain subject to #125 and may not be promoted merely because another venue has a candle at the same wall-clock timestamp.

## Decision

1. **Bybit is primary** for market identity and paper-trading/execution semantics.
2. **Binance is secondary** for compatible cross-validation and bounded backfill evidence.
3. **LBank is tertiary** and research-only, used only with explicit source provenance.
4. Cross-source reconciliation is allowed only when a canonical mapping proves the instruments and timeframe semantics are compatible.
5. No adapter, backfill job or downstream consumer may silently relabel Binance/LBank candles as Bybit candles.
6. Unsupported, unavailable or ambiguous source intervals remain explicit `unknown` / `unavailable`; no synthetic or interpolated candle is created.
7. Downstream eligibility is fail-closed. Missing provenance, stale/partial pages, open candles, malformed OHLCV, duplicate/out-of-order/off-grid rows, unresolved gaps, checksum mismatch or unexplained cross-source disagreement must set `integrity_ok=false` with deterministic reason codes.

## Assets

- canonical OHLCV history;
- source manifests and checksums;
- canonical symbol/timeframe mapping registry;
- listing and delisting boundaries;
- freshness and integrity status;
- reconciliation and gap-inventory outputs;
- downstream backtest/paper-trading decisions.

## Actors and trust boundaries

Actors: Bybit public API, Binance public API, LBank public API, ingestion/backfill agent, repository workflows, deterministic validators, human reviewers, downstream research/paper consumers, and optional AI workers/reviewers.

Trust boundaries:

1. exchange public API -> source adapter;
2. source adapter -> canonical schema;
3. mapping registry -> reconciliation engine;
4. reconciliation result -> persisted dataset/manifest;
5. validated dataset -> downstream consumers;
6. repository policy/tests -> merge authority.

External AI workers/reviewers are advisory only. They may not own credentials, weaken gates, merge/release changes, alter core goals, or redefine risk/data policy.

## Abuse cases and failure modes

Reject or quarantine at minimum:

- endpoint/source spoofing or accidental endpoint substitution;
- symbol alias collision or spot/perpetual substitution;
- wrong contract category or settlement asset;
- timestamp unit/timezone/grid mismatch;
- partial pagination accepted as complete;
- reverse/forward ordering assumptions that hide gaps;
- stale or replayed historical pages;
- open/incomplete candles accepted as closed history;
- volume/turnover unit mismatch across venue/contract types;
- listing-boundary mismatch mislabeled as a source gap;
- broad OHLC tolerance masking material disagreement;
- duplicate, out-of-order or off-grid rows;
- manifest/checksum mismatch or unknown schema;
- silent fallback from Bybit to Binance/LBank;
- raw-file downstream bypass that skips readiness validation;
- simultaneous weakening of source policy, validator and tests.

## Deny-by-default policy

Any unknown or ambiguous market identity, unsupported mapping, stale/unavailable source, incomplete page, missing provenance, open candle, checksum mismatch, malformed OHLCV, timestamp-grid violation, duplicate/out-of-order row, unresolved gap or unexplained cross-source disagreement results in:

- `integrity_ok=false`;
- explicit deterministic reason code;
- quarantine/no promotion of the candidate dataset;
- no eligibility for Backtest, Strategy Lab, Decision Engine or Paper Trading.

Availability pressure must never widen integrity thresholds merely to obtain a green state.

## Compatibility contract

A cross-source mapping must identify at least:

- source exchange;
- source symbol and canonical symbol;
- market category (spot/perpetual/futures where applicable);
- quote/settlement asset;
- timeframe and timestamp convention;
- candle finality semantics;
- listing/delisting window;
- volume/turnover unit semantics;
- mapping policy version.

If any required field is unknown or incompatible, cross-source reconciliation is not authorized for that interval.

## Reconciliation and backfill contract

For every missing interval, persist a machine-readable record containing:

- canonical market identity;
- timeframe;
- expected timestamp/range;
- neighboring canonical/source timestamps;
- source endpoint/archive identifier;
- retrieval result;
- source and mapping policy versions;
- checksum before and after candidate reconciliation;
- classification: `recovered`, `source_unavailable`, `source_missing`, `request_failed`, or `incompatible_source`.

Backfill must be deterministic and idempotent. Replaying the same fixed source window under the same policy must produce the same normalized output and manifest digest.

## Validation requirements

After every reconciliation or backfill candidate, re-run:

- continuity;
- timestamp uniqueness;
- ordering;
- timestamp-grid alignment;
- OHLC validity;
- expected-row accounting;
- freshness;
- source-manifest/checksum validation;
- cross-timeframe consistency where defined;
- downstream fail-closed eligibility checks.

## Required tests

Positive:

- exact compatible instrument mapping;
- closed canonical candles;
- deterministic pagination replay;
- idempotent reconciliation;
- stable source manifest/checksum;
- compatible cross-source gap corroboration.

Negative:

- wrong category/symbol/timeframe;
- spot/perpetual substitution;
- stale/missing page;
- open candle;
- duplicate/out-of-order/off-grid row;
- malformed OHLC;
- listing-edge unavailable interval;
- checksum mismatch;
- incompatible volume/contract semantics;
- unexplained material OHLC disagreement.

Bypass:

- raw-file consumer path;
- alternate manifest/path substitution;
- silent source promotion without provenance;
- broad tolerance masking a disagreement;
- duplicate display symbol with different market identity;
- policy+validator+test simultaneous weakening.

## Rollback and recovery

Rollback restores the previous-known-good source-policy, adapters, mapping registry and validator/tests as one versioned tuple. Preserve rejected candidate data and before/after checksums for audit rather than overwriting previous-valid evidence.

Recovery replays a fixed source window, regenerates manifests deterministically, proves the rejected candidate remains quarantined, and re-runs the full continuity/uniqueness/grid/OHLC/row/freshness/cross-timeframe suite before downstream eligibility is restored.

## Evidence and limitations

- Bybit V5 market APIs distinguish product category and document candle ordering/finality semantics; these are part of the source-compatibility boundary.
- Binance public market-data APIs provide an independent venue useful for corroboration, but a Binance candle is not semantically identical to a Bybit candle solely because symbol text and timestamp match.
- LBank remains useful as explicitly tagged tertiary research evidence, especially for markets absent elsewhere, but existing LBank continuity gaps remain fail-closed under #125.
- Cross-exchange comparison improves detection coverage but cannot prove a single universal "true" OHLCV because legitimate venue-specific prices, liquidity, listing windows and volume differ.

## Obsolescence triggers

Re-review this ADR on changes to:

- Bybit/Binance/LBank API endpoint or schema semantics;
- symbol/category/settlement model;
- pagination/order rules;
- timestamp precision/timezone behavior;
- candle close/finality semantics;
- volume/turnover units;
- supported intervals;
- listing/delisting behavior;
- canonical schema or mapping registry;
- downstream authority boundary;
- addition of a new exchange/data provider;
- any incident revealing a new reconciliation or bypass class.

## Merge gate

Implementation that depends on this hierarchy may merge only when the versioned mapping/manifest contract, fail-closed validator, positive/negative/bypass tests, rollback/recovery procedure and exact-head CI are aligned on one fixed SHA; the PR is mergeable; and unresolved review threads are zero. This ADR itself grants no live-trading or production authority.

Refs #107 #125 #130 #131
