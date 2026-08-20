from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MISSION_QUEUE = ROOT / ".github" / "workflows" / "nexus-mission-queue.yml"
LOCAL_RUNNER = ROOT / ".github" / "workflows" / "nexus-local-runner.yml"


def test_final_sha_cloud_and_physical_proofs_share_trusted_main_trigger_surfaces():
    mission = MISSION_QUEUE.read_text(encoding="utf-8")
    local = LOCAL_RUNNER.read_text(encoding="utf-8")

    # A Phase 7 regression change can force the exact-main cloud proof without
    # adding a workflow, job, permission, or synthetic provider execution.
    assert "branches: [main]" in mission
    assert "'tests/test_phase7_*.py'" in mission
    assert "python -m scripts.phase7_proof_prepare --source-sha \"$NEXUS_PROOF_SOURCE_SHA\"" in mission
    assert "name: nexus-phase7-proof-${{ github.event.pull_request.head.sha || github.sha }}" in mission
    assert "assert run['paper_only'] is True" in mission
    assert "assert run['live_trading_authority'] is False" in mission

    # The same final merge can request the real existing physical Windows lane
    # by changing the already-approved bootstrap trigger path and carrying the
    # existing read-only proof/compatibility markers in its merge message.
    assert "- scripts/bootstrap_portable_python.cmd" in local
    assert "runs-on: [self-hosted, Windows, X64]" in local
    assert "ref: ${{ github.sha }}" in local
    assert "persist-credentials: false" in local
    assert "'[verify-owner-autostart]'" in local
    assert "'[sidecar-compat]'" in local
    assert "nexus-owner-autostart-proof-${{ github.run_id }}" in local
    assert "nexus-windows-sidecar-local-compat-${{ github.run_id }}" in local
