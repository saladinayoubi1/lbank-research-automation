from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

import nexus_multitimeframe_search_exhaustion as exhaustion


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "experiments" / "nexus_multitimeframe_strategy_discovery_v1.json"
DATASET_SEMANTIC_SHA = "2" * 64
SOURCE_SHA = "a" * 40


def _neighborhood(tmp_path: Path, *, source_sha: str = SOURCE_SHA) -> dict:
    implementation = tmp_path / "engine.py"
    implementation.write_text("ENGINE = 1\n", encoding="utf-8")
    return exhaustion.build_neighborhood(
        MANIFEST,
        source_sha=source_sha,
        dataset_semantic_sha256=DATASET_SEMANTIC_SHA,
        root=tmp_path,
        implementation_files=("engine.py",),
    )


def _evidence(neighborhood: dict) -> tuple[dict, dict, dict]:
    base = {
        "source_sha": SOURCE_SHA,
        "discovery_digest": "b" * 64,
        "dataset_archive_sha256": neighborhood["dataset_archive_sha256"],
        "research_proposal_count": 0,
        "research_only": True,
        "paper_only": True,
        "live_trading_authority": False,
        "automatic_strategy_promotion": False,
    }
    plan = {
        "source_discovery_sha": SOURCE_SHA,
        "source_discovery_digest": base["discovery_digest"],
        "plan_digest": "c" * 64,
        "training_basis_digest": "d" * 64,
        "should_refine": True,
        "selection_basis": "training_only",
        "locked_holdout_used_for_refinement": False,
        "research_only": True,
        "paper_only": True,
        "live_trading_authority": False,
        "automatic_strategy_promotion": False,
    }
    refined = {
        "source_sha": SOURCE_SHA,
        "discovery_digest": "e" * 64,
        "dataset_archive_sha256": neighborhood["dataset_archive_sha256"],
        "research_proposal_count": 0,
        "research_only": True,
        "paper_only": True,
        "live_trading_authority": False,
        "automatic_strategy_promotion": False,
    }
    return base, plan, refined


def test_neighborhood_fingerprint_changes_on_implementation_change(tmp_path: Path) -> None:
    implementation = tmp_path / "engine.py"
    implementation.write_text("ENGINE = 1\n", encoding="utf-8")
    first = exhaustion.build_neighborhood(
        MANIFEST,
        source_sha=SOURCE_SHA,
        dataset_semantic_sha256=DATASET_SEMANTIC_SHA,
        root=tmp_path,
        implementation_files=("engine.py",),
    )
    implementation.write_text("ENGINE = 2\n", encoding="utf-8")
    second = exhaustion.build_neighborhood(
        MANIFEST,
        source_sha=SOURCE_SHA,
        dataset_semantic_sha256=DATASET_SEMANTIC_SHA,
        root=tmp_path,
        implementation_files=("engine.py",),
    )
    assert first["neighborhood_fingerprint"] != second["neighborhood_fingerprint"]


def test_neighborhood_fingerprint_changes_on_dataset_change(tmp_path: Path) -> None:
    first = _neighborhood(tmp_path)
    second = exhaustion.build_neighborhood(
        MANIFEST,
        source_sha=SOURCE_SHA,
        dataset_semantic_sha256="3" * 64,
        root=tmp_path,
        implementation_files=("engine.py",),
    )
    assert first["neighborhood_fingerprint"] != second["neighborhood_fingerprint"]


def test_neighborhood_fingerprint_changes_on_source_sha_change(tmp_path: Path) -> None:
    first = _neighborhood(tmp_path, source_sha=SOURCE_SHA)
    second = _neighborhood(tmp_path, source_sha="f" * 40)
    assert first["source_sha"] == SOURCE_SHA
    assert second["source_sha"] == "f" * 40
    assert first["neighborhood_fingerprint"] != second["neighborhood_fingerprint"]


def test_source_sha_can_be_bound_from_trigger_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("TRIGGER_SOURCE_SHA", "b" * 40)
    monkeypatch.setenv("GITHUB_SHA", "c" * 40)
    neighborhood = exhaustion.build_neighborhood(
        MANIFEST,
        dataset_semantic_sha256=DATASET_SEMANTIC_SHA,
        root=tmp_path,
        implementation_files=("engine.py",),
    )
    assert neighborhood["source_sha"] == "b" * 40


