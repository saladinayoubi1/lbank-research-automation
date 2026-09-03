from __future__ import annotations

import json
from pathlib import Path

import pytest

import nexus_multipair_physical_discovery_acceptance as acceptance


SOURCE_SHA = "a" * 40


def _discovery(proposals: list[dict] | None = None) -> dict:
    proposals = [] if proposals is None else proposals
    cells = []
    for timeframe in acceptance.TIMEFRAMES:
        for family in acceptance.FAMILIES:
            cells.append(
                {
                    "timeframe": timeframe,
                    "family": family,
                    "selection_source": "training_only",
                    "locked_profiles": {"conservative": {"passes": True}, "stress": {"passes": True}},
                }
            )
    return {
        "source_sha": SOURCE_SHA,
        "symbols": list(acceptance.SYMBOLS),
        "timeframes": list(acceptance.TIMEFRAMES),
        "families": list(acceptance.FAMILIES),
        "hypothesis_count": 9,
        "cells": cells,
        "research_proposals": proposals,
        "research_proposal_count": len(proposals),
        "research_only": True,
        "paper_only": True,
        "live_trading_authority": False,
        "private_credentials_used": False,
        "automatic_strategy_promotion": False,
        "automatic_paper_forward_started": False,
        "discovery_digest": "b" * 64,
    }


def _requalification(*, proposal_count: int = 0, blocked: int = 0) -> dict:
    return {
        "proposal_count": proposal_count,
        "blocked_runtime_data_count": blocked,
        "qualified_for_review_count": 0,
        "rejected_count": proposal_count - blocked,
        "status": "NO_WORK" if proposal_count == 0 else "WAITING_FOR_RUNTIME_DATA" if blocked else "EVALUATED",
        "proposal_results": [],
        "runtime_data_is_fresh_not_snapshot_reuse": True,
        "candidate_creation_authority": False,
        "promotion_authority": False,
        "paper_execution_started": False,
        "live_trading_authority": False,
        "private_credentials_used": False,
        "automatic_strategy_promotion": False,
        "deterministic_risk_final_authority": True,
        "requalification_digest": "c" * 64,
    }


def _install_fakes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, discovery: dict, requalification: dict) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        acceptance,
        "load_discovery_manifest",
        lambda _path: {"dataset": {"dataset_root": "build/nexus_multipair_discovery_snapshot"}},
    )

    def collect_snapshot(**kwargs):
        root = Path(kwargs["output_root"])
        root.mkdir(parents=True, exist_ok=True)
        return {
            "source_sha": SOURCE_SHA,
            "cell_count": 12,
            "snapshot_digest": "d" * 64,
        }

    monkeypatch.setattr(acceptance, "collect_snapshot", collect_snapshot)
    monkeypatch.setattr(acceptance, "verify_snapshot", lambda *_args, **_kwargs: {"decision": "pass"})

    def run_discovery(_manifest_path, output_root, *, source_sha):
        assert source_sha == SOURCE_SHA
        root = Path(output_root)
        root.mkdir(parents=True, exist_ok=True)
        (root / "multipair_strategy_discovery.json").write_text(json.dumps(discovery), encoding="utf-8")
        (root / "research_proposals.json").write_text("{}", encoding="utf-8")
        return discovery

    monkeypatch.setattr(acceptance, "run_discovery", run_discovery)
    monkeypatch.setattr(
        acceptance,
        "verify_discovery",
        lambda _value: {"decision": "pass", "verification_digest": "e" * 64},
    )

    def run_requalification(_discovery_path, _queue_path, **kwargs):
        assert kwargs["source_sha"] == SOURCE_SHA
        assert kwargs["discovery_source_sha"] == SOURCE_SHA
        target = Path(kwargs["output"])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(requalification), encoding="utf-8")
        return requalification

    monkeypatch.setattr(acceptance, "run_requalification", run_requalification)
    monkeypatch.setattr(
        acceptance,
        "verify_requalification",
        lambda _value: {"decision": "pass", "verification_digest": "f" * 64},
    )


