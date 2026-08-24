from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from nexus_ai_room_boundary import AIRoomBoundaryError, validate_ai_room_boundary


class NexusAIRoomBoundaryTests(unittest.TestCase):
    def test_current_ai_room_respects_authority_boundary(self) -> None:
        report = validate_ai_room_boundary()
        self.assertTrue(report["ok"])
        self.assertFalse(report["live_trading_authority"])

    def test_direct_paper_mutator_import_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ai_room.py"
            path.write_text("from paper_execution import execute_paper_command\n", encoding="utf-8")
            with self.assertRaisesRegex(AIRoomBoundaryError, "state-mutating"):
                validate_ai_room_boundary(path)

    def test_direct_strategy_lifecycle_import_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ai_room.py"
            path.write_text("import strategy_lifecycle\n", encoding="utf-8")
            with self.assertRaisesRegex(AIRoomBoundaryError, "state-mutating"):
                validate_ai_room_boundary(path)


if __name__ == "__main__":
    unittest.main()
