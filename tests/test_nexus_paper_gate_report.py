from __future__ import annotations

from copy import deepcopy

import pytest

import nexus_paper_gate_report as report


SOURCE_SHA = "a" * 40
RUN_ID = 123456
RUN_URL = f"https://github.com/example/repo/actions/runs/{RUN_ID}"
ARTIFACT_DIGEST = "sha256:" + "b" * 64


def state_with_bars(count: int, *, status: str = "COLLECTING") -> dict[str, object]:
    events: list[dict[str, object]] = []
    previous = "0" * 64
    for sequence in range(1, count + 1):
        hour = ((sequence - 1) * 4) % 24
        day = 26 + ((sequence - 1) * 4) // 24
        execution = f"2026-08-{day:02d}T{hour:02d}:00:00Z"
        core: dict[str, object] = {
            "schema_version": report.EVENT_SCHEMA,
            "sequence": sequence,
            "execution_utc": execution,
            "signal_close_utc": execution,
            "target_weights": [0.0, 0.0],
            "target_changed": False,
            "market_evidence_digest": "c" * 64,
            "source_sha": SOURCE_SHA,
            "previous_event_digest": previous,
            "paper_only": True,
            "live_trading_enabled": False,
        }
        event_digest = report._digest(core)  # noqa: SLF001
        events.append({**core, "event_digest": event_digest})
        previous = event_digest
    decision = report.STATUS_DECISIONS[status]
    core_state: dict[str, object] = {
        "schema_version": report.STATE_SCHEMA,
        "forward_id": report.FORWARD_ID,
        "strategy_id": report.STRATEGY_ID,
        "strategy_manifest_sha256": "d" * 64,
        "engine_sha256": "e" * 64,
        "start_not_before_utc": "2026-08-26T00:00:00Z",
        "last_execution_utc": events[-1]["execution_utc"] if events else None,
        "last_run_id": RUN_ID,
        "latest_source_sha": SOURCE_SHA,
        "completed_bar_count": count,
        "events": events,
        "profiles": {"conservative": {}, "stress": {}},
        "status": status,
        "decision": decision,
        "paper_only": True,
        "live_trading_enabled": False,
        "private_credentials_used": False,
        "automatic_live_promotion": False,
    }
    return {**core_state, "state_digest": report._digest(core_state)}  # noqa: SLF001


def render(state: dict[str, object]):
    return report.build_report(
        state,
        expected_source_sha=SOURCE_SHA,
        expected_run_id=RUN_ID,
        run_url=RUN_URL,
        artifact_id=987,
        artifact_digest=ARTIFACT_DIGEST,
    )


def test_daily_six_bar_checkpoint_is_publishable_and_paper_only() -> None:
    metadata, markdown = render(state_with_bars(6))

    assert metadata["publish"] is True
    assert metadata["completed_bar_count"] == 6
    assert metadata["live_trading_enabled"] is False
    assert "6 / 180" in markdown
    assert "automatic Live promotion: `false`" in markdown


def test_non_milestone_collecting_state_is_not_publishable() -> None:
    metadata, _ = render(state_with_bars(5))

    assert metadata["publish"] is False


@pytest.mark.parametrize("status", ["COMPLETE_REVIEW_REQUIRED", "QUARANTINED"])
def test_terminal_state_is_always_publishable_without_promotion(status: str) -> None:
    metadata, markdown = render(state_with_bars(5, status=status))

    assert metadata["publish"] is True
    assert metadata["automatic_live_promotion"] is False
    assert "No exchange order" in markdown


def test_digest_tampering_and_authority_widening_fail_closed() -> None:
    state = state_with_bars(1)
    state["live_trading_enabled"] = True

    with pytest.raises(report.PaperGateReportError, match="digest mismatch"):
        render(state)

    state = state_with_bars(1)
    unsigned = dict(state)
    unsigned.pop("state_digest")
    unsigned["live_trading_enabled"] = True
    state = {**unsigned, "state_digest": report._digest(unsigned)}  # noqa: SLF001
    with pytest.raises(report.PaperGateReportError, match="contract rejected"):
        render(state)


def test_wrong_run_source_or_url_binding_is_rejected() -> None:
    state = state_with_bars(1)

    with pytest.raises(report.PaperGateReportError, match="contract rejected"):
        report.build_report(
            state,
            expected_source_sha="f" * 40,
            expected_run_id=RUN_ID,
            run_url=RUN_URL,
            artifact_id=987,
            artifact_digest=ARTIFACT_DIGEST,
        )
    with pytest.raises(report.PaperGateReportError, match="run URL"):
        report.build_report(
            state,
            expected_source_sha=SOURCE_SHA,
            expected_run_id=RUN_ID,
            run_url="https://example.invalid/actions/runs/123456",
            artifact_id=987,
            artifact_digest=ARTIFACT_DIGEST,
        )


def test_milestone_marker_is_stable_across_no_new_bar_rerun() -> None:
    first = state_with_bars(6)
    first_metadata, _ = render(first)

    rerun = deepcopy(first)
    rerun["last_run_id"] = RUN_ID + 1
    unsigned = dict(rerun)
    unsigned.pop("state_digest")
    rerun["state_digest"] = report._digest(unsigned)  # noqa: SLF001
    second_metadata, _ = report.build_report(
        rerun,
        expected_source_sha=SOURCE_SHA,
        expected_run_id=RUN_ID + 1,
        run_url=f"https://github.com/example/repo/actions/runs/{RUN_ID + 1}",
        artifact_id=988,
        artifact_digest=ARTIFACT_DIGEST,
    )

    assert first_metadata["marker"] == second_metadata["marker"]


def test_event_chain_substitution_fails_closed() -> None:
    state = state_with_bars(2)
    state["events"][1]["previous_event_digest"] = "0" * 64  # type: ignore[index]
    unsigned = dict(state)
    unsigned.pop("state_digest")
    state["state_digest"] = report._digest(unsigned)  # noqa: SLF001

    with pytest.raises(report.PaperGateReportError, match="event chain"):
        render(state)
