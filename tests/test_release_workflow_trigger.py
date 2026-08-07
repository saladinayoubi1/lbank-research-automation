import re
import unittest
from pathlib import Path


WORKFLOW = Path('.github/workflows/release-readiness.yml')


class ReleaseWorkflowTriggerTests(unittest.TestCase):
    def test_main_push_is_not_path_filtered(self):
        text = WORKFLOW.read_text(encoding='utf-8')
        match = re.search(r"(?ms)^  push:\n(?P<body>.*?)(?=^  pull_request:)", text)
        self.assertIsNotNone(match, 'release readiness must define a push trigger')
        body = match.group('body')
        self.assertIn('branches: [main]', body)
        self.assertNotIn('paths:', body, 'every main SHA must receive release-readiness CI evidence')

    def test_pull_request_trigger_remains_scoped(self):
        text = WORKFLOW.read_text(encoding='utf-8')
        match = re.search(r"(?ms)^  pull_request:\n(?P<body>.*?)(?=^  workflow_dispatch:)", text)
        self.assertIsNotNone(match)
        self.assertIn('paths:', match.group('body'))


if __name__ == '__main__':
    unittest.main()
