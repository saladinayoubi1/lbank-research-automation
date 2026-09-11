from pathlib import Path

WORKFLOW = Path('.github/workflows/nexus-event-driven-failure-triage.yml')


def _text() -> str:
    return WORKFLOW.read_text(encoding='utf-8')


def test_pr_close_cleanup_adds_only_trusted_same_repo_event_path():
    text = _text()
    assert '  pull_request:\n    branches:\n      - main\n    types: [closed]' in text
    assert "(github.event_name == 'pull_request' && github.event.action == 'closed')" in text
    assert "if (context.eventName === 'pull_request')" in text
    assert "context.payload.action !== 'closed'" in text
    assert "pr?.base?.ref !== defaultBranch" in text
    assert "pr?.base?.repo?.full_name !== expectedRepo" in text
    assert "pr?.head?.repo?.full_name !== expectedRepo" in text
    assert "pr?.html_url !== expectedUrl" in text
    assert 'pull_request_target:' not in text


def test_pr_close_cleanup_is_exact_sha_branch_bound_and_fail_closed():
    text = _text()
    assert "markerMatch[2] === pr.head.sha" in text
    assert "eventMatch?.[1] === 'pull_request'" in text
    assert "branchMatch?.[1] === pr.head.ref" in text
    assert 'Rejected malformed, forked, or non-default-branch pull request closure metadata' in text
    assert 'Pull request #${prNumber} closure cleanup closed ${closedCount} exact-bound triage issue(s).' in text
    assert 'Closed automatically by NEXUS CI hygiene:' in text


def test_pr_close_cleanup_does_not_expand_privileged_permissions_or_execute_pr_code():
    text = _text()
    permissions = text.split('permissions:', 1)[1].split('concurrency:', 1)[0]
    assert 'contents: read' in permissions
    assert 'actions: read' in permissions
    assert 'issues: write' in permissions
    assert 'pull-requests:' not in permissions
    assert 'contents: write' not in permissions
    assert 'actions: write' not in permissions
    assert 'id-token: write' not in permissions
    lowered = text.lower()
    assert 'actions/checkout' not in lowered
    assert 'download-artifact' not in lowered
    assert 'child_process' not in lowered
