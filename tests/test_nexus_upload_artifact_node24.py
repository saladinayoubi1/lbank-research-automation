from __future__ import annotations

from pathlib import Path


WORKFLOWS = Path(".github/workflows")
PHYSICAL_WSL1_WORKFLOW = WORKFLOWS / "nexus_composite_runtime_requalification.yml"
DEPRECATED_UPLOAD_ARTIFACT = "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02"
NODE24_UPLOAD_ARTIFACT = "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"


def test_node20_upload_artifact_is_scoped_only_to_physical_wsl1_job() -> None:
    nexus = list(WORKFLOWS.glob("nexus*.yml"))
    assert nexus
    physical = PHYSICAL_WSL1_WORKFLOW.read_text(encoding="utf-8")
    contract, runtime = physical.split("  runtime-requalification:", 1)

    # WSL1 cannot execute the runner's Node24 binary. The one physical Bybit
    # job is therefore allowed exactly one SHA-pinned Node20 upload action.
    assert runtime.count(DEPRECATED_UPLOAD_ARTIFACT) == 1
    assert DEPRECATED_UPLOAD_ARTIFACT not in contract

    # Keep the repository-wide deprecation guard for every other NEXUS
    # workflow and every non-physical section of this workflow.
    all_other = "\n".join(
        path.read_text(encoding="utf-8")
        for path in nexus
        if path != PHYSICAL_WSL1_WORKFLOW
    )
    assert DEPRECATED_UPLOAD_ARTIFACT not in all_other
    assert NODE24_UPLOAD_ARTIFACT in all_other
