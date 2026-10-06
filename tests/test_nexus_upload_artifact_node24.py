from __future__ import annotations

from pathlib import Path


WORKFLOWS = Path(".github/workflows")
PHYSICAL_WSL1_WORKFLOW = WORKFLOWS / "nexus_composite_runtime_requalification.yml"
DEPRECATED_UPLOAD_ARTIFACT = "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02"
NODE24_UPLOAD_ARTIFACT = "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"


def test_physical_wsl1_job_is_action_free_and_hosted_publication_uses_node24() -> None:
    nexus = list(WORKFLOWS.glob("nexus*.yml"))
    assert nexus
    workflow = PHYSICAL_WSL1_WORKFLOW.read_text(encoding="utf-8")
    runtime = workflow.split("  runtime-requalification:", 1)[1].split("  contract-test:", 1)[0]
    hosted = workflow.split("  contract-test:", 1)[1]

    # WSL1 cannot execute the runner's Node24 binary. Keep the physical Bybit
    # job completely JavaScript-action-free instead of granting a Node20 exception.
    assert "uses:" not in runtime
    assert DEPRECATED_UPLOAD_ARTIFACT not in runtime
    assert NODE24_UPLOAD_ARTIFACT not in runtime

    # Evidence publication happens only on the hosted contract-test job, where
    # the repository-wide Node24 upload-artifact pin remains mandatory.
    assert DEPRECATED_UPLOAD_ARTIFACT not in workflow
    assert NODE24_UPLOAD_ARTIFACT in hosted

    all_other = "\n".join(
        path.read_text(encoding="utf-8")
        for path in nexus
        if path != PHYSICAL_WSL1_WORKFLOW
    )
    assert DEPRECATED_UPLOAD_ARTIFACT not in all_other
    assert NODE24_UPLOAD_ARTIFACT in all_other
