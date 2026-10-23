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
    assert "nexus-persistent-paper-public-boundary" in text
    assert "nexus-demo-strategy-matrix-state" in text
    assert "scripts/nexus_public_paper_boundary_proof.py verify" in text
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
    public_paper_verifier = "python scripts/nexus_public_paper_boundary_proof.py verify"
    demo_trigger = "python nexus_demo_strategy_discovery_health_trigger.py"
    assert install in dispatch
    assert "python -m pip check" in dispatch
    assert dispatch.index(install) < dispatch.index(public_paper_verifier)
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


def test_unique_new_run_jq_filter_rejects_existing_same_sha_when_available():
    import json
    import re
    import shutil
    import subprocess

    import pytest

    if shutil.which("jq") is None:
        pytest.skip("jq integration runs on an available platform")
    dispatch = _text().split("Dispatch reviewed Research workflow", 1)[1].split(
        "Commit rotation cursor only after accepted dispatch", 1
    )[0]
    query = dispatch.split('--argjson before "$prior_runs"', 1)[1].split("'", 2)[1]
    assert "select(.headSha == $sha" in query, "the real jq program must be selected"
    existing = {"databaseId": 100, "headSha": "a" * 40,
                "createdAt": "2026-09-29T00:00:02Z"}
    fresh = {"databaseId": 101, "headSha": "a" * 40,
             "createdAt": "2026-09-29T00:00:05Z"}
    args = ["jq", "-r", "--arg", "sha", "a" * 40, "--arg", "started",
            "2026-09-29T00:00:03Z", "--argjson", "before",
            json.dumps([{"databaseId": existing["databaseId"]}]), query]
    result = subprocess.run(args, input=json.dumps([existing, fresh]), text=True,
                            capture_output=True, check=False)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "101"
    ambiguous = subprocess.run(args, input=json.dumps([existing, fresh,
                           {**fresh, "databaseId": 102}]), text=True,
                           capture_output=True, check=False)
    assert ambiguous.returncode == 0, ambiguous.stderr
    assert ambiguous.stdout.strip() == "", "ambiguous concurrent runs must fail closed"


def test_lost_prior_research_artifact_is_reason_coded_before_frontier_advances():
    workflow = _text()
    reconcile = workflow.split("Reconcile previously dispatched Research outcome", 1)[1].split(
        "Verify discovery surface and select one stage", 1
    )[0]
    assert "research_outcome_artifact=UNAVAILABLE_FAIL_CLOSED" in reconcile
    assert "--artifact-unavailable" in reconcile
    assert "artifact_unavailable=true" in reconcile


def test_reused_source_exhaustion_is_not_misreported_as_failed_or_new_proof():
    """A no-change discovery legitimately reuses an older certified artifact."""
    text = _text()
    certificate = text.split(
        "Obtain only the exact certified prior multi-timeframe outcome", 1
    )[1].split("Restore integrity-bound prior independent research frontier", 1)[0]
    assert "id: certified-source" in certificate
    assert "artifacts_json=" in certificate
    assert 'artifact_match_count="$(jq -er' in certificate
    assert 'if [ "$artifact_match_count" = "0" ]; then' in certificate
    assert "NOT_EMITTED_NO_NEW_EVIDENCE" in certificate
    assert 'echo "available=false" >> "$GITHUB_OUTPUT"' in certificate
    assert 'if [ "$artifact_match_count" != "1" ]; then' in certificate
    assert "Ambiguous exact-run exhaustion artifact; fail closed" in certificate
    assert 'if ! [[ "$artifact_id" =~ ^[1-9][0-9]*$ ]]; then' in certificate
    assert "Malformed certified artifact ID; fail closed" in certificate
    assert certificate.index('if [ "$artifact_match_count" = "0" ]; then') < (
        certificate.index("Ambiguous exact-run exhaustion artifact")
    )
    # Never publish availability until the exact archive member is unzipped.
    assert certificate.index(
        "unzip -p build/research-feedback/exact-exhaustion.zip"
    ) < certificate.index('echo "available=true" >> "$GITHUB_OUTPUT"')
    assert "exhaustion-certificate.json" in certificate


