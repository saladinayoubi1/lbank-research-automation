from __future__ import annotations

from pathlib import Path


WORKFLOW = Path(".github/workflows/nexus_persistent_paper_trading_loop.yml")


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _paper_job() -> str:
    return _text().split("  paper-loop:", 1)[1].split("  persist-state:", 1)[0]


def test_scheduled_physical_runtime_uses_exact_v2_surface_and_legacy_migration_input() -> None:
    paper = _paper_job()
    assert "nexus_multipair_persistent_paper_trading_loop.py" in paper
    assert "--manifest config/nexus-demo-strategy-matrix-v2.json" in paper
    assert "--legacy-manifest config/nexus-demo-strategy-matrix-v1.json" in paper
    assert 'assert snapshot["matrix_id"] == "nexus-demo-btc-eth-sol-xrp-3tf-3strategy-v2"' in paper
    assert 'assert snapshot["expected_cell_count"] == 12' in paper
    assert 'assert snapshot["expected_lane_count"] == 36' in paper
    assert 'snapshot["matrix_migration_status"] in {"PERFORMED", "ALREADY_V2"}' in paper
    assert 'assert snapshot["new_symbol_inherited_cell_count"] == 0' in paper


def test_physical_verifier_requires_migration_evidence_and_issue_984_isolation() -> None:
    paper = _paper_job()
    assert "_verify_migration" in paper
    assert "MIGRATION_EVIDENCE_NAME" in paper
    assert 'assert migration_verification["decision"] == "pass"' in paper
    assert 'assert snapshot["state_isolated_from_issue_984"] is True' in paper
    assert 'assert snapshot["issue_984_state_artifact_touched"] is False' in paper
    assert 'assert snapshot["persistent_runtime_database_on_github"] is False' in paper
    assert 'assert snapshot["real_exchange_orders"] is False' in paper
    assert "#984" not in paper


def test_v2_cutover_keeps_state_artifact_name_and_read_only_transport() -> None:
    text = _text()
    paper = _paper_job()
    assert "STATE_ARTIFACT: nexus-persistent-paper-trading-state" in paper
    assert "contents: read" in text
    assert "actions: read" in text
    assert "contents: write" not in text
    assert "actions: write" not in text
    assert "github_actions" not in paper.lower() or "persistent_runtime_database_on_github" in paper


def test_exact_source_checkout_is_per_run_and_does_not_depend_on_shared_git_lock_cleanup() -> None:
    paper = _paper_job()
    prepare = paper.split(
        "Prepare exact repository and pre-provisioned Python 3.12 without JavaScript actions", 1
    )[1].split("Enforce eligible Bybit network execution plane", 1)[0]
    assert 'source_root="$HOME/.local/share/nexus/persistent-paper-source/$GITHUB_RUN_ID"' in prepare
    assert 'rm -rf "$source_root"' in prepare
    assert 'mkdir -p "$source_root"' in prepare
    assert 'cd "$source_root"' in prepare
    assert "git init ." in prepare
    assert "shallow.lock" not in prepare
    assert "SOURCE_ROOT=" in prepare


def test_contract_job_covers_v2_controller_lifecycle_and_existing_migration_contract() -> None:
    text = _text()
    contract = text.split("Verify persistent Trading Engine contracts", 1)[1].split(
        "  runtime-wheelhouse:", 1
    )[0]
    for path in (
        "tests/test_nexus_multipair_persistent_paper_trading_loop.py",
        "tests/test_nexus_multipair_persistent_paper_workflow.py",
        "tests/test_nexus_multipair_regime_lifecycle.py",
        "tests/test_nexus_multipair_demo_strategy_matrix.py",
    ):
        assert path in contract


def test_v2_implementation_and_manifest_changes_retrigger_push_and_pr() -> None:
    text = _text()
    for path in (
        '"nexus_multipair_persistent_paper_trading_loop.py"',
        '"nexus_multipair_public_regime_cycle.py"',
        '"nexus_multipair_regime_lifecycle.py"',
        '"nexus_multipair_demo_strategy_matrix.py"',
        '"config/nexus-demo-strategy-matrix-v2.json"',
        '"tests/test_nexus_multipair_persistent_paper_trading_loop.py"',
        '"tests/test_nexus_multipair_persistent_paper_workflow.py"',
        '"tests/test_nexus_multipair_regime_lifecycle.py"',
        '"tests/test_nexus_multipair_demo_strategy_matrix.py"',
    ):
        assert text.count(path) >= 2


def test_state_handoff_keeps_full_state_but_uses_bounded_cross_file_xz_compression() -> None:
    text = _text()
    paper = _paper_job()
    package = paper.split("Package Paper state for hosted artifact persistence", 1)[1]
    persist = text.split("  persist-state:", 1)[1]
    assert "persistent-state-handoff.tar.xz" in package
    assert 'tarfile.open(output, "w:xz", preset=9)' in package
    assert "state_handoff_tar_xz_bytes=" in package
    assert 'state_b64_bytes" -gt 720000' in package
    assert "zipfile.ZIP_LZMA" not in package
    assert "persistent-state-handoff.tar.xz" in persist
    assert 'tarfile.open(archive_path, "r:xz")' in persist
    assert "archive.extractall" not in persist
    assert "member.issym()" in persist
    assert "member.islnk()" in persist


def test_failed_physical_runtime_cannot_persist_partial_state() -> None:
    text = _text()
    paper = _paper_job()
    package = paper.split("Package Paper state for hosted artifact persistence", 1)[1]
    persist_header = text.split("  persist-state:", 1)[1].split("    env:", 1)[0]
    assert "if: success()" in package
    assert "needs.paper-loop.result == 'success'" in persist_header
