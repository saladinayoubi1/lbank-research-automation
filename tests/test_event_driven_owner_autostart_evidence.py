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



def test_owner_proof_bridge_exposes_pending_from_exact_main_push_without_polling():
    text = body()
    assert "types: [completed]" in text
    assert "context.payload.after" in text
    assert "context.payload.ref" in text
    assert "context.payload.head_commit?.message" in text
    assert "message.includes(ownerProofCommitMarker)" in text
    assert "state: 'PENDING'" in text
    assert "local runner state: `AWAITING_COMPLETION`" in text
    assert "expected completion workflow: `NEXUS Local Runner`" in text
    assert "await upsertOwnerProofEvidence({ sha, state: 'PENDING', lines });" in text
    assert "requested, in_progress" not in text


def test_pending_owner_proof_evidence_is_exact_main_commit_bound():
    text = body()
    push = text.index("if (context.eventName === 'push')")
    completed = text.index("const run = context.payload.workflow_run;")
    section = text[push:completed]
    assert "const sha = context.payload.after;" in section
    assert "const expectedRef = `refs/heads/${defaultBranch}`;" in section
    assert "ref !== expectedRef || !validSha(sha)" in section
    assert "const ownerProofRequested = typeof message === 'string' && message.includes(ownerProofCommitMarker);" in section
    assert "installRequested && ownerProofRequested" in section
    assert "Refused ambiguous repair trigger containing both install and owner-proof markers." in section
    assert "await upsertOwnerProofEvidence({ sha, state: 'PENDING', lines });" in section

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
