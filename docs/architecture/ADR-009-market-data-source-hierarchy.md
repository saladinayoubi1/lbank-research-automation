# ADR-009: Market-data source hierarchy and reconciliation authority

- Version: 1.1.0
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

## Security, privacy, reliability and AI-governance boundary

- Public market data is not treated as secret, but request metadata, local paths, operator identifiers, API keys, account identifiers, cookies, IP-derived metadata and any future authenticated headers are sensitive and must never be persisted into public manifests or logs.
- This ADR authorizes no authenticated exchange access. Any future credential-bearing adapter requires a separate versioned ADR and threat/privacy review.
- AI workers/reviewers are advisory only. They may propose mappings, explanations or candidate fixes, but may not weaken gates, merge/release changes, redefine source authority, accept ambiguous evidence, or authorize live trading.
- Availability does not override integrity: failure to obtain secondary data must produce an explicit unavailable/unknown state, not a widened tolerance or synthetic continuity.

## Assets

- canonical OHLCV history;
- source manifests and checksums;
- canonical symbol/timeframe mapping registry;
- listing and delisting boundaries;
- freshness and integrity status;
- reconciliation and gap-inventory outputs;
- downstream backtest/paper-trading decisions;
- evidence that a dataset was accepted or rejected under a specific policy version.

## Actors and trust boundaries

Actors: Bybit public API, Binance public API, LBank public API, ingestion/backfill agent, repository workflows, deterministic validators, human reviewers, downstream research/paper consumers, and optional AI workers/reviewers.

Trust boundaries:

1. exchange public API -> source adapter;
2. source adapter -> canonical schema;
3. mapping registry -> reconciliation engine;
4. reconciliation result -> persisted dataset/manifest;
5. validated dataset -> downstream consumers;
6. repository policy/tests -> merge authority;
7. AI-produced proposal -> deterministic validator/human review.

## Threat model

Assume an attacker or failure can control or corrupt any single external response, cached page, adapter output, mapping entry, manifest path, environment variable, workflow step or AI-generated proposal. Assume accidental operator error is as important as malicious input. Do not assume simultaneous compromise of all independent reviewers/providers, but explicitly test simultaneous weakening of policy+validator+tests because a repository-local control plane can otherwise self-authorize.

Security objectives:

- source identity and market semantics remain explicit and non-substitutable;
- accepted datasets are reproducibly attributable to source, mapping-policy version and validation result;
- ambiguous or unverifiable evidence cannot become downstream-eligible;
- raw/unvalidated paths cannot bypass readiness gates;
- rollback restores a complete previous-known-good policy/adapter/validator/test tuple.

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
- alternate path/manifest substitution;
- policy+validator+test simultaneous weakening;
- AI suggestion accepted without deterministic compatibility/provenance validation;
- secrets or operator-identifying metadata written into manifests/logs.

## Deny-by-default policy

Any unknown or ambiguous market identity, unsupported mapping, stale/unavailable source, incomplete page, missing provenance, open candle, checksum mismatch, malformed OHLCV, timestamp-grid violation, duplicate/out-of-order row, unresolved gap or unexplained cross-source disagreement results in:

- `integrity_ok=false`;
- explicit deterministic reason code;
- quarantine/no promotion of the candidate dataset;
- no eligibility for Backtest, Strategy Lab, Decision Engine or Paper Trading.

Availability pressure must never widen integrity thresholds merely to obtain a green state. Unknown schema/version or unpinned implementation semantics must also fail closed.

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
- source endpoint/documentation version or retrieval contract;
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

## Required tests and evidence

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
- unexplained material OHLC disagreement;
- missing/unknown documentation contract version;
- secret/operator metadata leakage into persisted manifest.

Bypass:

- raw-file consumer path;
- alternate manifest/path substitution;
- silent source promotion without provenance;
- broad tolerance masking a disagreement;
- duplicate display symbol with different market identity;
- policy+validator+test simultaneous weakening;
- AI-proposed mapping accepted without deterministic validation.

Merge evidence must include executable test names/results bound to one exact final head SHA. A prose test plan alone is not implementation evidence.

## Rollback and recovery

Rollback restores the previous-known-good source-policy, adapters, mapping registry and validator/tests as one versioned tuple. Preserve rejected candidate data and before/after checksums for audit rather than overwriting previous-valid evidence.

Recovery replays a fixed source window, regenerates manifests deterministically, proves the rejected candidate remains quarantined, and re-runs the full continuity/uniqueness/grid/OHLC/row/freshness/cross-timeframe suite before downstream eligibility is restored.

Before implementation merge, perform at least one rollback/recovery exercise on a deliberately invalid candidate and retain the exact commands, fixed input window, expected rejection reason, before/after digests and successful restoration evidence.

## Evidence triangulation

### Official standard

- NIST SP 800-218 SSDF v1.1 (final, February 2022): secure-development practices, tracked security requirements, risk handling and integrity-oriented development evidence. https://csrc.nist.gov/pubs/sp/800/218/final
- NIST SP 800-218 Rev.1 / SSDF v1.2 initial public draft (December 17, 2025) is an obsolescence trigger, not a replacement baseline until finalized. https://csrc.nist.gov/pubs/sp/800/218/r1/ipd

### Independent academic evidence

- Torres-Arias et al., “in-toto: Providing farm-to-table guarantees for bits and bytes,” USENIX Security 2019. The paper shows that compromise of one supply-chain step can invalidate downstream trust and motivates verifiable provenance across steps. https://www.usenix.org/conference/usenixsecurity19/presentation/torres-arias
- Albers et al., “Fragmentation, Price Formation, and Cross-Impact in Bitcoin Markets,” 2021. The work documents venue fragmentation and leader/lagger effects, supporting the limitation that venue-specific market data is not a universal truth oracle. https://arxiv.org/abs/2108.09750

### Implementation/source evidence

- Bybit V5 Get Kline distinguishes product `category`, returns rows reverse-sorted by `startTime`, and documents contract-dependent volume/turnover units. https://bybit-exchange.github.io/docs/v5/market/kline
- Bybit V5 WebSocket Kline exposes `confirm` to distinguish closed from still-open candles. https://bybit-exchange.github.io/docs/v5/websocket/public/kline
- Binance is permitted only as secondary evidence after the implementation pins and tests the exact official endpoint/documentation contract used. If the exact Binance semantics cannot be verified from official documentation for the chosen endpoint, reconciliation must return `incompatible_source`/`unknown` rather than infer equivalence.

### Limitation / opposing view

Cross-exchange comparison improves detection coverage only for semantically equivalent instruments. Legitimate venue-specific prices, liquidity, fee regimes, listing windows, contract definitions, volume units and microstructure can differ. Therefore Binance corroboration can reduce single-source blind spots but cannot prove a single universal “true” OHLCV and must never silently replace Bybit execution-market semantics.

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
- any incident revealing a new reconciliation or bypass class;
- final publication of a later NIST SSDF revision that materially changes applicable requirements;
- introduction of authenticated exchange APIs or sensitive/account data.

## Merge gate

This ADR may remain a documentation-only proposal, but implementation that depends on this hierarchy must not merge until the versioned mapping/manifest contract, fail-closed validator, positive/negative/bypass tests, rollback/recovery exercise and exact-head CI are aligned on one fixed SHA; the PR is mergeable; unresolved review threads are zero; and every material claim is backed by an official, independent or implementation source plus an explicit limitation where applicable.

Documentation-only CI success does not satisfy the implementation gate. This ADR grants no live-trading or production authority.

Refs #107 #125 #130 #131
