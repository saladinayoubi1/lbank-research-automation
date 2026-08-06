import json
import tempfile
import unittest
from pathlib import Path

from scripts.check_workflow_permissions import run


class WorkflowPermissionsTests(unittest.TestCase):
    def fixture(self, workflow: str, *, jobs=None, workflow_name="test.yml"):
        root = Path(tempfile.mkdtemp())
        workflows = root / ".github" / "workflows"
        workflows.mkdir(parents=True)
        path = workflows / workflow_name
        path.write_text(workflow, encoding="utf-8")
        policy = root / "policy.json"
        policy.write_text(
            json.dumps(
                {
                    "version": 1,
                    "workflows": {
                        path.as_posix(): {
                            "policy_version": 1,
                            "workflow_permissions": {"contents": "read"},
                            "jobs": jobs or {"audit": {"policy_version": 1}},
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        return workflows, policy, path

    def assertBlocked(self, workflow, pattern, *, jobs=None):
        workflows, policy, _ = self.fixture(workflow, jobs=jobs)
        with self.assertRaisesRegex(ValueError, pattern):
            run(workflows, policy)

    def test_read_only_workflow_passes(self):
        workflows, policy, _ = self.fixture(
            "name: test\non: push\npermissions:\n  contents: read\njobs:\n  audit:\n    runs-on: ubuntu-latest\n    steps: []\n"
        )
        self.assertEqual(len(run(workflows, policy)), 1)

    def test_write_all_blocked(self):
        self.assertBlocked(
            "name: test\non: push\npermissions: write-all\njobs:\n  audit:\n    runs-on: ubuntu-latest\n    steps: []\n",
            "scalar permissions",
        )

    def test_duplicate_keys_blocked(self):
        self.assertBlocked(
            "name: test\non: push\npermissions:\n  contents: read\npermissions:\n  contents: write\njobs:\n  audit:\n    runs-on: ubuntu-latest\n    steps: []\n",
            "duplicate YAML key",
        )

    def test_aliases_and_anchors_blocked(self):
        self.assertBlocked(
            "name: test\non: push\npermissions: &p\n  contents: read\njobs:\n  audit:\n    permissions: *p\n    runs-on: ubuntu-latest\n    steps: []\n",
            "anchors|aliases",
        )

    def test_malformed_yaml_blocked(self):
        self.assertBlocked(
            "name: [broken\npermissions:\n  contents: read\njobs:\n  audit: {}\n",
            "malformed YAML",
        )

    def test_job_escalation_blocked(self):
        self.assertBlocked(
            "name: test\non: push\npermissions:\n  contents: read\njobs:\n  audit:\n    permissions:\n      contents: write\n    runs-on: ubuntu-latest\n    steps: []\n",
            "differs from policy|widens",
            jobs={"audit": {"policy_version": 1, "permissions": {"contents": "write"}, "write_justification": "test"}},
        )

    def test_inline_permissions_mapping_is_parsed(self):
        workflows, policy, _ = self.fixture(
            "name: test\non: push\npermissions: {contents: read}\njobs:\n  audit:\n    runs-on: ubuntu-latest\n    steps: []\n"
        )
        self.assertEqual(len(run(workflows, policy)), 1)

    def test_inline_write_permissions_blocked(self):
        self.assertBlocked(
            "name: test\non: push\npermissions: {contents: write}\njobs:\n  audit:\n    runs-on: ubuntu-latest\n    steps: []\n",
            "differ|justification",
        )

    def test_new_workflow_without_policy_blocked(self):
        workflows, policy, _ = self.fixture(
            "name: test\non: push\npermissions:\n  contents: read\njobs:\n  audit:\n    runs-on: ubuntu-latest\n    steps: []\n"
        )
        (workflows / "new.yml").write_text(
            "name: new\non: push\npermissions:\n  contents: read\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps: []\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "inventory mismatch"):
            run(workflows, policy)

    def test_undocumented_workflow_write_blocked(self):
        workflows, policy, path = self.fixture(
            "name: test\non: push\npermissions:\n  contents: write\njobs:\n  audit:\n    runs-on: ubuntu-latest\n    steps: []\n"
        )
        data = json.loads(policy.read_text(encoding="utf-8"))
        data["workflows"][path.as_posix()]["workflow_permissions"] = {"contents": "write"}
        policy.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "lacks justification"):
            run(workflows, policy)


if __name__ == "__main__":
    unittest.main()
