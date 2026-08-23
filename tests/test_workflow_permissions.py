import json
import tempfile
import unittest
from pathlib import Path

from scripts.check_workflow_permissions import run


VALID = "name: test\non: push\npermissions:\n  contents: read\njobs:\n  audit:\n    runs-on: ubuntu-latest\n    steps: []\n"


class WorkflowPermissionsTests(unittest.TestCase):
    def fixture(self, workflow: str = VALID, *, jobs=None, workflow_name="test.yml"):
        root = Path(tempfile.mkdtemp())
        workflows = root / ".github" / "workflows"
        workflows.mkdir(parents=True)
        path = workflows / workflow_name
        path.write_text(workflow, encoding="utf-8")
        policy = root / "policy.json"
        policy.write_text(json.dumps({"version": 1, "workflows": {path.as_posix(): {"policy_version": 1, "workflow_permissions": {"contents": "read"}, "jobs": jobs or {"audit": {"policy_version": 1}}}}}), encoding="utf-8")
        return workflows, policy, path

    def mutate_policy(self, policy: Path, mutation):
        data = json.loads(policy.read_text(encoding="utf-8"))
        mutation(data)
        policy.write_text(json.dumps(data), encoding="utf-8")

    def assertBlocked(self, workflow, pattern, *, jobs=None):
        workflows, policy, _ = self.fixture(workflow, jobs=jobs)
        with self.assertRaisesRegex(ValueError, pattern):
            run(workflows, policy)

    def test_read_only_workflow_passes(self):
        workflows, policy, _ = self.fixture()
        self.assertEqual(len(run(workflows, policy)), 1)

    def test_explicit_read_only_job_passes(self):
        workflow = VALID.replace("runs-on:", "permissions:\n      contents: read\n    runs-on:")
        jobs = {"audit": {"policy_version": 1, "permissions": {"contents": "read"}}}
        workflows, policy, _ = self.fixture(workflow, jobs=jobs)
        self.assertEqual(len(run(workflows, policy)), 1)

    def test_inline_permissions_mapping_is_parsed(self):
        workflows, policy, _ = self.fixture(VALID.replace("permissions:\n  contents: read", "permissions: {contents: read}"))
        self.assertEqual(len(run(workflows, policy)), 1)

    def test_write_all_blocked(self):
        self.assertBlocked(VALID.replace("permissions:\n  contents: read", "permissions: write-all"), "scalar permissions")

    def test_read_all_scalar_blocked(self):
        self.assertBlocked(VALID.replace("permissions:\n  contents: read", "permissions: read-all"), "scalar permissions")

    def test_duplicate_workflow_permission_keys_blocked(self):
        self.assertBlocked(VALID.replace("permissions:\n  contents: read", "permissions:\n  contents: read\npermissions:\n  contents: write"), "duplicate YAML key")

    def test_duplicate_nested_job_permission_keys_blocked(self):
        workflow = VALID.replace("runs-on:", "permissions:\n      contents: read\n    permissions:\n      contents: write\n    runs-on:")
        self.assertBlocked(workflow, "duplicate YAML key")

    def test_aliases_and_anchors_blocked(self):
        self.assertBlocked("name: test\non: push\npermissions: &p\n  contents: read\njobs:\n  audit:\n    permissions: *p\n    runs-on: ubuntu-latest\n    steps: []\n", "anchors|aliases")

    def test_unused_anchor_blocked(self):
        self.assertBlocked(VALID.replace("name: test", "name: &n test"), "anchors")

    def test_malformed_yaml_blocked(self):
        self.assertBlocked("name: [broken\npermissions:\n  contents: read\njobs:\n  audit: {}\n", "malformed YAML")

    def test_inline_write_permissions_blocked(self):
        self.assertBlocked(VALID.replace("permissions:\n  contents: read", "permissions: {contents: write}"), "differ|justification")

    def test_empty_permissions_mapping_blocked(self):
        self.assertBlocked(VALID.replace("permissions:\n  contents: read", "permissions: {}"), "non-empty explicit mapping")

    def test_unknown_permission_scope_blocked(self):
        self.assertBlocked(VALID.replace("contents: read", "future-super-scope: read"), "unknown permission scope")

    def test_invalid_permission_level_blocked(self):
        self.assertBlocked(VALID.replace("contents: read", "contents: admin"), "invalid level")

    def test_job_escalation_blocked(self):
        workflow = VALID.replace("runs-on:", "permissions:\n      contents: write\n    runs-on:")
        jobs = {"audit": {"policy_version": 1, "permissions": {"contents": "write"}, "write_justification": "mutation"}}
        self.assertBlocked(workflow, "widens", jobs=jobs)

    def test_new_workflow_without_policy_blocked(self):
        workflows, policy, _ = self.fixture()
        (workflows / "new.yml").write_text(VALID.replace("name: test", "name: new"), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "inventory mismatch"):
            run(workflows, policy)

    def test_stale_policy_workflow_blocked(self):
        workflows, policy, path = self.fixture()
        self.mutate_policy(policy, lambda data: data["workflows"].update({"stale.yml": data["workflows"][path.as_posix()]}))
        with self.assertRaisesRegex(ValueError, "inventory mismatch"):
            run(workflows, policy)

    def test_new_job_inventory_drift_blocked(self):
        workflow = VALID.replace("jobs:\n", "jobs:\n  surprise:\n    runs-on: ubuntu-latest\n    steps: []\n")
        self.assertBlocked(workflow, "job inventory differs")

    def test_removed_job_inventory_drift_blocked(self):
        workflows, policy, path = self.fixture()
        self.mutate_policy(policy, lambda data: data["workflows"][path.as_posix()]["jobs"].update({"missing": {"policy_version": 1}}))
        with self.assertRaisesRegex(ValueError, "job inventory differs"):
            run(workflows, policy)

    def test_policy_version_mutation_blocked(self):
        workflows, policy, _ = self.fixture()
        self.mutate_policy(policy, lambda data: data.__setitem__("version", 2))
        with self.assertRaisesRegex(ValueError, "version 1"):
            run(workflows, policy)

    def test_workflow_policy_version_mutation_blocked(self):
        workflows, policy, path = self.fixture()
        self.mutate_policy(policy, lambda data: data["workflows"][path.as_posix()].__setitem__("policy_version", 2))
        with self.assertRaisesRegex(ValueError, "versioned workflow policy"):
            run(workflows, policy)

    def test_job_policy_version_mutation_blocked(self):
        workflows, policy, path = self.fixture()
        self.mutate_policy(policy, lambda data: data["workflows"][path.as_posix()]["jobs"]["audit"].__setitem__("policy_version", 2))
        with self.assertRaisesRegex(ValueError, "lacks versioned policy"):
            run(workflows, policy)

    def test_policy_permission_mutation_blocked(self):
        workflows, policy, path = self.fixture()
        self.mutate_policy(policy, lambda data: data["workflows"][path.as_posix()].__setitem__("workflow_permissions", {"contents": "none"}))
        with self.assertRaisesRegex(ValueError, "differ from policy"):
            run(workflows, policy)

    def test_undocumented_workflow_write_blocked(self):
        workflows, policy, path = self.fixture(VALID.replace("contents: read", "contents: write"))
        self.mutate_policy(policy, lambda data: data["workflows"][path.as_posix()].__setitem__("workflow_permissions", {"contents": "write"}))
        with self.assertRaisesRegex(ValueError, "lacks justification"):
            run(workflows, policy)

    def test_blank_write_justification_blocked(self):
        workflows, policy, path = self.fixture(VALID.replace("contents: read", "contents: write"))
        def mutation(data):
            rule = data["workflows"][path.as_posix()]
            rule["workflow_permissions"] = {"contents": "write"}
            rule["write_justification"] = "   "
        self.mutate_policy(policy, mutation)
        with self.assertRaisesRegex(ValueError, "lacks justification"):
            run(workflows, policy)

    def test_duplicate_policy_json_key_blocked(self):
        workflows, policy, path = self.fixture()
        rule = json.dumps({"policy_version": 1, "workflow_permissions": {"contents": "read"}, "jobs": {"audit": {"policy_version": 1}}})
        policy.write_text('{"version":1,"version":1,"workflows":{' + json.dumps(path.as_posix()) + ':' + rule + '}}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "duplicate policy key"):
            run(workflows, policy)

    def test_unexpected_policy_root_field_blocked(self):
        workflows, policy, _ = self.fixture()
        self.mutate_policy(policy, lambda data: data.__setitem__("bypass", True))
        with self.assertRaisesRegex(ValueError, "unexpected fields"):
            run(workflows, policy)

    def test_unexpected_workflow_policy_field_blocked(self):
        workflows, policy, path = self.fixture()
        self.mutate_policy(policy, lambda data: data["workflows"][path.as_posix()].__setitem__("bypass", True))
        with self.assertRaisesRegex(ValueError, "unexpected fields"):
            run(workflows, policy)

    def test_authoritative_gate_blocks_direct_workflow_input_interpolation(self):
        workflow = VALID.replace(
            "on: push",
            "on:\n  workflow_dispatch:\n    inputs:\n      payload:\n        required: false",
        ).replace("steps: []", "steps:\n      - run: echo '${{ inputs.payload }}'")
        self.assertBlocked(workflow, "interpolates workflow input directly")

    def test_authoritative_gate_blocks_unguarded_self_hosted_pull_request(self):
        workflow = VALID.replace("on: push", "on: pull_request").replace(
            "runs-on: ubuntu-latest", "runs-on: [self-hosted, Windows]"
        )
        self.assertBlocked(workflow, "may execute pull_request code")

    def test_authoritative_gate_blocks_pull_request_secret_exposure(self):
        workflow = VALID.replace("on: push", "on: pull_request").replace(
            "steps: []",
            "env:\n      API_KEY: ${{ secrets.API_KEY }}\n    steps:\n      - run: python main.py",
        )
        self.assertBlocked(workflow, "exposes a secret")

    def test_external_action_mutable_tag_is_blocked(self):
        workflow = VALID.replace("steps: []", "steps:\n      - uses: actions/checkout@v4")
        self.assertBlocked(workflow, "full commit SHA")

    def test_external_action_full_sha_passes(self):
        workflow = VALID.replace(
            "steps: []",
            "steps:\n      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262",
        )
        workflows, policy, _ = self.fixture(workflow)
        self.assertEqual(len(run(workflows, policy)), 1)

    def test_local_action_reference_passes(self):
        workflow = VALID.replace("steps: []", "steps:\n      - uses: ./actions/local")
        workflows, policy, _ = self.fixture(workflow)
        self.assertEqual(len(run(workflows, policy)), 1)


if __name__ == "__main__":
    unittest.main()
