# NEXUS Project Memory validation

Project Memory validation is deny-by-default. The validator reads only the four canonical paths under `docs/project_memory/` and rejects alternate-path substitution, canonical-file symlinks, malformed state, missing authoritative freshness evidence, stale exact-SHA evidence, safety-boundary conflicts, and Drive-presence-only recovery authority.

## Exact-SHA freshness semantics

`STATE.json.current_evidence.observed_main_sha` is an **observation/source SHA**, not the SHA of the commit that contains the updated `STATE.json`. A Git commit SHA hashes the tree that contains `STATE.json`; requiring the file to embed that same containing commit SHA would be self-referential and cannot be satisfied deterministically.

Therefore a caller must independently observe the authoritative repository SHA and pass it explicitly:

```bash
python project_memory_validator.py --expected-observed-main <40-hex-observed-sha>
```

The argument is mandatory. A validation attempt without an authoritative SHA fails closed. The validator then requires `STATE.json` to record exactly that externally supplied evidence SHA. If the repository advances after the snapshot, rerunning with the newer observed SHA fails closed as stale.

Canonical Project Memory filenames must also be ordinary files, not symlinks. This prevents a canonical filename from being redirected to another same-directory or external target while preserving the expected visible path.

## Claim boundary

A successful validation proves canonical-path presence, no canonical-file symlink substitution, required state structure, exact externally supplied observation binding, safety-boundary consistency, and the non-authoritative Drive-backup contract checked by this validator. It does not prove that an observation SHA is current unless the caller obtained it from authoritative repository evidence immediately before validation. It also does not by itself eliminate all concurrent filesystem replacement/TOCTOU risks; authoritative CI wiring or a trusted immutable workspace remains required for that stronger claim. It does not authorize credentials, billing, signing, deployment, production recovery, live trading, or any irreversible action.

## Recovery

If validation fails, do not copy an alternate file into place or weaken the gate. Re-observe repository state, regenerate the bounded memory snapshot from that evidence, preserve append/supersede history, and rerun validation. If main advances before merge, invalidate the snapshot and replay from the new exact repository evidence.
