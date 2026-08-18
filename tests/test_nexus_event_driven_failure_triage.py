from pathlib import Path
import re

WORKFLOW = Path('.github/workflows/nexus-event-driven-failure-triage.yml')


def _text():
    return WORKFLOW.read_text(encoding='utf-8')


def test_privileged_workflow_has_exact_minimal_permissions():
    text = _text()
    assert 'contents: read' in text
    assert 'actions: read' in text
    assert 'issues: write' in text
    assert 'pull-requests: read' in text
    for forbidden in ('contents: write', 'actions: write', 'pull-requests: write', 'packages: write', 'id-token: write'):
        assert forbidden not in text


def test_third_party_action_is_pinned_to_full_sha():
    text = _text()
    match = re.search(r'uses:\s*actions/github-script@([0-9a-f]{40})\b', text)
    assert match, 'github-script must be pinned to a full immutable commit SHA'
    assert '@v7' not in text


def test_only_expected_source_workflows_are_allowlisted_at_trigger_and_job_gate():
    text = _text()
    for name in ('Test', 'NEXUS Cloud Fallback', 'NEXUS Build Verification'):
        assert f'- {name}' in text
        assert f"github.event.workflow_run.name == '{name}'" in text
    assert 'NEXUS Event-Driven Failure Triage' not in text.split('workflows:', 1)[1].split('types:', 1)[0]


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
    success_index = text.index("if (run.conclusion === 'success')")
    create_index = text.index('github.rest.issues.create')
    assert success_index < create_index


def test_malformed_metadata_fails_closed_before_issue_write():
    text = _text()
    guard_index = text.index("core.warning('Rejected malformed or non-allow-listed workflow_run metadata")
    list_index = text.index('github.rest.issues.listForRepo')
    create_index = text.index('github.rest.issues.create')
    assert guard_index < list_index < create_index
    assert "allowedWorkflows.has(run.name)" in text
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


def test_superseded_pull_request_failures_are_retired_by_exact_open_head_sha():
    text = _text()
    assert 'github.rest.pulls.list' in text
    assert "state: 'open'" in text
    assert 'const activePrHeads = new Set(openPulls.map(pr => pr.head?.sha).filter(Boolean));' in text
    assert "parsed.event === 'pull_request' && !activePrHeads.has(parsed.sha)" in text
    assert 'the pull request is closed or its head advanced to a newer SHA.' in text


def test_exact_sha_success_closes_matching_failure_and_default_branch_supersedes_older_failures():
    text = _text()
    assert "if (run.conclusion === 'success')" in text
    assert "the exact SHA now has a successful workflow run." in text
    assert "parsed.event === 'push'" in text
    assert 'parsed.branch === defaultBranch' in text
    assert 'parsed.workflow === run.name' in text
    assert 'parsed.sha !== run.head_sha' in text
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
