from __future__ import annotations

import pytest

from nexus_cloud_fallback_status import build_status


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


def test_checkpoint_valid_only_when_all_steps_and_identity_are_present() -> None:
    status = build_status(valid_env(), generated_at="2026-08-07T12:00:00+00:00")

    assert status["schema_version"] == 2
    assert status["checkpoint_valid"] is True
    assert status["sha"] == "a" * 40
    assert status["runner_sha"] == "b" * 40
    assert status["invalid_reasons"] == []
    assert status["step_outcomes"] == {
        "install": "success",
        "compile": "success",
        "tests": "success",
    }


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
