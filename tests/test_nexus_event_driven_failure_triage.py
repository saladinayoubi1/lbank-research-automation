from pathlib import Path
import re

WORKFLOW = Path('.github/workflows/nexus-event-driven-failure-triage.yml')


def _text():
    return WORKFLOW.read_text(encoding='utf-8')


def test_privileged_workflow_has_exact_frozen_permissions():
    text = _text()
    assert 'contents: read' in text
    assert 'actions: read' in text
    assert 'issues: write' in text
    assert 'statuses: write' not in text
    assert 'pull-requests: read' not in text
    for forbidden in ('contents: write', 'actions: write', 'pull-requests: write', 'packages: write', 'id-token: write'):
        assert forbidden not in text


def test_third_party_action_is_pinned_to_full_sha():
    text = _text()
    match = re.search(r'uses:\s*actions/github-script@([0-9a-f]{40})\b', text)
    assert match, 'github-script must be pinned to a full immutable commit SHA'
    assert '@v7' not in text


def test_expected_source_workflows_and_install_dispatch_are_allowlisted():
    text = _text()
    for name in ('Test', 'NEXUS Cloud Fallback', 'NEXUS Build Verification'):
        assert f'- {name}' in text
        assert f"github.event.workflow_run.name == '{name}'" in text
    assert '- NEXUS Local Runner' in text
    assert "github.event.workflow_run.name == 'NEXUS Local Runner'" in text
    assert "github.event_name == 'push'" in text
    assert '- .nexus/repair-trigger.txt' in text
    assert 'NEXUS Event-Driven Failure Triage' not in text.split('workflows:', 1)[1].split('types:', 1)[0]


def test_zero_touch_pending_evidence_is_exact_sha_bound_and_non_success_claiming():
    text = _text()
    assert 'const installIssueNumber = 702;' in text
    assert "const installCommitMarker = '[install-autostart]';" in text
    assert 'nexus-zero-touch-install:${sha}' in text
    assert "state: 'PENDING'" in text
    assert "context.payload.after" in text
    assert "context.payload.head_commit?.message" in text
    assert "message.includes(installCommitMarker)" in text
    assert "ref !== expectedRef || !validSha(sha)" in text
    assert 'Physical installation is **not** claimed' in text
    assert 'expected completion workflow: `NEXUS Local Runner`' in text


def test_local_runner_completion_is_bound_to_main_push_exact_commit_and_canonical_run_url():
    text = _text()
    assert "run?.name === installWorkflow" in text
    assert "run.event !== 'push'" in text
    assert 'run.head_branch !== defaultBranch' in text
    assert 'const expectedRunUrl = `https://github.com/${owner}/${repo}/actions/runs/${run.id}`;' in text
    assert 'run.html_url !== expectedRunUrl' in text
    assert 'github.rest.repos.getCommit' in text
    assert 'commit?.sha !== run.head_sha' in text
    assert '!commitMessage.includes(installCommitMarker)' in text


def test_zero_touch_success_requires_exact_nonexpired_nonempty_artifact_from_same_run():
    text = _text()
    assert 'github.rest.actions.listWorkflowRunArtifacts' in text
    assert 'run_id: run.id' in text
    assert 'const expectedArtifactName = `nexus-zero-touch-install-${run.id}`;' in text
    assert 'artifact?.name === expectedArtifactName' in text
    assert 'artifact?.expired === false' in text
    assert 'artifact.size_in_bytes > 0' in text
    assert 'const artifactVerified = matches.length === 1;' in text
    assert "const success = run.conclusion === 'success' && artifactVerified;" in text
    assert "state: success ? 'SUCCESS' : 'FAILURE'" in text


def test_zero_touch_artifact_lookup_failure_is_recorded_fail_closed():
    text = _text()
    lookup = text.index('github.rest.actions.listWorkflowRunArtifacts')
    failure = text.index("state: 'FAILURE'", lookup)
    assert lookup < failure
    assert 'expected install artifact: `UNVERIFIED`' in text
    assert 'verification error:' in text
    assert 'Physical installation is **not** claimed for this SHA.' in text


def test_zero_touch_comment_upsert_is_stable_and_issue_scoped():
    text = _text()
    assert 'github.rest.issues.listComments' in text
    assert 'issue_number: installIssueNumber' in text
    assert "comment.body.includes(marker)" in text
    assert 'github.rest.issues.updateComment' in text
    assert 'github.rest.issues.createComment' in text
    assert "['PENDING', 'SUCCESS', 'FAILURE'].includes(state)" in text


def test_success_runs_are_observed_for_cleanup_but_only_failure_like_conclusions_create_failure_issues():
    text = _text()
    assert "const allowedConclusions = new Set([" in text
    assert "'success'" in text.split('const allowedConclusions', 1)[1]
    for conclusion in ('failure', 'cancelled', 'timed_out', 'action_required'):
        assert f"'{conclusion}'" in text.split('const failureConclusions', 1)[1]
    for rejected in ('neutral', 'skipped'):
        assert f"'{rejected}'" not in text.split('const allowedConclusions', 1)[1].split(']);', 1)[0]
    assert "if (run.conclusion === 'success')" in text
    assert 'if (!failureConclusions.has(run.conclusion))' in text
    assert text.index("if (run.conclusion === 'success')") < text.index('github.rest.issues.create({ owner, repo, title, body })')


