from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from nexus_demo_strategy_matrix import (
    _digest,
    load_manifest as load_legacy_manifest,
    load_state as load_legacy_state,
    run_matrix_cycle,
)
from nexus_multipair_demo_strategy_matrix import (
    APPROVED_SYMBOLS,
    MultiPairMatrixError,
    load_manifest,
    load_or_migrate_state,
    run_cycle,
    verify_v2_snapshot,
)


ROOT = Path(__file__).resolve().parents[1]
LEGACY_MANIFEST = ROOT / "config" / "nexus-demo-strategy-matrix-v1.json"
V2_MANIFEST = ROOT / "config" / "nexus-demo-strategy-matrix-v2.json"
SOURCE_SHA = "a" * 40
NOW_MS = 1_800_000_000_000


def _hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _runner(**kwargs):
    symbol = kwargs["symbol"]
    timeframe = kwargs["timeframe"]
    tasks = []
    for family in kwargs["families"]:
        tasks.append({
            "family": family,
            "task_id": f"{symbol}:{timeframe}:{family}",
            "status": "qualification_killed",
            "evidence_digest": _hex(f"{symbol}:{timeframe}:{family}"),
        })
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "paper_only": True,
        "live_trading_authority": False,
        "tasks": tasks,
        "ledger_digest": _hex(f"ledger:{symbol}:{timeframe}"),
    }


def _verifier(ledger):
    return {
        "decision": "pass",
        "verification_digest": _hex(f"verify:{ledger['symbol']}:{ledger['timeframe']}"),
    }


def _analyzer(root, _ledger):
    return {
        "paper_only": True,
        "live_trading_authority": False,
        "status_counts": {},
        "projection_digest": _hex(f"analysis:{root}"),
    }


def _redigest_snapshot(snapshot: dict) -> dict:
    core = dict(snapshot)
    core.pop("snapshot_digest", None)
    return {**core, "snapshot_digest": _digest(core)}


class MultiPairDemoStrategyMatrixTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.v2_manifest = load_manifest(V2_MANIFEST)
        self.legacy_manifest = load_legacy_manifest(LEGACY_MANIFEST)

    def tearDown(self):
        self.temp.cleanup()

    def _write_verified_legacy_state(self) -> Path:
        path = self.root / "matrix-state.json"
        empty = load_legacy_state(path, self.legacy_manifest)
        state, snapshot = run_matrix_cycle(
            manifest=self.legacy_manifest,
            state=empty,
            state_root=self.root,
            source_sha=SOURCE_SHA,
            run_id="41",
            now_ms=NOW_MS,
            runner=_runner,
            verifier=_verifier,
            analyzer=_analyzer,
        )
        self.assertEqual(snapshot["expected_cell_count"], 6)
        self.assertEqual(snapshot["expected_lane_count"], 18)
        path.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
        return path

    def _fresh_v2_cycle(self):
        return run_cycle(
            manifest_path=V2_MANIFEST,
            legacy_manifest_path=LEGACY_MANIFEST,
            state_path=self.root / "fresh-v2-state.json",
            state_root=self.root,
            source_sha=SOURCE_SHA,
            run_id="90",
            now_ms=NOW_MS,
            runner=_runner,
            verifier=_verifier,
            analyzer=_analyzer,
        )

    def test_v2_manifest_is_exact_four_symbol_paper_surface(self):
        self.assertEqual(tuple(self.v2_manifest["symbols"]), APPROVED_SYMBOLS)
        self.assertEqual(len(self.v2_manifest["symbols"]), 4)
        self.assertEqual(len(self.v2_manifest["timeframes"]), 3)
        self.assertEqual(len(self.v2_manifest["families"]), 3)
        self.assertTrue(self.v2_manifest["authority"]["paper_only"])
        self.assertFalse(self.v2_manifest["authority"]["live_trading_authority"])
        self.assertFalse(self.v2_manifest["authority"]["private_credentials_allowed"])
        self.assertFalse(self.v2_manifest["authority"]["automatic_strategy_promotion"])
        self.assertTrue(self.v2_manifest["authority"]["deterministic_risk_final_authority"])

    def test_digest_valid_v1_state_migrates_without_inheriting_new_pair_evidence(self):
        path = self._write_verified_legacy_state()
        migrated, evidence = load_or_migrate_state(
            path,
            self.v2_manifest,
            legacy_manifest_path=LEGACY_MANIFEST,
        )
        self.assertIsNotNone(evidence)
        assert evidence is not None
        self.assertEqual(len(migrated["cells"]), 6)
        self.assertTrue(all(key.startswith(("BTCUSDT:", "ETHUSDT:")) for key in migrated["cells"]))
        self.assertFalse(any(key.startswith(("SOLUSDT:", "XRPUSDT:")) for key in migrated["cells"]))
        self.assertEqual(evidence["preserved_cell_count"], 6)
        self.assertEqual(evidence["new_symbols"], ["SOLUSDT", "XRPUSDT"])
        self.assertEqual(evidence["new_symbol_inherited_cell_count"], 0)
        self.assertFalse(evidence["live_trading_authority"])
        self.assertFalse(evidence["automatic_strategy_promotion"])

    def test_first_v2_cycle_preserves_old_cells_and_executes_only_new_pair_cells_on_same_bar(self):
        path = self._write_verified_legacy_state()
        calls = []

        def runner(**kwargs):
            calls.append((kwargs["symbol"], kwargs["timeframe"]))
            return _runner(**kwargs)

        state, snapshot, migration = run_cycle(
            manifest_path=V2_MANIFEST,
            legacy_manifest_path=LEGACY_MANIFEST,
            state_path=path,
            state_root=self.root,
            source_sha=SOURCE_SHA,
            run_id="42",
            now_ms=NOW_MS,
            runner=runner,
            verifier=_verifier,
            analyzer=_analyzer,
        )
        self.assertIsNotNone(migration)
        self.assertEqual(set(calls), {
            (symbol, timeframe)
            for symbol in ("SOLUSDT", "XRPUSDT")
            for timeframe in ("minute15", "hour1", "hour4")
        })
        self.assertEqual(len(state["cells"]), 12)
        self.assertEqual(snapshot["status"], "VERIFIED")
        self.assertEqual(snapshot["expected_cell_count"], 12)
        self.assertEqual(snapshot["verified_cell_count"], 12)
        self.assertEqual(snapshot["expected_lane_count"], 36)
        self.assertEqual(snapshot["reported_lane_count"], 36)
        self.assertTrue(snapshot["paper_only"])
        self.assertFalse(snapshot["live_trading_authority"])
        self.assertEqual(
            verify_v2_snapshot(snapshot, manifest=self.v2_manifest, state=state)["decision"],
            "pass",
        )

    def test_fresh_v2_state_runs_all_twelve_cells_and_thirty_six_lanes(self):
        state_path = self.root / "new-state.json"
        calls = []

        def runner(**kwargs):
            calls.append((kwargs["symbol"], kwargs["timeframe"]))
            return _runner(**kwargs)

        state, snapshot, migration = run_cycle(
            manifest_path=V2_MANIFEST,
            legacy_manifest_path=LEGACY_MANIFEST,
            state_path=state_path,
            state_root=self.root,
            source_sha=SOURCE_SHA,
            run_id="43",
            now_ms=NOW_MS,
            runner=runner,
            verifier=_verifier,
            analyzer=_analyzer,
        )
        self.assertIsNone(migration)
        self.assertEqual(len(calls), 12)
        self.assertEqual(len(state["cells"]), 12)
        self.assertEqual(snapshot["expected_cell_count"], 12)
        self.assertEqual(snapshot["expected_lane_count"], 36)
        self.assertEqual(snapshot["reported_lane_count"], 36)

    def test_v2_verifier_rejects_shape_rewrite_even_with_recomputed_digest(self):
        state, snapshot, _migration = self._fresh_v2_cycle()
        candidate = deepcopy(snapshot)
        candidate["expected_cell_count"] = 11
        candidate = _redigest_snapshot(candidate)
        result = verify_v2_snapshot(candidate, manifest=self.v2_manifest, state=state)
        self.assertEqual(result["decision"], "reject")
        self.assertFalse(result["checks"]["matrix_shape"])

    def test_v2_verifier_rejects_missing_lane_even_with_recomputed_digest(self):
        state, snapshot, _migration = self._fresh_v2_cycle()
        candidate = deepcopy(snapshot)
        candidate["lanes"] = candidate["lanes"][:-1]
        candidate["reported_lane_count"] = 35
        candidate = _redigest_snapshot(candidate)
        result = verify_v2_snapshot(candidate, manifest=self.v2_manifest, state=state)
        self.assertEqual(result["decision"], "reject")
        self.assertFalse(result["checks"]["verified_completeness"])

    def test_v2_verifier_rejects_live_authority_even_with_recomputed_digest(self):
        state, snapshot, _migration = self._fresh_v2_cycle()
        candidate = deepcopy(snapshot)
        candidate["live_trading_authority"] = True
        candidate = _redigest_snapshot(candidate)
        result = verify_v2_snapshot(candidate, manifest=self.v2_manifest, state=state)
        self.assertEqual(result["decision"], "reject")
        self.assertFalse(result["checks"]["live_disabled"])

    def test_v2_verifier_rejects_digest_tamper(self):
        state, snapshot, _migration = self._fresh_v2_cycle()
        candidate = deepcopy(snapshot)
        candidate["status"] = "DEGRADED"
        result = verify_v2_snapshot(candidate, manifest=self.v2_manifest, state=state)
        self.assertEqual(result["decision"], "reject")
        self.assertFalse(result["checks"]["digest"])

    def test_v2_verifier_rejects_unknown_symbol_lane_even_with_recomputed_digest(self):
        state, snapshot, _migration = self._fresh_v2_cycle()
        candidate = deepcopy(snapshot)
        candidate["lanes"][0]["symbol"] = "DOGEUSDT"
        candidate = _redigest_snapshot(candidate)
        result = verify_v2_snapshot(candidate, manifest=self.v2_manifest, state=state)
        self.assertEqual(result["decision"], "reject")
        self.assertFalse(result["checks"]["lane_namespace"])

    def test_tampered_v1_state_cannot_be_migrated(self):
        path = self._write_verified_legacy_state()
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["cells"]["BTCUSDT:hour1"]["symbol"] = "SOLUSDT"
        path.write_text(json.dumps(raw), encoding="utf-8")
        with self.assertRaises(MultiPairMatrixError):
            load_or_migrate_state(
                path,
                self.v2_manifest,
                legacy_manifest_path=LEGACY_MANIFEST,
            )

    def test_v2_manifest_authority_mutation_fails_closed(self):
        candidate = self.root / "bad-manifest.json"
        raw = json.loads(V2_MANIFEST.read_text(encoding="utf-8"))
        raw["authority"]["live_trading_authority"] = True
        candidate.write_text(json.dumps(raw), encoding="utf-8")
        with self.assertRaises(MultiPairMatrixError):
            load_manifest(candidate)


if __name__ == "__main__":
    unittest.main()