def test_zero_base_and_training_refinement_create_reusable_certificate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    neighborhood = _neighborhood(tmp_path)
    base, plan, refined = _evidence(neighborhood)
    monkeypatch.setattr(exhaustion.discovery, "verify_discovery", lambda value: {"decision": "pass"})
    certificate = exhaustion.build_certificate(neighborhood, base, plan, refined)
    exhaustion.verify_certificate(certificate)
    assert certificate["exhausted"] is True
    assert certificate["source_sha"] == SOURCE_SHA
    assert certificate["selection_basis"] == "training_only"
    assert certificate["locked_holdout_used_for_refinement"] is False
    assert certificate["live_trading_authority"] is False
    assert exhaustion.certificate_is_reusable(neighborhood, certificate) is True


def test_certificate_reuse_requires_exact_neighborhood(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    neighborhood = _neighborhood(tmp_path)
    base, plan, refined = _evidence(neighborhood)
    monkeypatch.setattr(exhaustion.discovery, "verify_discovery", lambda value: {"decision": "pass"})
    certificate = exhaustion.build_certificate(neighborhood, base, plan, refined)
    changed = deepcopy(neighborhood)
    changed["dataset_semantic_sha256"] = "4" * 64
    core = dict(changed)
    core.pop("neighborhood_fingerprint")
    changed["neighborhood_fingerprint"] = exhaustion._digest(core)
    assert exhaustion.certificate_is_reusable(changed, certificate) is False


def test_certificate_reuse_rejects_different_source_sha(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    neighborhood = _neighborhood(tmp_path)
    base, plan, refined = _evidence(neighborhood)
    monkeypatch.setattr(exhaustion.discovery, "verify_discovery", lambda value: {"decision": "pass"})
    certificate = exhaustion.build_certificate(neighborhood, base, plan, refined)
    changed = _neighborhood(tmp_path, source_sha="f" * 40)
    assert exhaustion.certificate_is_reusable(changed, certificate) is False


def test_certificate_fails_closed_on_base_source_sha_mismatch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    neighborhood = _neighborhood(tmp_path, source_sha="f" * 40)
    base, plan, refined = _evidence(neighborhood)
    monkeypatch.setattr(exhaustion.discovery, "verify_discovery", lambda value: {"decision": "pass"})
    with pytest.raises(exhaustion.MultiTimeframeExhaustionError, match="base source SHA mismatch"):
        exhaustion.build_certificate(neighborhood, base, plan, refined)


def test_certificate_fails_closed_if_locked_holdout_influenced_refinement(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    neighborhood = _neighborhood(tmp_path)
    base, plan, refined = _evidence(neighborhood)
    plan["locked_holdout_used_for_refinement"] = True
    monkeypatch.setattr(exhaustion.discovery, "verify_discovery", lambda value: {"decision": "pass"})
    with pytest.raises(exhaustion.MultiTimeframeExhaustionError, match="locked holdout"):
        exhaustion.build_certificate(neighborhood, base, plan, refined)


def test_certificate_fails_closed_if_any_search_produces_a_proposal(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    neighborhood = _neighborhood(tmp_path)
    base, plan, refined = _evidence(neighborhood)
    refined["research_proposal_count"] = 1
    monkeypatch.setattr(exhaustion.discovery, "verify_discovery", lambda value: {"decision": "pass"})
    with pytest.raises(exhaustion.MultiTimeframeExhaustionError, match="refined search is not exhausted"):
        exhaustion.build_certificate(neighborhood, base, plan, refined)


def test_certificate_fails_closed_on_live_authority(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    neighborhood = _neighborhood(tmp_path)
    base, plan, refined = _evidence(neighborhood)
    refined["live_trading_authority"] = True
    monkeypatch.setattr(exhaustion.discovery, "verify_discovery", lambda value: {"decision": "pass"})
    with pytest.raises(exhaustion.MultiTimeframeExhaustionError, match="Live authority"):
        exhaustion.build_certificate(neighborhood, base, plan, refined)
