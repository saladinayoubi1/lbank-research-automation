# NEXUS Regime Runtime Drift v1

## Contract

This bridge connects three independently bounded evidence chains:

```text
verified Supervisor ledger
  + verified Paper performance projection
  + independently replayed regime Runtime evidence
  -> next-cycle drift controls
  -> append-only drift evidence
```

The bridge does not rewrite the current runtime. It can emit only these
recommendations for the next selector cycle:

- `KEEP` for healthy evidence;
- `WATCH_HAIRCUT_NEXT_CYCLE` for `WATCH`;
- `REMOVE_FROM_NEXT_SELECTION` for `DEGRADED` or `QUARANTINED`;
- `PRESERVE_CURRENT_POLICY_BOUND` while samples are insufficient.

## Fail-closed bindings

- Supervisor evidence is independently re-verified.
- Runtime evidence replays Selector, Deterministic Risk, and the full Paper pipeline.
- Performance evidence must retain its canonical digest and bind the same Supervisor verifier.
- Runtime and Supervisor must use the same exact source SHA.
- Every selected family must have one unambiguous performance monitor row.
- Output is Paper-only, append-only, and digest-bound.

The bridge has no promotion, execution, exchange, credential, signing, deployment,
Live/L4, or current-runtime mutation authority.

## Verification

```bash
python -m pytest -q tests/test_nexus_regime_runtime_drift.py
```

Tests cover healthy, watch, degraded, quarantined, insufficient-sample, missing-family,
cross-SHA, tampered Runtime, tampered Performance, append-only, and idempotent paths.
