from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_WORKER = ROOT / "scripts" / "nexus_runtime_worker.js"
CUTOVER_WORKFLOW = ROOT / ".github" / "workflows" / "nexus-runner-hidden-cutover.yml"
MARKER = ROOT / ".nexus" / "runner-hidden-cutover.txt"


def test_self_hosted_github_runtime_worker_is_bounded_to_one_cycle() -> None:
    text = RUNTIME_WORKER.read_text(encoding="utf-8")
    for marker in (
        "process.env.GITHUB_ACTIONS === 'true'",
        "process.env.RUNNER_ENVIRONMENT === 'self-hosted-windows'",
        "if (once || boundedGitHubSelfHosted)",
        "bounded_self_hosted_github_cycle=complete",
    ):
        assert marker in text


def test_hidden_cutover_uses_runtime_worker_concurrency_without_local_execution() -> None:
    text = CUTOVER_WORKFLOW.read_text(encoding="utf-8")
    assert "group: nexus-runtime-worker-${{ github.ref }}" in text
    assert "cancel-in-progress: true" in text
    assert "runs-on: ubuntu-latest" in text
    assert "runs-on: [self-hosted" not in text
    assert "sleep 90" in text
    assert "permissions:\n  contents: read" in text


def test_hidden_cutover_is_explicit_marker_driven_and_preserves_authority() -> None:
    workflow = CUTOVER_WORKFLOW.read_text(encoding="utf-8")
    marker = MARKER.read_text(encoding="utf-8")
    assert ".nexus/runner-hidden-cutover.txt" in workflow
    assert "authority=research_backtest_paper_only" in marker
    assert "credentials_modified=false" in marker
    assert "runner_registration_modified=false" in marker
