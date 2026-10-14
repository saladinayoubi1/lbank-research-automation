from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from unittest.mock import patch

from scripts.nexus_multipair_feedback_run_selection import (
    PHYSICAL_JOBS,
    PROOF_PREFIX,
    WORKFLOW_NAME,
    WORKFLOW_PATH,
    select_discovery_proof_run,
)


SOURCE = "ed2f16b6aabe7d0d97562fd64bb4e3609dc51b32"
WORKFLOW = Path(".github/workflows/nexus_multipair_paper_boundary_discovery_feedback.yml")


def run(run_id=38348220449, event="push"):
    return dict(id=run_id, name=WORKFLOW_NAME, path=WORKFLOW_PATH, head_branch="main",
                head_sha=SOURCE, status="completed", conclusion="success", event=event)


def jobs(physical="skipped"):
    rows = [dict(name="contract-test", status="completed", conclusion="success")]
    rows.extend(dict(name=name, status="completed", conclusion=physical) for name in PHYSICAL_JOBS)
    return dict(total_count=len(rows), jobs=rows)


def artifacts(run_id=38348220449):
    row = dict(id=1234, name=PROOF_PREFIX + SOURCE, expired=False, size_in_bytes=2048,
               digest="sha256:" + "b" * 64,
               workflow_run=dict(id=run_id, head_sha=SOURCE, head_branch="main"))
    return dict(total_count=1, artifacts=[row])


EMPTY_ARTIFACTS = dict(total_count=0, artifacts=[])


class DiscoveryRunSelectionTests(unittest.TestCase):
    def select(self, job_page=None, artifact_page=None, runs=None):
        return select_discovery_proof_run(
            [run()] if runs is None else runs, SOURCE,
            lambda _: jobs() if job_page is None else job_page,
            lambda _: EMPTY_ARTIFACTS if artifact_page is None else artifact_page,
        )

    def test_observed_successful_source_push_without_proof_waits(self):
        result = self.select()
        self.assertEqual((result.run_id, result.reason), (0, "CONTRACT_ONLY_NO_PHYSICAL_PROOF"))
        self.assertEqual(result.skipped_run_ids, (38348220449,))

    def test_eligible_physical_run_is_selected(self):
        result = self.select(jobs("success"), artifacts(), [run(event="workflow_dispatch")])
        self.assertEqual((result.run_id, result.reason), (38348220449, "ELIGIBLE_PHYSICAL_PROOF"))

    def test_contract_only_latest_does_not_hide_older_exact_physical_proof(self):
        selected = select_discovery_proof_run(
            [run(22), run(11, "workflow_dispatch")], SOURCE,
            lambda i: jobs("success" if i == 11 else "skipped"),
            lambda i: artifacts(11) if i == 11 else EMPTY_ARTIFACTS,
        )
        self.assertEqual((selected.run_id, selected.skipped_run_ids), (11, (22,)))

    def test_no_exact_counterpart_waits(self):
        self.assertEqual(self.select(runs=[]).reason, "NO_EXACT_SUCCESSFUL_DISCOVERY_RUN")

    def test_partial_physical_path_with_skipped_publisher_waits(self):
        page = jobs()
        page["jobs"][1]["conclusion"] = "success"
        self.assertEqual(self.select(page).reason, "WAITING_FOR_PHYSICAL_PROOF")

    def test_successful_publisher_missing_proof_fails(self):
        with self.assertRaisesRegex(ValueError, "expected one exact artifact"):
            self.select(jobs("success"))

    def test_proof_without_successful_publisher_fails(self):
        with self.assertRaisesRegex(ValueError, "without a successful publisher"):
            self.select(artifact_page=artifacts())

    def test_incomplete_job_listing_cannot_claim_contract_only(self):
        page = jobs()
        page["jobs"].pop()
        with self.assertRaisesRegex(ValueError, "incomplete"):
            self.select(page)

    def test_missing_duplicate_unfinished_or_failed_jobs_fail(self):
        for change in ("missing", "duplicate", "unfinished", "failed"):
            with self.subTest(change=change):
                page = jobs()
                if change == "missing":
                    page["jobs"].pop()
                    page["total_count"] -= 1
                elif change == "duplicate":
                    page["jobs"][-1]["name"] = page["jobs"][-2]["name"]
                elif change == "unfinished":
                    page["jobs"][-1]["status"] = "in_progress"
                else:
                    page["jobs"][-1]["conclusion"] = "failure"
                with self.assertRaises(ValueError):
                    self.select(page)

    def test_successful_publisher_cannot_skip_physical_work(self):
        page = jobs("success")
        page["jobs"][1]["conclusion"] = "skipped"
        with self.assertRaisesRegex(ValueError, "complete physical path"):
            self.select(page, artifacts())

    def test_invalid_run_identity_fails_closed(self):
        mutations = dict(id=True, name="other", path="other.yml", head_branch="feature",
                         head_sha="a" * 40, status="in_progress", conclusion="failure", event="pull_request")
        for key, value in mutations.items():
            with self.subTest(key=key):
                candidate = run()
                candidate[key] = value
                with self.assertRaisesRegex(ValueError, "identity mismatch"):
                    self.select(runs=[candidate])

    def test_wrong_proof_source_name_fails_even_when_publisher_skipped(self):
        page = artifacts()
        page["artifacts"][0]["name"] = PROOF_PREFIX + "a" * 40
        with self.assertRaisesRegex(ValueError, "source name mismatch"):
            self.select(artifact_page=page)

    def test_invalid_artifact_identity_digest_size_and_expiry_fail(self):
        changes = (
            ("id", True), ("digest", "sha256:bad"), ("size_in_bytes", 0),
            ("size_in_bytes", 250 * 1024 * 1024 + 1), ("size_in_bytes", True),
            ("expired", True), ("expired", None),
            ("workflow_run", dict(id=999, head_sha=SOURCE, head_branch="main")),
            ("workflow_run", dict(id=38348220449, head_sha="a" * 40, head_branch="main")),
            ("workflow_run", dict(id=38348220449, head_sha=SOURCE, head_branch="feature")),
        )
        for key, value in changes:
            with self.subTest(key=key, value=value):
                page = artifacts()
                page["artifacts"][0][key] = value
                with self.assertRaises(ValueError):
                    self.select(jobs("success"), page)

    def test_duplicate_or_incomplete_artifact_listing_fails(self):
        for page in (
            dict(total_count=2, artifacts=artifacts()["artifacts"]),
            dict(total_count=2, artifacts=deepcopy(artifacts()["artifacts"]) * 2),
        ):
            with self.subTest(page=page), self.assertRaises(ValueError):
                self.select(jobs("success"), page)

    def test_corrupt_newer_run_is_not_hidden_by_older_valid_proof(self):
        with self.assertRaisesRegex(ValueError, "expected one exact artifact"):
            select_discovery_proof_run(
                [run(22), run(11)], SOURCE, lambda _: jobs("success"),
                lambda i: EMPTY_ARTIFACTS if i == 22 else artifacts(11),
            )

    def test_metadata_reader_error_does_not_become_not_ready(self):
        def unavailable(_):
            raise RuntimeError("metadata unavailable")
        with self.assertRaisesRegex(RuntimeError, "unavailable"):
            select_discovery_proof_run([run()], SOURCE, unavailable, lambda _: EMPTY_ARTIFACTS)


class WorkflowRunResolutionTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("bash"), "feedback shell executes on Ubuntu")
    def test_selector_error_stops_actual_shell_before_pairing(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        start = text.index('          pair_ids="$(SOURCE_SHA="$source_sha" python')
        stop = text.index('          {\n            echo "source_sha=$source_sha"', start)
        shell = textwrap.dedent(text[start:stop])
        result = subprocess.run(
            ["bash", "-c", "set -euo pipefail\nsource_sha=unused\npython() { return 23; }\n" + shell + "echo UNSAFE_PAIRING_CONTINUED"],
            text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, 23)
        self.assertNotIn("UNSAFE_PAIRING_CONTINUED", result.stdout)

    def execute_resolution(self, candidates, pages):
        text = WORKFLOW.read_text(encoding="utf-8")
        start = text.index('$(SOURCE_SHA="$source_sha" python - <<\'PY\'')
        code = textwrap.dedent(text[start:].split("\n", 1)[1].split("\n          PY", 1)[0])
        stdout, stderr = io.StringIO(), io.StringIO()
        calls = []

        def read_metadata(args, *, text):
            self.assertTrue(text)
            self.assertEqual(args[:4], ["gh", "api", "-H", "Accept: application/vnd.github+json"])
            url = args[-1]
            self.assertTrue(url.startswith("repos/owner/repo/actions/runs/"))
            run_id = int(url.split("/runs/", 1)[1].split("/", 1)[0])
            resource = "jobs" if url.endswith("jobs?filter=latest&per_page=100") else "artifacts"
            self.assertIn(url.rsplit("/", 1)[1], {"jobs?filter=latest&per_page=100", "artifacts?per_page=100"})
            calls.append((run_id, resource))
            return json.dumps(pages[(run_id, resource)])

        old_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as temp:
            try:
                os.chdir(temp)
                Path("build").mkdir()
                paper = dict(id=33, name="NEXUS persistent Paper trading loop",
                             path=".github/workflows/nexus_persistent_paper_trading_loop.yml",
                             head_branch="main", head_sha=SOURCE, status="completed", conclusion="success")
                Path("build/paper-runs.json").write_text(json.dumps(dict(workflow_runs=[paper])))
                Path("build/discovery-runs.json").write_text(json.dumps(dict(workflow_runs=candidates)))
                with patch.dict(os.environ, SOURCE_SHA=SOURCE, GITHUB_REPOSITORY="owner/repo"), \
                     patch("subprocess.check_output", side_effect=read_metadata), \
                     redirect_stdout(stdout), redirect_stderr(stderr):
                    exec(compile(code, "<exact workflow run resolution>", "exec"), {})
            finally:
                os.chdir(old_cwd)
        return stdout.getvalue().strip().split(), stderr.getvalue(), calls

    def test_actual_workflow_contract_only_run_does_not_pair(self):
        run_id = 38348220449
        result, diagnostic, calls = self.execute_resolution(
            [run(run_id)], {(run_id, "jobs"): jobs(), (run_id, "artifacts"): EMPTY_ARTIFACTS})
        self.assertEqual(result, ["33", "0"])
        self.assertIn("CONTRACT_ONLY_NO_PHYSICAL_PROOF", diagnostic)
        self.assertEqual(calls, [(run_id, "jobs"), (run_id, "artifacts")])

    def test_actual_workflow_selects_only_eligible_exact_counterpart(self):
        result, _, _ = self.execute_resolution(
            [run(22), run(11, "workflow_dispatch")],
            {(22, "jobs"): jobs(), (22, "artifacts"): EMPTY_ARTIFACTS,
             (11, "jobs"): jobs("success"), (11, "artifacts"): artifacts(11)})
        self.assertEqual(result, ["33", "11"])

    def test_actual_workflow_does_not_hide_missing_physical_proof(self):
        with self.assertRaisesRegex(ValueError, "expected one exact artifact"):
            self.execute_resolution(
                [run(11, "workflow_dispatch")],
                {(11, "jobs"): jobs("success"), (11, "artifacts"): EMPTY_ARTIFACTS})


if __name__ == "__main__":
    unittest.main()
