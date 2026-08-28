from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = (
    ROOT / ".github" / "workflows" / "backup-restore-readiness.yml",
    ROOT / ".github" / "workflows" / "disaster-recovery-readiness.yml",
)
CHECKOUT_SHA = "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1"
PYTHON_SHA = "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97"


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