def test_uncertified_discovery_cannot_advance_frontier_or_publish_design():
    text = _text()
    for step in (
        "Restore integrity-bound prior independent research frontier",
        "Issue one unexecuted NEW mechanism design after verified exhaustion",
    ):
        block = text.split("      - name: " + step, 1)[1]
        assert (
            "if: steps.health-gate.outputs.should_feedback == 'true' && "
            "steps.certified-source.outputs.available == 'true'"
        ) in block.split("shell: bash", 1)[0]
    upload = text.split("name: nexus-research-frontier-state", 1)[0].split(
        "- uses: actions/upload-artifact@", 1
    )[-1]
    assert (
        "steps.certified-source.outputs.available == 'true'"
    ) in upload

def test_feedback_requires_exact_trigger_run_composite_ledger_before_new_design():
    text = _text()
    certificate = text.split(
        "Obtain only the exact certified prior multi-timeframe outcome", 1
    )[1].split("Restore integrity-bound prior independent research frontier", 1)[0]
    assert 'nexus-composite-novelty-state' in certificate
    assert 'composite_match_count=' in certificate
    assert 'if [ "$composite_match_count" = "0" ]; then' in certificate
    assert "NOT_EMITTED_NO_EVALUATED_LEDGER" in certificate
    assert 'echo "available=false" >> "$GITHUB_OUTPUT"' in certificate
    assert "Ambiguous exact-run composite novelty artifact; fail closed" in certificate
    assert "novelty-ledger.json" in certificate
    assert "research-report.json" in certificate
    assert "evaluated-ledger.json" in certificate
    feedback = text.split(
        "Issue one unexecuted NEW mechanism design after verified exhaustion", 1
    )[1].split("- uses: actions/upload-artifact@", 1)[0]
    assert "--evaluated-ledger build/research-feedback/input/evaluated-ledger.json" in feedback


def test_terminal_frontier_reports_blocked_without_dispatching_or_moving_cursor():
    text = _text()
    decision = text.split("Verify discovery surface and select one stage", 1)[1].split(
        "Dispatch reviewed Research workflow", 1
    )[0]
    assert "id: frontier-selection" in decision
    assert "--blocked-receipt-on-exhaustion" in decision
    assert 'echo "ready=false" >> "$GITHUB_OUTPUT"' in decision
    assert "BLOCKED_NEW_MECHANISM_REQUIRED" in decision
    for name, next_name in (
        ("Dispatch reviewed Research workflow", "Commit rotation cursor only after accepted dispatch"),
        ("Commit rotation cursor only after accepted dispatch", "Obtain only the exact certified prior multi-timeframe outcome"),
    ):
        step = text.split(name, 1)[1].split(next_name, 1)[0]
        assert "steps.frontier-selection.outputs.ready == 'true'" in step


def test_unavailable_feedback_cannot_bootstrap_autonomous_dispatch():
    workflow = _text()
    stage = workflow.split("Verify discovery surface and select one stage", 1)[1].split(
        "Dispatch reviewed Research workflow", 1
    )[0]
    assert "--require-feedback-state" in stage
    assert "--blocked-receipt-on-exhaustion" in stage
    assert "steps.frontier-selection.outputs.ready == 'true'" in workflow


def test_restore_and_reconciliation_require_feedback_before_any_reset():
    workflow = _text()
    restore = workflow.split("Restore rotation state", 1)[1].split(
        "Reconcile previously dispatched Research outcome", 1
    )[0]
    assert 'load_feedback(Path("build/discovery/feedback-state.json"), require_existing=True)' in restore
    reconcile = workflow.split("Reconcile previously dispatched Research outcome", 1)[1].split(
        "Verify discovery surface and select one stage", 1
    )[0]
    assert "set -euo pipefail" in reconcile
    command = reconcile.split("python nexus_strategy_discovery_feedback.py", 1)[1].split(
        'rm -f "$receipt"', 1
    )[0]
    assert "--require-feedback-state" in command



