import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("mr40_newday_test", ROOT / "research/nexus_mr40_momentum30_newday_v1.py")
study = importlib.util.module_from_spec(spec)
spec.loader.exec_module(study)


class NewDayAccountTests(unittest.TestCase):
    def test_closed_bar_decision_and_terminal_fee(self):
        rows = [[i * study.STEP, "100", "100", "100", "100", "1"] for i in range(3)]
        marks, fills = study.decimal_500(rows, [0, 1, 0], 1, 10, 5)
        self.assertEqual(marks[0], 500)
        self.assertEqual(fills, [(2 * study.STEP, "buy"), (3 * study.STEP, "sell")])
        expected = 500 / (1.001 * 1.0005) * 0.9995 * 0.999
        self.assertAlmostEqual(marks[-1], expected, places=10)

    def test_stress_costs_reduce_same_trade(self):
        rows = [[i * study.STEP, "100", "101", "99", "100", "1"] for i in range(4)]
        normal, fills = study.decimal_500(rows, [1, 1, 0, 0], 1, 10, 5)
        stress, stress_fills = study.decimal_500(rows, [1, 1, 0, 0], 1, 25, 15)
        self.assertEqual(fills, stress_fills)
        self.assertLess(stress[-1], normal[-1])
        self.assertEqual(fills[-1], (3 * study.STEP, "sell"))

    def test_reject_digest_tampering(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "input.json"
            value = {"rows": [[0, "100"]]}
            expected = study.digest(value)
            value["input_digest"] = expected
            path.write_text(json.dumps(value))
            study.verified_json(path, "input_digest", expected)
            value["rows"][0][1] = "101"
            path.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError, "substitution"):
                study.verified_json(path, "input_digest", expected)

    def test_frozen_source_identity(self):
        loaded = study.modules(ROOT)
        self.assertEqual(set(loaded), {"core", "gate", "intake"})
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)
            relative, _ = study.PINNED["core"]
            target = source / relative
            target.parent.mkdir(parents=True)
            target.write_text((ROOT / relative).read_text() + "\n")
            with self.assertRaisesRegex(ValueError, "substitution"):
                study.modules(source)


if __name__ == "__main__":
    unittest.main()
