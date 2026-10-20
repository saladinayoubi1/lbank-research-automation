"""A successful technical report must mean complete execution without skips."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


RUNNER = Path(__file__).resolve().parents[1] / "research/run_ctrend_causal_validation_v1.py"


class ValidationGateTests(unittest.TestCase):
    def run_fixture(self, count, skip=False, expected_failure=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "research").mkdir()
            (root / "tests").mkdir()
            runner = root / "research" / RUNNER.name
            shutil.copyfile(RUNNER, runner)
            lines = ["import unittest", "class Fixture(unittest.TestCase):"]
            for number in range(count):
                body = "self.skipTest('missing optional dependency')" if skip and number == 0 else "pass"
                if expected_failure and number == 0:
                    lines += ["    @unittest.expectedFailure"]
                    body = "self.fail('known technical failure')"
                lines += [f"    def test_{number:02d}(self):", f"        {body}"]
            (root / "tests/test_nexus_ctrend_causal_fixture.py").write_text(
                "\n".join(lines) + "\n", encoding="utf-8"
            )
            report = root / "report.json"
            process = subprocess.run(
                [sys.executable, str(runner), "--report", str(report)],
                capture_output=True, text=True, timeout=30, cwd=root,
            )
            return process.returncode, json.loads(report.read_text(encoding="utf-8"))

    def test_skipped_test_cannot_certify_complete_execution(self):
        code, report = self.run_fixture(49, skip=True)
        self.assertEqual(report["tests_run"], 49)
        self.assertEqual(report["skipped"], 1)
        self.assertFalse(report["success"])
        self.assertEqual(code, 1)

    def test_incomplete_discovery_cannot_certify_execution(self):
        code, report = self.run_fixture(48)
        self.assertEqual(report["tests_run"], 48)
        self.assertEqual(report["skipped"], 0)
        self.assertFalse(report["success"])
        self.assertEqual(code, 1)

    def test_complete_execution_can_pass(self):
        code, report = self.run_fixture(49)
        self.assertEqual(report["tests_run"], 49)
        self.assertEqual(report["skipped"], 0)
        self.assertTrue(report["success"])
        self.assertEqual(code, 0)

    def test_expected_failure_cannot_certify_execution(self):
        code, report = self.run_fixture(49, expected_failure=True)
        self.assertEqual(report["expected_failures"], 1)
        self.assertFalse(report["success"])
        self.assertEqual(code, 1)
