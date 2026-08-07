from __future__ import annotations

from datetime import datetime, timezone
from typing import Mapping

STEP_ENV = {
    "install": "INSTALL_OUTCOME",
    "compile": "COMPILE_OUTCOME",
    "tests": "TEST_OUTCOME",
}
IDENTITY_ENV = {
    "repository": "GITHUB_REPOSITORY",
    "sha": "GITHUB_SHA",
    "run_id": "GITHUB_RUN_ID",
    "run_attempt": "GITHUB_RUN_ATTEMPT",
    "event_name": "GITHUB_EVENT_NAME",
}


def build_status(env: Mapping[str, str], *, generated_at: str | None = None) -> dict[str, object]:
    outcomes = {name: env.get(key, "missing") for name, key in STEP_ENV.items()}
    identity = {name: env.get(key, "") for name, key in IDENTITY_ENV.items()}

    invalid_reasons = [
        f"{name}:{outcome}" for name, outcome in outcomes.items() if outcome != "success"
    ]
    invalid_reasons.extend(
        f"identity:{name}:missing" for name, value in identity.items() if not value
    )

    checkpoint_valid = not invalid_reasons
    timestamp = generated_at or datetime.now(timezone.utc).isoformat()

    return {
        "schema_version": 1,
        "mode": "github-actions-cloud-fallback",
        "generated_at": timestamp,
        **identity,
        "checkpoint_valid": checkpoint_valid,
        "step_outcomes": outcomes,
        "invalid_reasons": invalid_reasons,
        "note": "Cloud-side health/test checkpoint. Consumers must require checkpoint_valid=true.",
    }
