import tempfile
import unittest
from pathlib import Path

from scripts.check_workflow_permissions import load_yaml
from workflow_trust_boundaries import validate_workflow_trust_boundaries


ROOT = Path(__file__).resolve().parents[1]


class WorkflowTrustBoundaryTests(unittest.TestCase):
    def validate(self, text: str) -> None:
        root = Path(tempfile.mkdtemp())
        path = root / "workflow.yml"
        path.write_text(text, encoding="utf-8")
        validate_workflow_trust_boundaries(path, load_yaml(path))

    def assertBlocked(self, text: str, pattern: str) -> None:
        with self.assertRaisesRegex(ValueError, pattern):
            self.validate(text)

    def test_repository_workflow_inventory_passes_trust_boundary_scan(self):
        workflow_root = ROOT / ".github" / "workflows"
        paths = sorted([*workflow_root.glob("*.yml"), *workflow_root.glob("*.yaml")])
        self.assertTrue(paths)
        for path in paths:
            with self.subTest(path=path.name):
                validate_workflow_trust_boundaries(path, load_yaml(path))

    def test_direct_workflow_input_interpolation_in_run_is_blocked(self):
        workflow = """name: bad
on:
  workflow_dispatch:
    inputs:
      payload:
        required: false
permissions:
  contents: read
jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - run: echo '${{ github.event.inputs.payload }}'
"""
        self.assertBlocked(workflow, "interpolates workflow input directly")

    def test_workflow_input_moved_to_env_is_allowed(self):
        workflow = """name: good
on:
  workflow_dispatch:
    inputs:
      payload:
        required: false
permissions:
  contents: read
jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - env:
          PAYLOAD: ${{ github.event.inputs.payload }}
        run: python tool.py --payload "$PAYLOAD"
"""
        self.validate(workflow)

    def test_self_hosted_pull_request_without_guard_is_blocked(self):
        workflow = """name: bad
on: pull_request
permissions:
  contents: read
jobs:
  laptop:
    runs-on: [self-hosted, Windows]
    steps:
      - uses: actions/checkout@v4
      - run: python main.py
"""
        self.assertBlocked(workflow, "self-hosted job laptop may execute pull_request code")

    def test_self_hosted_owner_same_repo_guard_is_allowed(self):
        workflow = """name: good
on: pull_request
permissions:
  contents: read
jobs:
  laptop:
    if: github.event.pull_request.head.repo.full_name == github.repository && github.actor == github.repository_owner
    runs-on: [self-hosted, Windows]
    steps:
      - uses: actions/checkout@v4
      - run: python main.py
"""
        self.validate(workflow)

    def test_self_hosted_explicit_no_pr_guard_is_allowed(self):
        workflow = """name: good
on:
  pull_request:
  workflow_dispatch:
permissions:
  contents: read
jobs:
  laptop:
    if: github.event_name != 'pull_request'
    runs-on: [self-hosted, Windows]
    steps:
      - run: python main.py
"""
        self.validate(workflow)

    def test_job_level_secret_on_pull_request_is_blocked(self):
        workflow = """name: bad
on: pull_request
permissions:
  contents: read
jobs:
  audit:
    runs-on: ubuntu-latest
    env:
      API_KEY: ${{ secrets.API_KEY }}
    steps:
      - uses: actions/checkout@v4
      - run: python main.py
"""
        self.assertBlocked(workflow, "exposes a secret to pull_request code")

    def test_step_secret_on_pull_request_run_is_blocked(self):
        workflow = """name: bad
on: pull_request
permissions:
  contents: read
jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - env:
          API_KEY: ${{ secrets.API_KEY }}
        run: python main.py
"""
        self.assertBlocked(workflow, "exposes a secret to pull_request run code")

    def test_step_secret_guarded_to_workflow_dispatch_is_allowed(self):
        workflow = """name: good
on:
  pull_request:
  workflow_dispatch:
permissions:
  contents: read
jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - if: github.event_name == 'workflow_dispatch'
        env:
          API_KEY: ${{ secrets.API_KEY }}
        run: python main.py
"""
        self.validate(workflow)


if __name__ == "__main__":
    unittest.main()
