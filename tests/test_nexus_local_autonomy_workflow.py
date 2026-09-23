from __future__ import annotations

import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "nexus_local_autonomy.yml"


class LocalAutonomyWorkflowContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def test_physical_runner_uses_anonymous_exact_sha_http11_source(self) -> None:
        self.assertIn("source-prep:", self.text)
        self.assertIn("Verify exact hosted source binding", self.text)
        self.assertIn('test "$actual" = "$GITHUB_SHA"', self.text)
        self.assertNotIn("actions/upload-artifact@", self.text[self.text.index("  source-prep:"):self.text.index("  local-worker:")])
        self.assertNotIn("actions/download-artifact@", self.text)
        self.assertIn("Prepare anonymous exact source with bounded HTTP/1.1 retries", self.text)
        self.assertIn("https://github.com/$env:GITHUB_REPOSITORY.git", self.text)
        self.assertIn("credential", self.text)
        self.assertIn("http.version=HTTP/1.1", self.text)
        self.assertIn("$fetchMaxAttempts = 3", self.text)
        self.assertIn("fetch --no-tags --prune --depth=1 origin $env:GITHUB_SHA", self.text)
        self.assertIn("checkout --detach --force FETCH_HEAD", self.text)
        self.assertIn("exact_source_mode=anonymous-exact-sha-http11", self.text)

    def test_physical_runner_source_fetch_is_anonymous_and_fail_closed(self) -> None:
        self.assertIn("git -C $workspace config --local --unset-all http.https://github.com/.extraheader", self.text)
        self.assertIn("Exact autonomy source fetch failed", self.text)
        self.assertIn("Exact trigger SHA mismatch", self.text)
        self.assertNotIn("x-access-token", self.text)
        self.assertNotIn("Authorization: Bearer", self.text)
        self.assertNotIn("git remote set-url", self.text)

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
            self.text.index("Prepare anonymous exact source with bounded HTTP/1.1 retries"),
            self.text.index("Run bounded autonomous queue"),
        )


if __name__ == "__main__":
    unittest.main()
