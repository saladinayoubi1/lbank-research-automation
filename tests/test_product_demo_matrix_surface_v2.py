from __future__ import annotations

import hashlib
import json
from pathlib import Path

from nexus_multipair_demo_strategy_matrix import run_cycle
from product_web_server import _demo_matrix_snapshot

ROOT = Path(__file__).resolve().parents[1]
V1_MANIFEST = ROOT / "config" / "nexus-demo-strategy-matrix-v1.json"
V2_MANIFEST = ROOT / "config" / "nexus-demo-strategy-matrix-v2.json"


def _hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _runner(**kwargs):
    tasks = [{
        "family": family,
        "task_id": f"{kwargs['symbol']}:{kwargs['timeframe']}:{family}",
        "status": "qualification_killed",
        "evidence_digest": _hex(f"{kwargs['symbol']}:{kwargs['timeframe']}:{family}"),
    } for family in kwargs["families"]]
    return {
        "symbol": kwargs["symbol"],
        "timeframe": kwargs["timeframe"],
        "paper_only": True,
        "live_trading_authority": False,
        "tasks": tasks,
        "ledger_digest": _hex(f"ledger:{kwargs['symbol']}:{kwargs['timeframe']}"),
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


def _write_surface(tmp_path: Path):
    state, snapshot, _ = run_cycle(
        manifest_path=V2_MANIFEST,
        legacy_manifest_path=V1_MANIFEST,
        state_path=tmp_path / "new-state.json",
        state_root=tmp_path / "runtime",
        source_sha="a" * 40,
        run_id="90",
        now_ms=1_800_000_000_000,
        runner=_runner,
        verifier=_verifier,
        analyzer=_analyzer,
    )
    demo = tmp_path / "demo"
    demo.mkdir()
    (demo / "strategy-matrix.json").write_text(json.dumps(snapshot), encoding="utf-8")
    (demo / "matrix-state.json").write_text(json.dumps(state), encoding="utf-8")
    (demo / "matrix-manifest-v2.json").write_text(V2_MANIFEST.read_text(encoding="utf-8"), encoding="utf-8")
    return demo, state


def test_product_demo_reads_verified_multipair_matrix_snapshot(tmp_path: Path) -> None:
    _write_surface(tmp_path)
    payload = _demo_matrix_snapshot(tmp_path / "market")
    assert payload["status"] == "VERIFIED"
    assert payload["expected_cell_count"] == 12
    assert payload["verified_cell_count"] == 12
    assert payload["expected_lane_count"] == 36
    assert payload["reported_lane_count"] == 36
    assert payload["paper_only"] is True
    assert payload["live_trading_authority"] is False


def test_product_demo_v2_fails_closed_without_exact_state(tmp_path: Path) -> None:
    demo, state = _write_surface(tmp_path)
    state["state_digest"] = "0" * 64
    (demo / "matrix-state.json").write_text(json.dumps(state), encoding="utf-8")
    payload = _demo_matrix_snapshot(tmp_path / "market")
    assert payload["status"] == "unavailable"
    assert payload["reason"] == "snapshot_verification_failed"
