"""Safety contracts for action-free, exact-source owner laptop health."""

from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/nexus-local-source-health.yml"


def test_owner_health_is_trusted_action_free_and_bounded():
    source = WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_dispatch:" in source
    assert "github.ref == 'refs/heads/main' && github.actor == github.repository_owner" in source
    assert "runs-on: [self-hosted, Windows, X64, nexus-local]" in source
    assert "contents: read" in source
    assert "cancel-in-progress: false" in source
    assert "timeout-minutes: 20" in source
    assert "uses:" not in source
    assert "actions/upload-artifact@" not in source
    assert "actions/checkout@" not in source
    for forbidden in ("secrets.", "gh auth token", "config.cmd", "live_trading", "orders_allowed"):
        assert forbidden not in source.casefold()


def test_owner_health_requires_isolation_exact_sha_and_original_tests():
    source = WORKFLOW.read_text(encoding="utf-8")
    required = (
        "NEXUS-LOCAL-RUNNER",
        "Unexpected worker identity",
        "Owner source health requires isolated GitHub Actions workspace",
        "GITHUB_SHA",
        "https://codeload.github.com/",
        "--ipv4",
        "--http1.1",
        "--connect-timeout 15",
        "--max-time 150",
        "--speed-limit 1024",
        ".nexus-trigger-source",
        "Exact source binding mismatch",
        "Bootstrap existing locked portable Python",
        "call scripts\\bootstrap_portable_python.cmd",
        "NEXUS_HEALTH_PRIVACY_AND_SHA_PASS=1",
        "tests/test_nexus_architecture_validator.py tests/test_web_dashboard.py",
    )
    for marker in required:
        assert marker in source
    assert "ReparsePoint" in source
    assert source.index("ReparsePoint") < source.index("Remove-Item -Recurse -Force -ErrorAction Stop")
    assert source.index("Owner source health requires isolated GitHub Actions workspace") < source.index(
        "Remove-Item -Recurse -Force -ErrorAction Stop"
    )
