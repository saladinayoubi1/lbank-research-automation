from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = (
    ROOT / ".github" / "workflows" / "backup-restore-readiness.yml",
    ROOT / ".github" / "workflows" / "disaster-recovery-readiness.yml",
)
CHECKOUT_SHA = "actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683"
PYTHON_SHA = "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065"


def test_recovery_gates_revalidate_exact_main_and_pr_candidates():
    for path in WORKFLOWS:
        text = path.read_text(encoding="utf-8")
        assert "push:\n    branches: [main]" in text
        assert "pull_request:" in text
        assert "workflow_dispatch:" in text


def test_recovery_gates_use_pinned_read_only_checkout():
    for path in WORKFLOWS:
        text = path.read_text(encoding="utf-8")
        assert CHECKOUT_SHA in text
        assert PYTHON_SHA in text
        assert "persist-credentials: false" in text
        assert "permissions:\n  contents: read" in text
        assert "contents: write" not in text
