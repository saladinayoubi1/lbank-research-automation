from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

import bybit_prospective_paper_forward_v1 as forward
import nexus_paper_terminal_rebind as rebind

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "experiments" / "bybit_prospective_paper_forward_v1.json"
ENGINE_SHA = forward._file_sha(ROOT / "bybit_prospective_paper_forward_v1.py")  # noqa: SLF001
SOURCE_A = "a" * 40
SOURCE_B = "b" * 40


def _terminal_state(status: str = "COMPLETE_REVIEW_REQUIRED") -> tuple[dict, dict]:
    config, _ = forward.load_contract(MANIFEST)
    state = forward.new_state(
        config,
        engine_sha256=ENGINE_SHA,
        source_sha=SOURCE_A,
        run_id=10,
    )
    state["status"] = status
    state["decision"] = rebind.TERMINAL_DECISIONS[status]
    unsigned = dict(state)
    unsigned.pop("state_digest")
    state["state_digest"] = forward._digest(unsigned)  # noqa: SLF001
    forward.verify_state(state, config, ENGINE_SHA)
    return config, state


@pytest.mark.parametrize("status", ["COMPLETE_REVIEW_REQUIRED", "QUARANTINED"])
def test_terminal_rebind_changes_only_provenance(status: str) -> None:
    config, state = _terminal_state(status)
    before = deepcopy(state)

    updated = rebind.rebind_terminal_state(
        state,
        config,
        source_sha=SOURCE_B,
        run_id=11,
        engine_sha256=ENGINE_SHA,
    )

    assert updated["last_run_id"] == 11
    assert updated["latest_source_sha"] == SOURCE_B
    assert updated["state_digest"] != before["state_digest"]
    for key in before:
        if key not in rebind.PROVENANCE_FIELDS:
            assert updated[key] == before[key]
    assert updated["status"] == status
    assert updated["paper_only"] is True
    assert updated["live_trading_enabled"] is False
    assert updated["private_credentials_used"] is False
    assert updated["automatic_live_promotion"] is False
    forward.verify_state(updated, config, ENGINE_SHA)


def test_collecting_state_cannot_use_terminal_rebind() -> None:
    config, _ = forward.load_contract(MANIFEST)
    state = forward.new_state(
        config,
        engine_sha256=ENGINE_SHA,
        source_sha=SOURCE_A,
        run_id=10,
    )
    with pytest.raises(rebind.PaperTerminalRebindError, match="not a valid terminal"):
        rebind.rebind_terminal_state(
            state,
            config,
            source_sha=SOURCE_B,
            run_id=11,
            engine_sha256=ENGINE_SHA,
        )


def test_terminal_rebind_rejects_bad_decision_or_nonadvancing_run() -> None:
    config, state = _terminal_state()
    bad = deepcopy(state)
    bad["decision"] = "collect_prospective_paper_evidence"
    unsigned = dict(bad)
    unsigned.pop("state_digest")
    bad["state_digest"] = forward._digest(unsigned)  # noqa: SLF001
    with pytest.raises(rebind.PaperTerminalRebindError, match="not a valid terminal"):
        rebind.rebind_terminal_state(
            bad,
            config,
            source_sha=SOURCE_B,
            run_id=11,
            engine_sha256=ENGINE_SHA,
        )
    with pytest.raises(rebind.PaperTerminalRebindError, match="did not advance"):
        rebind.rebind_terminal_state(
            state,
            config,
            source_sha=SOURCE_B,
            run_id=10,
            engine_sha256=ENGINE_SHA,
        )


def test_workflow_freezes_terminal_state_before_market_collection() -> None:
    workflow = (
        ROOT / ".github" / "workflows" / "bybit_prospective_paper_forward_v1.yml"
    ).read_text(encoding="utf-8")
    assert "Detect terminal Paper evidence" in workflow
    assert "steps.terminal.outputs.terminal != 'true'" in workflow
    assert "steps.terminal.outputs.terminal == 'true'" in workflow
    assert "nexus_paper_terminal_rebind.py" in workflow
    assert "terminal_evidence_frozen" in workflow
    assert "live_trading_enabled\"] is False" in workflow