def _run(tmp_path: Path) -> dict:
    return acceptance.run_acceptance(
        manifest_path="experiments/fake.json",
        source_sha=SOURCE_SHA,
        run_id="12345",
        now_ms=1_800_000_000_000,
        state_root=tmp_path / "external-state",
        work_root=tmp_path / "work",
        output=tmp_path / "proof" / "evidence.json",
        runner_name="NEXUS-BYBIT-WSL",
        runner_os="Linux",
        runner_environment="self-hosted",
        execution_plane="nexus-bybit-network",
        history_limit=240,
    )


def test_zero_proposal_physical_path_is_valid_and_authority_remains_closed(monkeypatch, tmp_path):
    discovery = _discovery()
    requalification = _requalification()
    _install_fakes(monkeypatch, tmp_path, discovery=discovery, requalification=requalification)

    evidence = _run(tmp_path)

    assert evidence["decision"] == "pass"
    assert evidence["snapshot_cell_count"] == 12
    assert evidence["hypothesis_count"] == 9
    assert evidence["research_proposal_count"] == 0
    assert evidence["requalification_proposal_count"] == 0
    assert evidence["blocked_runtime_data_count"] == 0
    assert evidence["zero_proposals_valid"] is True
    assert evidence["training_selection_only"] is True
    assert evidence["locked_holdout_after_selection"] is True
    assert evidence["fresh_runtime_requalification"] is True
    assert evidence["candidate_state_created"] is False
    assert evidence["paper_execution_started"] is False
    assert evidence["automatic_strategy_promotion"] is False
    assert evidence["live_trading_authority"] is False
    assert evidence["private_credentials_used"] is False
    assert evidence["real_exchange_orders"] is False
    assert evidence["deterministic_risk_final_authority"] is True
    assert evidence["state_isolated_from_issue_984"] is True
    assert evidence["issue_984_state_artifact_touched"] is False
    assert evidence["persistent_runtime_database_on_github"] is False
    saved = json.loads((tmp_path / "proof" / "evidence.json").read_text(encoding="utf-8"))
    assert saved == evidence


def test_runtime_data_block_rejects_physical_acceptance(monkeypatch, tmp_path):
    proposal = {
        "proposal_state": "RESEARCH_PROPOSAL_ONLY",
        "requires_independent_runtime_requalification": True,
        "promotion_authority": False,
        "live_trading_authority": False,
    }
    discovery = _discovery([proposal])
    requalification = _requalification(proposal_count=1, blocked=1)
    _install_fakes(monkeypatch, tmp_path, discovery=discovery, requalification=requalification)

    with pytest.raises(acceptance.MultiPairPhysicalDiscoveryAcceptanceError, match="failed closed"):
        _run(tmp_path)


def test_wrong_execution_plane_rejects_before_research_work(tmp_path):
    with pytest.raises(acceptance.MultiPairPhysicalDiscoveryAcceptanceError, match="nexus-bybit-network"):
        acceptance.run_acceptance(
            manifest_path="unused.json",
            source_sha=SOURCE_SHA,
            run_id="12345",
            now_ms=1_800_000_000_000,
            state_root=tmp_path / "state",
            work_root=tmp_path / "work",
            output=tmp_path / "proof.json",
            runner_name="runner",
            runner_os="Linux",
            runner_environment="self-hosted",
            execution_plane="wrong-plane",
        )


def test_issue_984_named_state_root_rejects(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        acceptance,
        "load_discovery_manifest",
        lambda _path: {"dataset": {"dataset_root": "build/nexus_multipair_discovery_snapshot"}},
    )
    with pytest.raises(acceptance.MultiPairPhysicalDiscoveryAcceptanceError, match="Issue #984"):
        acceptance.run_acceptance(
            manifest_path="unused.json",
            source_sha=SOURCE_SHA,
            run_id="12345",
            now_ms=1_800_000_000_000,
            state_root=tmp_path / "issue-984-state",
            work_root=tmp_path / "work",
            output=tmp_path / "proof.json",
            runner_name="runner",
            runner_os="Linux",
            runner_environment="self-hosted",
            execution_plane="nexus-bybit-network",
        )
