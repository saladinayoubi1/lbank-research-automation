from __future__ import annotations

import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "nexus_local_autonomy.yml"


class LocalAutonomyWorkflowContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def test_physical_runner_uses_exact_codeload_http11_source(self) -> None:
        self.assertIn("source-prep:", self.text)
        self.assertIn("Verify exact hosted source binding", self.text)
        self.assertIn('test "$actual" = "$GITHUB_SHA"', self.text)
        self.assertNotIn("actions/upload-artifact@", self.text[self.text.index("  source-prep:"):self.text.index("  local-worker:")])
        self.assertNotIn("actions/download-artifact@", self.text)
        self.assertIn("Fetch exact autonomy source from codeload", self.text)
        self.assertIn("https://codeload.github.com/$env:GITHUB_REPOSITORY/zip/$env:GITHUB_SHA", self.text)
        self.assertIn("curl.exe --fail --silent --show-error --http1.1", self.text)
        self.assertIn("--connect-timeout 10", self.text)
        self.assertIn("--max-time 60", self.text)
        self.assertIn("--speed-time 20", self.text)
        self.assertIn("--speed-limit 1024", self.text)
        self.assertIn("tar.exe -xf $archive -C $extract", self.text)
        self.assertIn(".nexus-trigger-source", self.text)
        self.assertIn("exact_source_mode=codeload-exact-sha-http11", self.text)
        self.assertNotIn("Expand-Archive", self.text)

    def test_physical_runner_source_fetch_is_bounded_and_fail_closed(self) -> None:
        self.assertIn("Local Autonomy workspace boundary mismatch.", self.text)
        self.assertIn("Exact autonomy codeload source download failed", self.text)
        self.assertIn("Exact autonomy trigger binding mismatch", self.text)
        self.assertIn("for ($attempt = 1; $attempt -le 3; $attempt++)", self.text)
        self.assertNotIn("x-access-token", self.text)
        self.assertNotIn("Authorization: Bearer", self.text)
        self.assertNotIn("git remote set-url", self.text)
        physical = self.text[self.text.index("  local-worker:"):]
        self.assertNotIn("git -C $workspace", physical)
        self.assertNotIn("fetch --no-tags", physical)

    def test_worker_authority_and_execution_plane_remain_bounded(self) -> None:
        self.assertIn("runs-on: [self-hosted, Windows, X64, nexus-local]", self.text)
        self.assertIn("NEXUS_WORKER_MAX_SECONDS: '240'", self.text)
        self.assertIn("NEXUS_DEEPSEEK_PAID_ROUTING_ALLOWED: '0'", self.text)
        self.assertIn("github.event_name != 'pull_request'", self.text)
        self.assertIn("github.actor == github.repository_owner", self.text)
        self.assertIn("permissions:\n  contents: read", self.text)

    def test_source_binding_is_fail_closed_before_execution(self) -> None:
        self.assertIn("Restored exact source is incomplete", self.text)
        self.assertLess(
            self.text.index("Fetch exact autonomy source from codeload"),
            self.text.index("Run bounded autonomous queue"),
        )


if __name__ == "__main__":
    unittest.main()
