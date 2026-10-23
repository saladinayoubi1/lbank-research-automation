"""Locked historical 47-entry diagnostic integrity tests. No market requests."""
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from research import nexus_mr40_cross_evidence_47_entry_diagnosis_v1 as m


class CrossEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        needed = [cls.root / "research" / m.PROTOCOL]
        needed += [cls.root / "results" / name for name in m.NAMES.values()]
        needed += [cls.root / "results" / m.OUTPUT]
        if not all(p.is_file() for p in needed):
            raise unittest.SkipTest("SHA-pinned market evidence exists only on research laptop")
        cls.protocol, cls.sources = m.load_locked(cls.root)

    def test_pinned_source_join_is_deterministic(self):
        a = m.inspect(self.root)
        b = m.inspect(self.root)
        self.assertEqual(a["digest"], b["digest"])
        self.assertEqual(a["summary"]["train"]["positions"], 25)
        self.assertEqual(a["summary"]["evaluation"]["positions"], 22)
        self.assertEqual(a["summary"]["all_47"]["unarmed_losers"], 8)
        self.assertEqual(a["decision"], "DESCRIPTIVE_ONLY_NO_PROMOTE")

    def test_source_sha256_must_match_frozen_protocol(self):
        with TemporaryDirectory() as t:
            tmp = Path(t)
            (tmp / "research").mkdir()
            (tmp / "results").mkdir()
            p = self.root / "research" / m.PROTOCOL
            (tmp / "research" / m.PROTOCOL).write_bytes(p.read_bytes())
            for name in m.NAMES.values():
                content = (self.root / "results" / name).read_bytes()
                if name == "entry_volume_audit.json":
                    content += b" "
                (tmp / "results" / name).write_bytes(content)
            with self.assertRaisesRegex(ValueError, "input_sha256_drift_volume"):
                m.load_locked(tmp)

    def _mutate(self, change, expected):
        sources = copy.deepcopy(self.sources)
        change(sources)
        with patch.object(m, "load_locked", return_value=(self.protocol, sources)):
            with self.assertRaisesRegex(ValueError, expected):
                m.inspect(self.root)

    def test_signal_index_tamper_rejected(self):
        self._mutate(
            lambda s: s["volume"]["windows"]["train"]["entries"][0].__setitem__(
                "signal_index", -1
            ),
            "cross_study_signal_identity_drift"
        )

    def test_pnl_tamper_rejected(self):
        self._mutate(
            lambda s: s["volume"]["windows"]["evaluation"]["entries"][0].__setitem__(
                "realized_pnl_usdt", 999999
            ),
            "realized_pnl_cross_study_drift"
        )

    def test_duplicate_adverse_entry_rejected(self):
        self._mutate(
            lambda s: s["adverse"]["per_position"][1].__setitem__(
                "entry_signal_index", s["adverse"]["per_position"][0]["entry_signal_index"]
            ),
            "duplicate_adverse_signal"
        )

    def test_unarmed_winner_spoof_rejected(self):
        self._mutate(
            lambda s: s["unarmed"]["windows"]["train"]["episodes"][0].__setitem__(
                "entry_open_utc",
                datetime.fromtimestamp(
                    next(r["entry_utc_ms"] for r in
                         s["structure"]["windows"]["train"]["entry_records"]
                         if r["label"] == "winner") / 1000, timezone.utc
                ).isoformat()
            ),
            "unarmed_loser_not_a_baseline_loser"
        )

    def test_naive_local_time_rejected(self):
        with self.assertRaisesRegex(ValueError, "utc_time_missing_offset"):
            m.utc_ms("2026-10-23T12:00:00")

    def test_preexisting_result_not_overwritten(self):
        out = self.root / "results" / m.OUTPUT
        self.assertTrue(out.exists())
        old = m.sha(out)
        with patch("sys.argv", ["research", "--root", str(self.root)]):
            with self.assertRaises(FileExistsError):
                m.main()
        self.assertEqual(m.sha(out), old)


class PureInvariantTests(unittest.TestCase):
    def test_time_requires_utc_offset(self):
        with self.assertRaisesRegex(ValueError, "utc_time_missing_offset"):
            m.utc_ms("2026-10-23T12:00:00")

    def test_nonduplicate_identity_enforced(self):
        with self.assertRaisesRegex(ValueError, "duplicate_signal"):
            m.unique_index([{"id": 3}, {"id": 3}], lambda x: x["id"], "signal")

    def test_accounting_rounded_comparison_is_strict(self):
        self.assertTrue(m.compatible_pnl("1.000000001", "1.0"))
        self.assertFalse(m.compatible_pnl("1.000001", "1.0"))

    def test_canonical_digest_order_independent(self):
        self.assertEqual(m.canon({"a": 1, "b": 2}), m.canon({"b": 2, "a": 1}))

    def test_raced_file_exists_never_deletes_other_writers_file(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            outdir = root / "results"
            outdir.mkdir()
            target = outdir / m.OUTPUT
            target.write_text("KEEP", encoding="utf-8")
            original = target.read_bytes()
            with patch.object(m, "inspect", return_value={"schema": "dummy"}), \
                 patch.object(Path, "exists", return_value=False), \
                 patch("sys.argv", ["test", "--root", str(root)]):
                with self.assertRaises(FileExistsError):
                    m.main()
            self.assertEqual(target.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
