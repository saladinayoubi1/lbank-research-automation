# NEXUS Project Memory validation

Project Memory validation is deny-by-default. The validator reads only the four canonical paths under `docs/project_memory/` and rejects alternate-path substitution, malformed state, stale exact-SHA evidence, safety-boundary conflicts, and Drive-presence-only recovery authority.

## Exact-SHA freshness semantics

`STATE.json.current_evidence.observed_main_sha` is an **observation/source SHA**, not the SHA of the commit that contains the updated `STATE.json`. A Git commit SHA hashes the tree that contains `STATE.json`; requiring the file to embed that same containing commit SHA would be self-referential and cannot be satisfied deterministically.

Therefore a caller that has independently observed the authoritative repository SHA must pass it explicitly:

```bash
python project_memory_validator.py --expected-observed-main <40-hex-observed-sha>
```

The validator then requires `STATE.json` to record exactly that externally supplied evidence SHA. If the repository advances after the snapshot, rerunning with the newer observed SHA fails closed as stale.

## Claim boundary

A successful validation proves canonical-path presence, required state structure, exact externally supplied observation binding, safety-boundary consistency, and the non-authoritative Drive-backup contract checked by this validator. It does not prove that an observation SHA is current unless the caller obtained it from authoritative repository evidence immediately before validation. It does not authorize credentials, billing, signing, deployment, production recovery, live trading, or any irreversible action.

## Recovery

If validation fails, do not copy an alternate file into place or weaken the gate. Re-observe repository state, regenerate the bounded memory snapshot from that evidence, preserve append/supersede history, and rerun validation. If main advances before merge, invalidate the snapshot and replay from the new exact repository evidence.