def test_malformed_generic_metadata_fails_closed_before_failure_issue_write():
    text = _text()
    guard_index = text.index("core.warning('Rejected malformed or non-allow-listed workflow_run metadata")
    list_index = text.index('github.rest.issues.listForRepo')
    create_index = text.index('github.rest.issues.create({ owner, repo, title, body })')
    assert guard_index < list_index < create_index
    assert "ciWorkflows.has(run.name)" in text
    assert "allowedConclusions.has(run.conclusion)" in text
    assert "^[0-9a-f]{40}$" in text
    assert "^https:\\/\\/github\\.com\\/" in text
    assert 'Number.isInteger(run?.run_attempt)' in text
    assert 'return;' in text[guard_index:list_index]


def test_untrusted_display_metadata_is_sanitized_before_markdown_rendering():
    text = _text()
    assert 'const safeInline = (value)' in text
    assert ".replace(/[\\r\\n\\t]/g, ' ')" in text
    assert ".replace(/`/g, '\\\\`')" in text
    assert 'const safeBranch = safeInline(run.head_branch);' in text
    assert 'const safeEvent = safeInline(run.event);' in text
    assert '`- branch: \\`${safeBranch}\\``' in text
    assert '`- event: \\`${safeEvent}\\``' in text
    assert '`- branch: \\`${run.head_branch' not in text


def test_duplicate_delivery_uses_stable_workflow_and_sha_marker():
    text = _text()
    assert 'nexus-ci-triage:${run.name}:${run.head_sha}' in text
    assert "(i.body || '').includes(marker)" in text
    assert 'issues.update' in text
    assert 'issues.create' in text


def test_newer_same_branch_run_retires_older_sha_without_pr_permission():
    text = _text()
    assert 'const currentBranchSupersedes = (parsed)' in text
    assert 'parsed.workflow === run.name' in text
    assert 'parsed.event === run.event' in text
    assert 'parsed.branch === safeBranch' in text
    assert 'parsed.sha !== run.head_sha' in text
    assert 'a newer ${run.name} run exists for branch ${safeBranch}.' in text
    assert 'github.rest.pulls.list' not in text


def test_historical_pr_cleanup_binds_actions_run_to_open_issue_pr_inventory():
    text = _text()
    assert 'const openPrNumbers = new Set(' in text
    assert 'issues.filter(issue => Boolean(issue.pull_request)).map(issue => issue.number)' in text
    assert 'github.rest.actions.getWorkflowRun' in text
    assert 'historical.name === parsed.workflow' in text
    assert 'historical.head_sha === parsed.sha' in text
    assert "historical.event === 'pull_request'" in text
    assert 'historical.html_url === expectedRepoUrl' in text
    assert 'associatedPrNumbers.every(number => !openPrNumbers.has(number))' in text
    assert 'all pull requests bound to workflow run ${parsed.runId} are closed or merged.' in text


def test_historical_cleanup_fails_closed_on_missing_or_mismatched_association():
    text = _text()
    assert 'Preserved triage issue #${issue.number}: historical workflow evidence mismatch.' in text
    assert 'Preserved triage issue #${issue.number}: no independently associated pull request.' in text
    assert 'Preserved triage issue #${issue.number}: historical run verification failed' in text
    assert 'associatedPrNumbers.length === 0' in text


def test_exact_sha_success_and_default_branch_supersession_are_preserved():
    text = _text()
    assert "if (run.conclusion === 'success')" in text
    assert 'the exact SHA now has a successful workflow run.' in text
    assert "parsed.event === 'push'" in text
    assert 'parsed.branch === defaultBranch' in text
    assert 'parsed.workflow === run.name' in text
    assert 'a newer ${run.name} run exists on ${defaultBranch}.' in text


def test_cleanup_is_auditable_and_does_not_delete_issue_history():
    text = _text()
    assert "state: 'closed'" in text
    assert "state_reason: 'not_planned'" in text
    assert 'Closed automatically by NEXUS CI hygiene:' in text
    assert 'issues.delete' not in text


def test_no_privileged_execution_of_triggering_code_or_artifacts():
    text = _text().lower()
    for token in ('actions/checkout', 'download-artifact', 'actions/cache', 'child_process', 'exec(', 'eval('):
        assert token not in text, f'privileged workflow must not execute untrusted material: {token}'
    assert re.search(r'^\s*run\s*:', text, flags=re.MULTILINE) is None, (
        'privileged workflow must not contain a shell run step'
    )


def test_triage_evidence_explicitly_denies_authority():
    text = _text()
    assert 'not releasable / not merge-authorized' in text
    assert 'no credentials, billing, signing, production deployment, or live financial authority' in text
    assert 'Research/Backtest/Paper only' in text
