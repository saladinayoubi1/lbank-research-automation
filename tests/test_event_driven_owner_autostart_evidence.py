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


def test_owner_proof_bridge_exposes_requested_and_in_progress_without_polling():
    text = body()
    assert "types: [requested, in_progress, completed]" in text
    assert "const workflowRunAction = context.payload.action;" in text
    assert "workflowRunAction === 'requested' || workflowRunAction === 'in_progress'" in text
    assert "const localRunnerState = workflowRunAction === 'requested' ? 'REQUESTED' : 'IN_PROGRESS';" in text
    assert "state: 'PENDING'" in text
    assert "workflow event action:" in text
    assert "workflow run id:" in text
    assert "queue/dispatch evidence only" in text
    assert "github.event.workflow_run.name == 'NEXUS Local Runner'" in text
    assert "github.event.action == 'requested'" in text
    assert "github.event.action == 'in_progress'" in text


def test_early_owner_proof_evidence_is_exact_commit_and_canonical_run_bound():
    text = body()
    early = text.index("if (run?.name === installWorkflow && earlyLocalRunnerAction)")
    completed = text.index("if (run?.name === packageWorkflow)")
    section = text[early:completed]
    assert "run.event !== 'push'" in section
    assert "run.head_branch !== defaultBranch" in section
    assert "const expectedRunUrl = `https://github.com/${owner}/${repo}/actions/runs/${run.id}`;" in section
    assert "run.html_url !== expectedRunUrl" in section
    assert "github.rest.repos.getCommit" in section
    assert "commit?.sha !== run.head_sha" in section
    assert "ownerProofRequested" in section
    assert "nexus-owner-autostart-proof-${run.id}" in section


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
