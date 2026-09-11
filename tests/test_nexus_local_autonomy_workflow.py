from __future__ import annotations

import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "nexus_local_autonomy.yml"


class LocalAutonomyWorkflowContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def test_physical_runner_uses_current_run_digest_pinned_source_artifact(self) -> None:
        self.assertIn("source-prep:", self.text)
        self.assertIn("git archive --format=zip", self.text)
        self.assertIn("archive_sha256:", self.text)
        self.assertIn("nexus-local-autonomy-source-${{ github.run_id }}", self.text)
        self.assertIn(
            "actions/download-artifact@d3f86a106a0bac45b974a628896c90dbdf5c8093",
            self.text,
        )
        self.assertIn("EXPECTED_SOURCE_ARCHIVE_SHA256", self.text)
        self.assertIn("Get-FileHash", self.text)
        self.assertIn("exact_source_mode=digest-pinned-current-run-artifact", self.text)

    def test_physical_runner_does_not_fetch_repository_over_git(self) -> None:
        self.assertNotIn("fetch --no-tags", self.text)
        self.assertNotIn("bounded-http11-fetch", self.text)
        self.assertNotIn("git checkout --detach", self.text)
        self.assertNotIn("git remote set-url", self.text)

    def test_worker_authority_and_execution_plane_remain_bounded(self) -> None:
        self.assertIn("runs-on: [self-hosted, Windows, X64, nexus-local]", self.text)
        self.assertIn("NEXUS_WORKER_MAX_SECONDS: '240'", self.text)
        self.assertIn("NEXUS_DEEPSEEK_PAID_ROUTING_ALLOWED: '0'", self.text)
        self.assertIn("github.event_name != 'pull_request'", self.text)
        self.assertIn("github.actor == github.repository_owner", self.text)
        self.assertIn("permissions:\n  contents: read", self.text)

    def test_source_binding_is_fail_closed_before_execution(self) -> None:
        self.assertIn("Exact source commit mismatch", self.text)
        self.assertIn("Exact source archive digest mismatch", self.text)
        self.assertIn("Restored exact source is incomplete", self.text)
        self.assertLess(
            self.text.index("Verify and restore exact source artifact"),
            self.text.index("Run bounded autonomous queue"),
        )


if __name__ == "__main__":
    unittest.main()
