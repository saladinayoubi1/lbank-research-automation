# ADR-009A: Provenance-manifest semantic binding addendum

- Version: 1.0.0
- Status: Proposed
- Parent: `ADR-009-market-data-source-hierarchy.md`
- Scope: research/public market-data provenance manifests only
- Authority boundary: no credentials, live trading, signing, billing, production deployment, or financial action

## Context

ADR-009 requires source, market, timeframe, retrieval-window and provenance semantics to remain explicit and fail-closed. A content digest alone is insufficient if an attacker or bug can relabel the same candle bytes under a different timeframe/window/source identity and then recompute a self-consistent digest.

PR #160 introduces a deterministic manifest primitive. This addendum narrows the policy requirement for that primitive without approving any real cross-exchange mapping or downstream research eligibility.

## Decision

A market-data provenance manifest is valid only when both content and semantics are independently consistent with the declared contract. Validators must derive and enforce supported fixed-duration timeframe cadence/grid locally, bind the exact declared retrieval window to the first/last timestamp and expected row count, reject unknown fields/schema/source/category, and reject sensitive credential-like metadata recursively.

A self-consistent rehash after changing `timeframe`, retrieval-window bounds, source identity, market category, mapping-policy identity, or endpoint contract must not be treated as proof that the candidate is semantically equivalent. Digest recomputation is integrity evidence for a specific declared tuple, not authorization to change that tuple.

## Threat and abuse cases

Reject or quarantine at minimum:

- semantic timeframe relabeling plus recomputed manifest digest;
- mixed cadence hidden behind a supported timeframe label;
- off-grid timestamps under an otherwise valid digest;
- partial-window or shifted-window substitution;
- source/category/endpoint identity substitution followed by rehash;
- unknown manifest fields or schema downgrade/extension accepted silently;
- credentials, tokens, cookies, authorization headers, private keys or similar secrets embedded in metadata;
- duplicate/out-of-order rows or candle tamper with a stale digest;
- policy/validator/test changes that remove these checks while preserving a superficially green pipeline.

## Deny-by-default policy

Any unsupported timeframe, grid/cadence mismatch, incomplete declared window, semantic relabeling, source/category ambiguity, unknown schema/field, digest mismatch, sensitive metadata, malformed OHLCV structure, or unexplained substitution results in rejection and no downstream eligibility.

The manifest validator does not approve cross-exchange equivalence, source mappings, reconciliation, persistence, or promotion. Those remain governed by ADR-009 and Issue #131.

## Required verification

Positive:
- deterministic manifest generation for the same canonical candle sequence and declaration;
- exact supported timeframe cadence and declared-window coverage;
- stable content and manifest digests.

Negative/bypass:
- timeframe relabel + rehash;
- wrong cadence, mixed cadence and off-grid timestamps;
- partial/shifted retrieval window;
- candle tamper and metadata tamper;
- unsupported source/category/timeframe;
- unknown manifest fields;
- recursive sensitive-metadata injection;
- duplicate/out-of-order rows.

Exact implementation PRs must preserve regression coverage for these classes and pass applicable CI on one fixed head SHA with zero unresolved review threads.

## Rollback and recovery

Rollback restores the previous-known-good ADR-009 policy plus manifest implementation/tests as one tuple. Preserve rejected candidate evidence rather than mutating it into a passing form.

Recovery must replay a fixed source window, regenerate the manifest deterministically, confirm the deliberately invalid semantic-relabel candidate is still rejected, verify previous-valid data remains unchanged, and rerun grid/cadence/window/digest/schema/sensitive-metadata tests before the manifest control is considered healthy.

This recovery exercise is control verification only; it does not authorize dataset promotion or production use.

## Residual risk

A deterministic local manifest cannot by itself prove exchange authenticity, network transport integrity, publisher identity, trusted execution, independent control-plane protection, or cross-exchange semantic equivalence. Repository-local policy and validator changes can still self-authorize unless independently protected; Issue #106 remains relevant.

## Obsolescence triggers

Re-review when supported interval semantics, exchange endpoint/category contracts, canonical candle schema, mapping-policy identity, manifest schema, hash algorithm, downstream authority boundary, or a new relabel/substitution bypass class changes.

## Merge gate

This addendum may merge only when its exact head is stable, applicable CI is green, the PR is mergeable, unresolved review threads are zero, and it does not weaken ADR-009 or expand authority beyond research/public-data provenance validation.