def test_all_strategy_stage_completions_wake_the_existing_rotation():
    text = _text()
    trigger = text.split("  workflow_run:", 1)[1].split("  push:", 1)[0]
    expected = (
        "NEXUS multi-timeframe strategy discovery",
        "NEXUS Multi-Pair Discovery v2 physical proof",
        "Bybit strategy search v2",
        "Bybit portfolio search v3",
        "Bybit long short search v4",
        "Bybit consensus search v5",
        "Bybit regime search v6",
        "Bybit neighborhood validation v7",
    )
    for workflow_name in expected:
        assert f'- "{workflow_name}"' in trigger
    assert "types: [completed]" in trigger
    assert 'cron: "37 2 * * *"' in text  # fallback remains, not the normal continuation path
    assert '"NEXUS strategy discovery rotation"' not in trigger
    assert '"Fast Agent Coordinator"' not in trigger


def test_successful_main_strategy_dispatch_completion_can_continue_same_rotation():
    text = _text()
    dispatch = text.split("  dispatch-one-stage:", 1)[1].split("    needs:", 1)[0]
    for required in (
        "github.event.workflow_run.head_branch == 'main'",
        "github.event.workflow_run.head_repository.full_name == github.repository",
        "github.event.workflow_run.conclusion == 'success'",
        "github.event.workflow_run.event == 'workflow_dispatch'",
    ):
        assert required in dispatch
    # Paper/Demo health triggers keep their separately verified event path.
    assert "github.event.workflow_run.name == 'NEXUS persistent Paper trading loop'" in dispatch
    assert "github.event.workflow_run.name == 'NEXUS Demo regime lifecycle bridge'" in dispatch


def test_feedback_only_manual_request_stays_non_dispatching_but_exact_completion_continues():
    text = _text()
    env = text.split("      HEALTH_TRIGGER:", 1)[1].split("    steps:", 1)[0]
    assert "NEXUS persistent Paper trading loop" in env
    assert "NEXUS Demo regime lifecycle bridge" in env
    assert "AUTO_CONTINUE:" in text
    for required in (
        "github.event.workflow_run.head_branch == 'main'",
        "github.event.workflow_run.head_repository.full_name == github.repository",
        "github.event.workflow_run.conclusion == 'success'",
        "github.event.workflow_run.event == 'workflow_dispatch'",
        "github.event.workflow_run.head_sha == github.sha",
    ):
        assert required in text.split("      AUTO_CONTINUE:", 1)[1].split("\n", 1)[0]
    gate = text.split("Decide daily or health-driven dispatch", 1)[1].split(
        "Restore rotation state", 1
    )[0]
    assert 'if [ "$FEEDBACK_REQUESTED" = "true" ]; then' in gate
    assert 'if [ "$AUTO_CONTINUE" = "true" ]; then' in gate
    assert 'echo "should_dispatch=true" >> "$GITHUB_OUTPUT"' in gate
    assert 'echo "should_dispatch=false" >> "$GITHUB_OUTPUT"' in gate
    assert "Manual feedback-only request: no subsequent strategy dispatch." in gate



def test_event_driven_rotation_requires_exact_receipt_and_stops_on_retryable_outcomes():
    text = _text()
    env = text.split("      REQUIRE_EXACT_RESEARCH_RECEIPT:", 1)[1].split("\n", 1)[0]
    assert "github.event_name == 'workflow_run'" in env
    assert "NEXUS persistent Paper trading loop" in env
    assert "NEXUS Demo regime lifecycle bridge" in env

    reconcile = text.split("Reconcile previously dispatched Research outcome", 1)[1].split(
        "Verify discovery surface and select one stage", 1
    )[0]
    assert "No prior dispatch receipt for this strategy workflow completion" in reconcile
    assert '"$run_id" != "$TRIGGER_RUN_ID"' in reconcile
    assert "was_processed=" in reconcile
    assert "Triggering research run was already reconciled" in reconcile
    assert "reconciled_run=" in reconcile
    assert '"evidence_unavailable"' in reconcile
    assert '"requires_data"' in reconcile
    assert "stop the immediate chain instead of looping" in reconcile
    assert 'echo "ready=false" >> "$GITHUB_OUTPUT"' in reconcile
