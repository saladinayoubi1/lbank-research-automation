from pathlib import Path


WORKFLOW = Path(".github/workflows/nexus_strategy_discovery_rotation.yml")


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_source_stale_workflow_run_is_skipped_before_checkout_and_dispatch():
    text = _text()
    contract = text.split('  contract-test:', 1)[1].split('  dispatch-one-stage:', 1)[0]
    assert "github.event.workflow_run.head_sha == github.sha" in contract
    assert "github.event_name != 'workflow_run'" in contract
    assert contract.index('if: >-') < contract.index('runs-on: ubuntu-latest')
    # The dependent dispatcher cannot start when contract-test is skipped.
    dispatch = text.split('  dispatch-one-stage:', 1)[1]
    assert 'needs: contract-test' in dispatch


def test_rotation_keeps_daily_fallback_and_adds_paper_and_demo_health_events():
    text = _text()
    assert 'cron: "37 2 * * *"' in text
    assert "workflow_run:" in text
    assert '"NEXUS persistent Paper trading loop"' in text
    assert '"NEXUS Demo regime lifecycle bridge"' in text
    assert "types: [completed]" in text


def test_health_event_consumes_exact_triggering_run_artifact_before_dispatch():
    text = _text()
    assert "github.event.workflow_run.id" in text
    assert "actions/runs/$TRIGGER_RUN_ID/artifacts" in text
    assert "nexus-persistent-paper-trading-state" in text
    assert "nexus-demo-strategy-matrix-state" in text
    assert "nexus_strategy_discovery_health_trigger.py" in text
    assert "nexus_demo_strategy_discovery_health_trigger.py" in text
    assert "should_dispatch" in text


def test_missing_exact_trigger_artifact_fails_closed_without_false_ci_failure():
    text = _text()
    health_gate = text.split("Decide daily or health-driven dispatch", 1)[1].split(
        "Restore rotation state", 1
    )[0]
    assert 'if [ -z "$artifact_id" ]; then' in health_gate
    assert 'echo "should_dispatch=false" >> "$GITHUB_OUTPUT"' in health_gate
    assert "health dispatch remains fail-closed" in health_gate
    assert health_gate.index('if [ -z "$artifact_id" ]; then') < health_gate.index(
        'gh api "repos/$GITHUB_REPOSITORY/actions/artifacts/$artifact_id/zip"'
    )


def test_workflow_run_checkout_is_pinned_to_triggering_sha():
    text = _text()
    binding = "github.event.workflow_run.head_sha"
    assert text.count(binding) >= 3
    assert "ref: ${{ github.event_name == 'workflow_run' && github.event.workflow_run.head_sha || github.sha }}" in text


def test_health_dispatch_installs_runtime_dependencies_before_importing_verifiers():
    text = _text()
    dispatch = text.split("dispatch-one-stage:", 1)[1]
    install = "python -m pip install -r requirements.lock"
    persistent_trigger = "python nexus_strategy_discovery_health_trigger.py"
    demo_trigger = "python nexus_demo_strategy_discovery_health_trigger.py"
    assert install in dispatch
    assert "python -m pip check" in dispatch
    assert dispatch.index(install) < dispatch.index(persistent_trigger)
    assert dispatch.index(install) < dispatch.index(demo_trigger)


def test_rotation_preserves_bounded_dispatch_authority():
    text = _text()
    permissions = text.split("permissions:", 1)[1].split("concurrency:", 1)[0]
    assert "contents: read" in permissions
    assert "actions: write" in permissions
    assert "contents: write" not in permissions
    assert "id-token: write" not in permissions
    assert "packages: write" not in permissions
    assert 'gh workflow run "$workflow" --ref main' in text
    assert "nexus_strategy_discovery_rotation.py commit" in text


def test_health_dispatch_is_gated_but_daily_rotation_remains_independent():
    text = _text()
    assert "HEALTH_TRIGGER" in text
    assert "TRIGGER_WORKFLOW" in text
    assert "steps.health-gate.outputs.should_dispatch == 'true'" in text
    assert "github.event_name != 'workflow_run'" in text


def test_rotation_reconciles_research_outcomes_before_dispatching_next_stage():
    text = _text()
    reconcile = text.split("Reconcile previously dispatched Research outcome", 1)[1].split(
        "Verify discovery surface and select one stage", 1
    )[0]
    assert "last-research-run.json" in reconcile
    assert 'gh run view "$run_id"' in reconcile
    assert 'gh run download "$run_id"' in reconcile
    assert "nexus_strategy_discovery_feedback.py" in reconcile
    assert 'echo "ready=false" >> "$GITHUB_OUTPUT"' in reconcile
    assert "--feedback-state build/discovery/feedback-state.json" in text


def test_rotation_persists_exact_dispatched_research_run_for_next_feedback_cycle():
    text = _text()
    dispatch = text.split("Dispatch reviewed Research workflow", 1)[1].split(
        "Commit rotation cursor only after accepted dispatch", 1
    )[0]
    assert "dispatch_sha" in dispatch
    assert "research_run_id" in dispatch
    assert "last-research-run.json" in dispatch
    assert "automatic_strategy_promotion" in dispatch
    assert "live_trading_authority" in dispatch

def test_rotation_restores_only_verified_newest_successful_main_state():
    workflow = _text()
    restore = workflow.split("Restore rotation state", 1)[1].split(
        "Reconcile previously dispatched Research outcome", 1
    )[0]
    assert "per_page=100" in restore
    assert 'sort_by(.created_at) | reverse' in restore
    assert '.workflow_run.head_branch == "main"' in restore
    assert '.conclusion == "success"' in restore
    assert "load_state(Path" in restore
    assert "load_feedback(" in restore


def test_reconciliation_requires_exact_workflow_source_and_artifact():
    workflow = _text()
    reconcile = workflow.split("Reconcile previously dispatched Research outcome", 1)[1].split(
        "Verify discovery surface and select one stage", 1
    )[0]
    assert 'run["headSha"] == meta["head_sha"] == receipt["source_sha"]' in reconcile
    assert 'meta["path"] == receipt["workflow"]' in reconcile
    assert 'meta["head_branch"] == "main"' in reconcile
    assert "expected-source-sha" in reconcile
    assert 'gh run download "$run_id"' in reconcile
    assert 'gh run download "$run_id" --repo "$GITHUB_REPOSITORY"             --dir build/discovery/research-outcome-artifacts || true' not in reconcile


def test_dispatch_must_bind_new_run_not_preexisting_same_sha():
    workflow = _text()
    dispatch = workflow.split("Dispatch reviewed Research workflow", 1)[1].split(
        "Commit rotation cursor only after accepted dispatch", 1
    )[0]
    assert "prior_runs=" in dispatch
    assert "dispatch_started=" in dispatch
    assert '--argjson before "$prior_runs"' in dispatch
    assert ".createdAt >= $started" in dispatch
    assert "if length == 1 then .[0].databaseId else empty end" in dispatch
