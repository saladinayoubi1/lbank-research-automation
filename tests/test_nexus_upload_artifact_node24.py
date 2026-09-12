from __future__ import annotations

from pathlib import Path


WORKFLOWS = Path(".github/workflows")
DEPRECATED_UPLOAD_ARTIFACT = "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02"
NODE24_UPLOAD_ARTIFACT = "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"


def test_nexus_workflows_do_not_use_deprecated_node20_upload_artifact() -> None:
    nexus = list(WORKFLOWS.glob("nexus*.yml"))
    assert nexus
    text = "\n".join(path.read_text(encoding="utf-8") for path in nexus)
    assert DEPRECATED_UPLOAD_ARTIFACT not in text
    assert NODE24_UPLOAD_ARTIFACT in text
