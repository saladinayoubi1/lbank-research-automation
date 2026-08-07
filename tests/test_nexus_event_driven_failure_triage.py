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
    for forbidden in ('contents: write', 'actions: write', 'pull-requests: write', 'packages: write', 'id-token: write'):
        assert forbidden not in text


def test_third_party_action_is_pinned_to_full_sha():
    text = _text()
    match = re.search(r'uses:\s*actions/github-script@([0-9a-f]{40})\b', text)
    assert match, 'github-script must be pinned to a full immutable commit SHA'
    assert '@v7' not in text


def test_only_expected_source_workflows_are_allowlisted():
    text = _text()
    for name in ('Test', 'NEXUS Cloud Fallback', 'NEXUS Build Verification'):
        assert f'- {name}' in text
    assert 'NEXUS Event-Driven Failure Triage' not in text.split('workflows:', 1)[1].split('types:', 1)[0]


def test_only_failure_like_conclusions_can_run_job():
    text = _text()
    for conclusion in ('failure', 'cancelled', 'timed_out', 'action_required'):
        assert f"github.event.workflow_run.conclusion == '{conclusion}'" in text
    for rejected in ('success', 'neutral', 'skipped'):
        assert f"github.event.workflow_run.conclusion == '{rejected}'" not in text


def test_duplicate_delivery_uses_stable_workflow_and_sha_marker():
    text = _text()
    assert 'nexus-ci-triage:${run.name}:${run.head_sha}' in text
    assert "(i.body || '').includes(marker)" in text
    assert 'issues.update' in text
    assert 'issues.create' in text


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
