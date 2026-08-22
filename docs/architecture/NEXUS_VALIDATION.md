# NEXUS architecture validation

The versioned NEXUS contract registry is validated fail-closed before repository tests run.

The accepted v1.0.0 baseline is scoped to research and paper trading. A candidate cannot silently downgrade it to `proposed` or widen its authority.

## Local validation

From the repository root, install the locked development dependencies and run:

```bash
python -m pip install -r requirements-dev.lock
python nexus_architecture_validator.py docs/architecture/module-contract-registry.yaml
python -m pytest -q tests/test_nexus_architecture_validator.py
```

A non-zero exit from the validator is a delivery blocker. Do not bypass, skip, or weaken the validator to obtain a green build.

## CI gate

`.github/workflows/tests.yml` runs the same validator on Ubuntu, Windows, and macOS before the full pytest suite. The workflow retains read-only repository permissions.

## Recovery

If a candidate contract or validator change fails, restore the previous-valid registry and validator revision, rerun the local commands above, and require the complete CI matrix to pass on the fixed head SHA before merge.

## Safety boundary

This gate covers architecture-contract validation only. It does not authorize live trading, credentials, production deployment, billing, withdrawals, or real orders. Deterministic risk controls retain final authority and AI/agent output remains advisory.

## Residual risk

This gate validates the declared registry and its safety invariants. Python import-graph enforcement, direct runtime mutation-path analysis, and persisted-schema migration verification require separate controls and must not be inferred from a green result here.
