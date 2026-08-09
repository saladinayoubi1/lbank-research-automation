# ADR-009A: Provenance semantic binding

- Version: 1.0.0
- Status: Proposed
- Parent: `ADR-009-market-data-source-hierarchy.md`
- Scope: public market-data provenance binding for cross-source reconciliation
- Authority boundary: research and paper-trading data only; no credentials, live orders, signing, billing, production deployment, or release authority

## Context

Issue #197 records a known post-merge gap: a digest can be internally consistent while omitting or misbinding timeframe, market category, endpoint interval, or candle-finality semantics. Therefore SHA-256 provenance alone is not sufficient evidence of semantic source equivalence.

## Decision

The repository has one canonical machine-readable semantic registry: `docs/architecture/market-data-source-registry.yaml`.

A provenance binding is eligible only when the candidate timeframe, manifest timeframe, Bybit category+interval, Binance market+interval, timestamp grid, and candle finality all match the same registry entry and mapping-policy version. Unknown or divergent values fail closed.

Canonical supported mappings for the current policy are:

| Candidate timeframe | Manifest | Bybit category | Bybit interval | Binance market | Binance interval | Finality |
|---|---|---|---|---|---|---|
| `minute15` | `15m` | `spot` | `15` | `spot` | `15m` | `closed_only` |
| `hour1` | `1h` | `spot` | `60` | `spot` | `1h` | `closed_only` |
| `hour4` | `4h` | `spot` | `240` | `spot` | `4h` | `closed_only` |

The implementation may cache these values only if deterministic validation proves exact equality with the versioned registry. Caller-supplied labels or endpoint contracts are never authoritative.

## Deny-by-default rules

Reject and quarantine when any of the following occurs:

- timeframe relabeling or relabel+rehash;
- Bybit category/interval substitution;
- Binance market/interval substitution;
- spot/perpetual alias collision;
- unknown registry or mapping-policy version;
- off-grid timestamp for the canonical timeframe;
- open/incomplete candle or finality ambiguity;
- raw/unvalidated downstream bypass;
- policy/validator/test tuple divergence.

Rejected candidates have zero eligibility for Backtest, Strategy Lab, Decision Engine, and Paper Trading.

## Threat model and bypass coverage

The control must cover caller-controlled labels, endpoint substitution, alternate registry/version substitution, semantic aliasing, open-vs-closed ambiguity, timestamp-grid mismatch, raw-file bypass, and simultaneous weakening of policy+validator+tests. Digest validity does not override semantic mismatch.

## Rollback and recovery

Rollback the ADR + registry + validator/binder + tests as one fixed tuple to the previous-known-good fail-closed state. Preserve rejected artifacts for audit.

Recovery must replay one fixed source window and prove deterministic binding for the canonical tuple, deterministic rejection of semantic substitutions, timestamp-grid correctness, closed-candle finality, source/market identity, manifest/provenance integrity, and downstream ineligibility for rejected candidates before authority is restored.

## Alternatives rejected

- Trust caller-supplied timeframe/endpoint labels: rejected because relabel+rehash remains possible.
- Treat a matching digest as semantic equivalence: rejected because hashes bind only included claims/bytes.
- Maintain a second implementation-local semantic authority: rejected because policy drift can self-authorize invalid mappings.

## Residual risks

Repository-local policy, validator, workflow, and tests can still be weakened together; #106 remains the independent-control-plane blocker. Cross-venue OHLCV agreement is corroboration, not proof of universal market truth. Provider API semantic changes can obsolete current mappings.

## Obsolescence triggers

Re-review on Bybit/Binance category, interval, market, timestamp-grid, finality, symbol, endpoint, pagination/order, or schema changes; canonical registry changes; new providers; downstream authority changes; a new bypass class; or an applicable finalized standards revision.

## Merge gate

This ADR is policy evidence only. It does not by itself close #197. Completion requires the canonical registry, implementation, positive/negative/bypass tests, rollback/recovery replay, exact-final-head green CI, mergeable state, and zero unresolved review threads to align on one fixed SHA.

Refs #197 #131 #106
