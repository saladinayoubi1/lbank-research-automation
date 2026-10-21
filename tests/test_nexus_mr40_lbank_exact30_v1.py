import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/evidence/lbank-mr40-exact30-20261021"
spec = importlib.util.spec_from_file_location("lbank_exact30_tests", ROOT / "research/nexus_mr40_lbank_exact30_v1.py")
study = importlib.util.module_from_spec(spec)
spec.loader.exec_module(study)


class LBankExact30Tests(unittest.TestCase):
    def test_recorded_public_history_replays_exactly_without_network(self):
        expected = json.loads((EVIDENCE / "results.json").read_bytes())
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            actual = study.run(ROOT, Path(tmp) / "replay", EVIDENCE)
        self.assertEqual(study.canonical(actual), study.canonical(expected))

    def test_missing_or_duplicate_bar_cannot_enter_backtest(self):
        code = study.load_sources(ROOT)
        body = json.loads((EVIDENCE / "lbank_kline_response.json").read_bytes(), parse_float=str)
        native = code["validator"](body["data"])
        with self.assertRaisesRegex(ValueError, "schema_failure"):
            code["validator"](native + [native[0]])
        rows = [[r[0]*1000, *r[1:]] for r in native[:-1]]
        del rows[-80]
        policy = json.loads((ROOT / "research/mean_reversion_40_m2_lbank_exact30_v1.json").read_bytes())
        with self.assertRaisesRegex(ValueError, "non-contiguous"):
            study.replay(rows, policy, code)

    def test_changed_recorded_response_is_rejected_before_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "recorded"
            source.mkdir()
            (source / "source_receipt.json").write_bytes((EVIDENCE / "source_receipt.json").read_bytes())
            (source / "lbank_kline_response.json").write_bytes((EVIDENCE / "lbank_kline_response.json").read_bytes() + b" ")
            with self.assertRaisesRegex(ValueError, "digest_mismatch"):
                study.run(ROOT, root / "output", source)


if __name__ == "__main__":
    unittest.main()
