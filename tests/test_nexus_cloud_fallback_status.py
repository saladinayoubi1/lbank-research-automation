from __future__ import annotations

from datetime import datetime, timezone

import pytest

from nexus_cloud_fallback_status import build_status, validate_status


def valid_env() -> dict[str, str]:
    return {
        "INSTALL_OUTCOME": "success",
        "COMPILE_OUTCOME": "success",
        "TEST_OUTCOME": "success",
        "GITHUB_REPOSITORY": "owner/repo",
        "CHECKPOINT_SHA": "a" * 40,
        "GITHUB_SHA": "b" * 40,
        "GITHUB_RUN_ID": "123",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_EVENT_NAME": "pull_request",
    }


def valid_status() -> dict[str, object]:
    return build_status(valid_env(), generated_at="2026-08-07T12:00:00+00:00")


def test_checkpoint_valid_only_when_all_steps_and_identity_are_present() -> None:
    status = valid_status()
    assert status["schema_version"] == 2
    assert status["checkpoint_valid"] is True
    assert status["sha"] == "a" * 40
    assert status["runner_sha"] == "b" * 40
    assert status["invalid_reasons"] == []
    assert status["step_outcomes"] == {"install": "success", "compile": "success", "tests": "success"}


@pytest.mark.parametrize("outcome", ["failure", "cancelled", "skipped", "neutral", "missing", ""])
def test_non_success_step_outcomes_fail_closed(outcome: str) -> None:
    env = valid_env()
    env["TEST_OUTCOME"] = outcome
    status = build_status(env)
    assert status["checkpoint_valid"] is False
    assert f"tests:{outcome}" in status["invalid_reasons"]


@pytest.mark.parametrize(
    ("key", "reason"),
    [
        ("GITHUB_REPOSITORY", "identity:repository:missing"),
        ("CHECKPOINT_SHA", "identity:sha:missing"),
        ("GITHUB_SHA", "identity:runner_sha:missing"),
        ("GITHUB_RUN_ID", "identity:run_id:missing"),
        ("GITHUB_RUN_ATTEMPT", "identity:run_attempt:missing"),
        ("GITHUB_EVENT_NAME", "identity:event_name:missing"),
    ],
)
def test_missing_checkpoint_identity_fails_closed(key: str, reason: str) -> None:
    env = valid_env()
    env.pop(key)
    status = build_status(env)
    assert status["checkpoint_valid"] is False
    assert reason in status["invalid_reasons"]


def test_missing_outcome_is_not_silently_promoted() -> None:
    env = valid_env()
    env.pop("COMPILE_OUTCOME")
    status = build_status(env)
    assert status["checkpoint_valid"] is False
    assert "compile:missing" in status["invalid_reasons"]


def test_pull_request_merge_runner_sha_does_not_replace_source_head_sha() -> None:
    env = valid_env()
    status = build_status(env)
    assert status["checkpoint_valid"] is True
    assert status["sha"] != status["runner_sha"]
    assert status["sha"] == env["CHECKPOINT_SHA"]


def test_consumer_accepts_exact_bound_checkpoint() -> None:
    ok, reasons = validate_status(
        valid_status(), expected_repository="owner/repo", expected_sha="a" * 40, expected_run_id="123"
    )
    assert ok is True
    assert reasons == ()


@pytest.mark.parametrize("schema", [None, 1, 3, "2"])
def test_consumer_rejects_unknown_or_legacy_schema(schema: object) -> None:
    status = valid_status()
    status["schema_version"] = schema
    ok, reasons = validate_status(status, expected_repository="owner/repo", expected_sha="a" * 40)
    assert ok is False
    assert "schema:unsupported" in reasons


@pytest.mark.parametrize(
    ("field", "value", "expected_reason"),
    [
        ("repository", "attacker/repo", "identity:repository:mismatch"),
        ("sha", "c" * 40, "identity:sha:mismatch"),
        ("run_id", "999", "identity:run_id:mismatch"),
    ],
)
def test_consumer_rejects_replayed_or_mismatched_identity(field: str, value: str, expected_reason: str) -> None:
    status = valid_status()
    status[field] = value
    ok, reasons = validate_status(
        status, expected_repository="owner/repo", expected_sha="a" * 40, expected_run_id="123"
    )
    assert ok is False
    assert expected_reason in reasons


@pytest.mark.parametrize("checkpoint_valid", [False, None, 1, "true"])
def test_consumer_requires_literal_true_checkpoint_valid(checkpoint_valid: object) -> None:
    status = valid_status()
    status["checkpoint_valid"] = checkpoint_valid
    ok, reasons = validate_status(status, expected_repository="owner/repo", expected_sha="a" * 40)
    assert ok is False
    assert "checkpoint:invalid" in reasons


def test_consumer_rechecks_step_outcomes_instead_of_trusting_summary_boolean() -> None:
    status = valid_status()
    status["step_outcomes"] = {"install": "success", "compile": "success", "tests": "skipped"}
    status["checkpoint_valid"] = True
    ok, reasons = validate_status(status, expected_repository="owner/repo", expected_sha="a" * 40)
    assert ok is False
    assert "steps:tests:not_success" in reasons


def test_consumer_quarantines_producer_with_embedded_invalid_reasons() -> None:
    status = valid_status()
    status["invalid_reasons"] = ["tests:failure"]
    status["checkpoint_valid"] = True
    ok, reasons = validate_status(status, expected_repository="owner/repo", expected_sha="a" * 40)
    assert ok is False
    assert "producer:invalid_reasons_present" in reasons


@pytest.mark.parametrize("generated_at", [None, "", "not-a-date", "2026-08-07T12:00:00"])
def test_consumer_rejects_missing_malformed_or_timezone_free_timestamp(generated_at: object) -> None:
    status = valid_status()
    status["generated_at"] = generated_at
    ok, reasons = validate_status(status, expected_repository="owner/repo", expected_sha="a" * 40)
    assert ok is False
    assert any(reason.startswith("generated_at:") for reason in reasons)


def test_consumer_rejects_stale_checkpoint() -> None:
    ok, reasons = validate_status(
        valid_status(),
        expected_repository="owner/repo",
        expected_sha="a" * 40,
        max_age_seconds=300,
        now=datetime(2026, 8, 7, 12, 5, 1, tzinfo=timezone.utc),
    )
    assert ok is False
    assert "freshness:stale" in reasons


def test_consumer_rejects_future_checkpoint() -> None:
    ok, reasons = validate_status(
        valid_status(),
        expected_repository="owner/repo",
        expected_sha="a" * 40,
        max_age_seconds=300,
        now=datetime(2026, 8, 7, 11, 59, 59, tzinfo=timezone.utc),
    )
    assert ok is False
    assert "freshness:future" in reasons


@pytest.mark.parametrize("max_age", [0, -1, True])
def test_consumer_rejects_invalid_freshness_policy(max_age: object) -> None:
    ok, reasons = validate_status(
        valid_status(),
        expected_repository="owner/repo",
        expected_sha="a" * 40,
        max_age_seconds=max_age,  # type: ignore[arg-type]
        now=datetime(2026, 8, 7, 12, 1, tzinfo=timezone.utc),
    )
    assert ok is False
    assert "freshness:policy_invalid" in reasons
