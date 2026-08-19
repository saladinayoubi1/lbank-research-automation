from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "nexus-event-driven-failure-triage.yml"


def body() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_owner_autostart_evidence_reuses_trusted_bridge_permissions_and_job():
    text = body()
    permissions = re.search(
        r"(?ms)^permissions:\n(?P<body>(?:  [^\n]+\n)+)\nconcurrency:", text
    )
    assert permissions
    assert {
        line.strip() for line in permissions.group("body").splitlines() if line.strip()
    } == {"contents: read", "actions: read", "issues: write"}
    jobs = re.findall(r"(?m)^  ([A-Za-z0-9_-]+):\n    (?:if:|runs-on:)", text)
    assert jobs == ["triage"]


def test_owner_autostart_proof_bridge_is_exact_and_fail_closed():
    text = body()
    for marker in (
        "const ownerProofCommitMarker = '[verify-owner-autostart]';",
        "<!-- nexus-owner-autostart-proof:${sha} -->",
        "const expectedArtifactName = `nexus-owner-autostart-proof-${run.id}`;",
        "artifact?.expired === false",
        "artifact.id > 0",
        "artifact.size_in_bytes > 0",
        "const artifactVerified = matches.length === 1;",
        "const success = run.conclusion === 'success' && artifactVerified;",
        "installRequested && ownerProofRequested",
        "Refused ambiguous local runner commit containing both install and owner-proof markers.",
        "Artifact contents must still be independently inspected",
        "Owner-user autostart validity is **not** claimed",
    ):
        assert marker in text


def test_owner_proof_bridge_preserves_existing_install_and_package_contracts():
    text = body()
    for marker in (
        "const installCommitMarker = '[install-autostart]';",
        "const expectedArtifactName = `nexus-zero-touch-install-${run.id}`;",
        "const packageWorkflow = 'Build NEXUS Desktop Windows';",
        "const packageArtifactName = 'NEXUS_PERSONAL_PRO_FINAL_MISSION_CONTROL_WINDOWS_5_1_0';",
        "<!-- nexus-windows-main-package:${sha} -->",
    ):
        assert marker in text
