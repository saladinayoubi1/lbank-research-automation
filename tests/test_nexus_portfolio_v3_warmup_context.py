"""Synthetic context/causality checks; no economic study or source admission."""
import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

import numpy as np
import pandas as pd

from scripts import nexus_portfolio_v3_warmup_context as context


def fixture():
    ts = pd.Series(pd.date_range(context.ANCHOR, context.CUTOFF, freq="4h", inclusive="left"))
    t = np.arange(len(ts))
    close = np.column_stack([100 * np.exp(.00003 * t + .03 * np.sin(t / 17)),
                             80 * np.exp(.00002 * t + .02 * np.cos(t / 23))])
    full = {"timestamps": ts, "symbols": list(context.SYMBOLS),
            "open": close * .999, "high": close * 1.01,
            "low": close * .99, "close": close}
    n = int((ts < context.SEAM).sum())
    original = {k: (v[:n].copy() if k != "symbols" else list(v)) for k, v in full.items()}
    bars = {}
    for j, symbol in enumerate(context.EXCHANGE):
        bars[symbol] = [{"timestamp": ts.iloc[i].isoformat(),
                         **{k: full[k][i, j] for k in context.PRICE_KEYS}, "volume": 10.}
                        for i in range(n, len(ts))]
    return original, bars


class ContextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan, cls.spec = context.checked_contract(context.ROOT)

    def test_locked_contract_preserves_candidate_window_and_denied_authorities(self):
        self.assertEqual(self.spec["candidate_id"], "b4e4a2c33304aec1")
        self.assertEqual(self.plan["joined_rows_per_symbol"], 8508)
        for key in ("future_source_authorized", "financial_dispatch_authorized",
                    "strategy_backtest_authorized", "paper_eligible", "live_enabled"):
            self.assertIs(self.plan[key], False)
        self.assertEqual(self.spec["future_study"]["end_exclusive_utc"], "2027-01-17T00:00:00Z")

    def test_altered_plan_handoff_or_original_engine_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = [context.PLAN, context.HANDOFF,
                     *self.spec["code_and_contract_sha256_lf_normalized"]]
            for p in paths:
                (root / p).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(context.ROOT / p, root / p)
            context.checked_contract(root)
            for p in (context.PLAN, context.HANDOFF, "bybit_portfolio_search_v3.py"):
                with self.subTest(path=p):
                    original = (root / p).read_bytes()
                    if p.endswith(".json"):
                        data = json.loads(original)
                        data["live_enabled"] = True
                        (root / p).write_text(json.dumps(data), encoding="utf-8")
                    else:
                        (root / p).write_bytes(original + b"\n# changed\n")
                    with self.assertRaises(context.ContextError):
                        context.checked_contract(root)
                    (root / p).write_bytes(original)

    def test_rehashed_but_unapproved_qa_receipt_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "receipt.json"
            body = {"synthetic_unit_fixture": True, "value": 1}
            expected = context.digest(body)
            path.write_text(json.dumps({**body, "digest": expected}))
            context.checked_receipt(path, expected)
            body["value"] = 2
            path.write_text(json.dumps({**body, "digest": context.digest(body)}))
            with self.assertRaises(context.ContextError):
                context.checked_receipt(path, expected)

    def test_source_byte_changes_cannot_inherit_old_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for folder in ("raw", "receipts", "archive"):
                (root / folder).mkdir()
            raw = root / "raw/BTCUSDT_2026-08-01.csv.gz"
            receipt = root / "receipts/BTCUSDT_2026-08-01.json"
            original = root / "archive/source.parquet"
            raw.write_bytes(b"synthetic previously checked day")
            receipt.write_bytes(b'{"synthetic_unit_fixture":true}')
            original.write_bytes(b"synthetic original source")
            original_hashes = {"source.parquet": context.sha_file(original)}
            summary = {"files": [{"symbol": "BTCUSDT", "date": "2026-08-01",
                                   "raw_file_sha256": context.sha_file(raw),
                                   "receipt_sha256": context.sha_file(receipt)}]}
            summary["digest"] = context.digest(summary)
            qa = {"capture_digest": summary["digest"],
                  "original_archive_six_sha256_rechecked": original_hashes}
            qa["digest"] = context.digest(qa)
            (root / "capture-summary.json").write_text(json.dumps(summary))
            (root / "independent-source-qa.json").write_text(json.dumps(qa))
            plan = {"capture_digest": summary["digest"], "independent_warmup_qa_digest": qa["digest"]}
            with mock.patch.object(context.source_qa, "ORIGINAL_SHA256", original_hashes):
                context.attest_sources(root, root / "archive", plan)
                for path in (raw, receipt, original):
                    with self.subTest(path=path.name):
                        previous = path.read_bytes()
                        path.write_bytes(b"modified")
                        with self.assertRaises(context.ContextError):
                            context.attest_sources(root, root / "archive", plan)
                        path.write_bytes(previous)

    def test_join_keeps_original_prices_and_exact_warmup_grid(self):
        original, bars = fixture()
        joined = context.join_warmup(original, bars)
        self.assertEqual(len(joined["timestamps"]), 8508)
        self.assertEqual(joined["timestamps"].iloc[8034], context.SEAM)
        self.assertEqual(joined["timestamps"].iloc[-1] + pd.Timedelta(hours=4), context.CUTOFF)
        for key in context.PRICE_KEYS:
            np.testing.assert_array_equal(joined[key][:8034], original[key])

    def test_missing_extra_naive_or_future_warmup_bars_are_rejected(self):
        original, bars = fixture()
        for kind in ("missing", "duplicate", "future", "naive", "bad_ohlc", "nan", "zero_volume"):
            with self.subTest(kind=kind):
                changed = copy.deepcopy(bars)
                rows = changed["BTCUSDT"]
                if kind == "missing": rows.pop()
                elif kind == "duplicate": rows[1] = rows[0].copy()
                elif kind == "future": rows[-1]["timestamp"] = context.CUTOFF.isoformat()
                elif kind == "naive": rows[0]["timestamp"] = "2026-08-01T00:00:00"
                elif kind == "bad_ohlc": rows[0]["high"] = .01
                elif kind == "nan": rows[0]["close"] = float("nan")
                else: rows[0]["volume"] = 0
                with self.assertRaises(context.ContextError):
                    context.join_warmup(original, changed)

    def test_truncated_or_shifted_original_grid_is_rejected(self):
        original, bars = fixture()
        original["timestamps"] = original["timestamps"] + pd.Timedelta(hours=4)
        with self.assertRaises(context.ContextError):
            context.join_warmup(original, bars)

    def test_full_context_preserves_prefix_without_calling_financial_engine(self):
        original, bars = fixture()
        joined = context.join_warmup(original, bars)
        with mock.patch.object(context.engine, "exact_backtest", side_effect=AssertionError("P/L forbidden")):
            report = context.compute_context(original, joined, self.spec)
        self.assertEqual(report["original_feature_target_prefix_rows_preserved"], 8034)
        self.assertEqual(report["last_completed_bar_closed_at_utc"], context.CUTOFF.isoformat())
        self.assertTrue(np.isfinite(report["last_closed_context_not_order_intent"]["score"]).all())

    def test_review_cadence_does_not_reset_at_august_seam(self):
        original, bars = fixture()
        joined = context.join_warmup(original, bars)
        mask = context.engine._candidate_rebalance_mask(8508, self.spec["candidate"])
        self.assertFalse(mask[8034])
        self.assertEqual(np.flatnonzero(mask[8034:])[0], 30)
        report = context.compute_context(original, joined, self.spec)
        self.assertEqual(report["next_review_source_open_utc"], "2026-10-22T00:00:00+00:00")
        self.assertEqual(report["next_review_observed_at_utc"], "2026-10-22T04:00:00+00:00")

    def test_changed_original_prefix_is_rejected_before_features(self):
        original, bars = fixture()
        joined = context.join_warmup(original, bars)
        for key in context.PRICE_KEYS:
            joined[key][100] *= 2
        with self.assertRaises(context.ContextError):
            context.compute_context(original, joined, self.spec)

    def test_prepare_writes_reusable_bundle_without_financial_authority(self):
        original, bars = fixture()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "new"
            with (mock.patch.object(context, "attest_sources", return_value=(
                    {"bars": bars}, {"synthetic_unit_fixture": True})),
                  mock.patch.object(context.engine, "load_market", return_value=original),
                  mock.patch.object(context.engine, "exact_backtest", side_effect=AssertionError("P/L forbidden"))):
                report = context.prepare(Path(tmp), Path(tmp), out)
                with self.assertRaises(context.ContextError):
                    context.prepare(Path(tmp), Path(tmp), out)
            for field in ("future_source_prices_read", "strategy_backtest_performed",
                          "financial_dispatch_authorized", "paper_eligible", "live_enabled"):
                self.assertIs(report[field], False)
            bundle = out / "joined-market-4h.npz"
            restored = context.load_market_bundle(bundle, report["joined_market_bundle_sha256"])
            self.assertEqual(len(restored["timestamps"]), 8508)
            with bundle.open("ab") as handle: handle.write(b"changed")
            with self.assertRaises(context.ContextError):
                context.load_market_bundle(bundle, report["joined_market_bundle_sha256"])


if __name__ == "__main__":
    unittest.main()
