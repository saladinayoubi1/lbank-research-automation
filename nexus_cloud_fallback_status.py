from __future__ import annotations

from datetime import datetime, timezone
from typing import Mapping

SCHEMA_VERSION = 2
MODE = "github-actions-cloud-fallback"
REQUIRED_STEPS = ("install", "compile", "tests")
STEP_ENV = {
    "install": "INSTALL_OUTCOME",
    "compile": "COMPILE_OUTCOME",
    "tests": "TEST_OUTCOME",
}
IDENTITY_ENV = {
    "repository": "GITHUB_REPOSITORY",
    "sha": "CHECKPOINT_SHA",
    "runner_sha": "GITHUB_SHA",
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
        "schema_version": SCHEMA_VERSION,
        "mode": MODE,
        "generated_at": timestamp,
        **identity,
        "checkpoint_valid": checkpoint_valid,
        "step_outcomes": outcomes,
        "invalid_reasons": invalid_reasons,
        "note": (
            "Cloud-side health/test checkpoint. 'sha' is the exact source head under test; "
            "'runner_sha' is the GitHub Actions execution SHA and may be a pull-request merge ref. "
            "Consumers must require checkpoint_valid=true and match sha to the expected source revision."
        ),
    }


def validate_status(
    status: Mapping[str, object],
    *,
    expected_repository: str,
    expected_sha: str,
    expected_run_id: str | None = None,
    max_age_seconds: int | None = None,
    now: datetime | None = None,
) -> tuple[bool, tuple[str, ...]]:
    """Fail-closed validation for consumers of persisted fallback checkpoints."""
    reasons: list[str] = []

    if status.get("schema_version") != SCHEMA_VERSION:
        reasons.append("schema:unsupported")
    if status.get("mode") != MODE:
        reasons.append("mode:unsupported")
    if status.get("checkpoint_valid") is not True:
        reasons.append("checkpoint:invalid")
    if status.get("repository") != expected_repository:
        reasons.append("identity:repository:mismatch")
    if status.get("sha") != expected_sha:
        reasons.append("identity:sha:mismatch")
    if expected_run_id is not None and status.get("run_id") != expected_run_id:
        reasons.append("identity:run_id:mismatch")

    parsed: datetime | None = None
    generated_at = status.get("generated_at")
    if not isinstance(generated_at, str) or not generated_at:
        reasons.append("generated_at:missing")
    else:
        try:
            parsed = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                reasons.append("generated_at:timezone_missing")
                parsed = None
        except ValueError:
            reasons.append("generated_at:invalid")

    if max_age_seconds is not None:
        if isinstance(max_age_seconds, bool) or not isinstance(max_age_seconds, int) or max_age_seconds <= 0:
            reasons.append("freshness:policy_invalid")
        elif parsed is not None:
            reference = now or datetime.now(timezone.utc)
            if reference.tzinfo is None:
                reasons.append("freshness:clock_timezone_missing")
            else:
                age_seconds = (reference.astimezone(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds()
                if age_seconds < 0:
                    reasons.append("freshness:future")
                elif age_seconds > max_age_seconds:
                    reasons.append("freshness:stale")

    outcomes = status.get("step_outcomes")
    if not isinstance(outcomes, Mapping):
        reasons.append("steps:missing")
    else:
        for step in REQUIRED_STEPS:
            if outcomes.get(step) != "success":
                reasons.append(f"steps:{step}:not_success")

    invalid_reasons = status.get("invalid_reasons")
    if not isinstance(invalid_reasons, list) or invalid_reasons:
        reasons.append("producer:invalid_reasons_present")

    return (not reasons, tuple(reasons))
