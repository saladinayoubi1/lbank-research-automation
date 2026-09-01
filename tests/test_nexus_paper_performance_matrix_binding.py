from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import nexus_demo_paper_performance_refresh as refresh


SOURCE_SHA = "a" * 40


def _manifest() -> dict:
    return {
        "symbols": ["BTCUSDT", "ETHUSDT"],
        "timeframes": ["minute15", "hour1", "hour4"],
    }


def _state() -> dict:
    cells = {}
    for symbol in _manifest()["symbols"]:
        for timeframe in _manifest()["timeframes"]:
            cell_id = f"{symbol}:{timeframe}"
            cells[cell_id] = {
                "cell_id": cell_id,
                "symbol": symbol,
                "timeframe": timeframe,
                "status": "VERIFIED",
                "source_sha": SOURCE_SHA,
                "analysis_digest": "1" * 64,
                "analysis_status_counts": {},
            }
    return {"cells": cells, "state_digest": "2" * 64}


def _rows() -> list[dict]:
    rows = []
    for index, (symbol, timeframe) in enumerate(
        (s, t) for s in _manifest()["symbols"] for t in _manifest()["timeframes"]
    ):
        rows.append({
            "symbol": symbol,
            "timeframe": timeframe,
            "strategy_count": index + 1,
            "status_counts": {"INSUFFICIENT_EVIDENCE": index + 1},
            "projection_digest": f"{index + 3:064x}",
        })
    return rows


def test_refresh_rebinds_matrix_state_and_snapshot_to_new_performance(monkeypatch, tmp_path: Path) -> None:
    state = _state()
    snapshot = {
        "source_sha": SOURCE_SHA,
        "status": "VERIFIED",
        "state_digest": state["state_digest"],
        "snapshot_digest": "3" * 64,
    }
    demo = tmp_path / "demo"
    demo.mkdir(parents=True)
    (demo / "strategy-matrix.json").write_text(__import__("json").dumps(snapshot), encoding="utf-8")
    monkeypatch.setattr(refresh, "load_state", lambda _path, _manifest: deepcopy(state))
    monkeypatch.setattr(refresh, "verify_snapshot", lambda _value: {"decision": "pass"})

    rebound_state, rebound_snapshot = refresh._rebind_matrix_performance(
        manifest=_manifest(),
        root=tmp_path,
        source_sha=SOURCE_SHA,
        rows=_rows(),
    )

    eth15 = rebound_state["cells"]["ETHUSDT:minute15"]
    expected = next(
        row for row in _rows()
        if row["symbol"] == "ETHUSDT" and row["timeframe"] == "minute15"
    )
    assert eth15["analysis_digest"] == expected["projection_digest"]
    assert eth15["analysis_status_counts"] == expected["status_counts"]
    assert rebound_state["state_digest"] != state["state_digest"]
    assert rebound_snapshot["state_digest"] == rebound_state["state_digest"]
    snapshot_core = dict(rebound_snapshot)
    claimed_snapshot_digest = snapshot_core.pop("snapshot_digest")
    assert claimed_snapshot_digest == refresh._matrix_digest(snapshot_core)


def test_refresh_rebind_fails_closed_on_incomplete_performance_surface(monkeypatch, tmp_path: Path) -> None:
    state = _state()
    snapshot = {
        "source_sha": SOURCE_SHA,
        "status": "VERIFIED",
        "state_digest": state["state_digest"],
        "snapshot_digest": "3" * 64,
    }
    demo = tmp_path / "demo"
    demo.mkdir(parents=True)
    (demo / "strategy-matrix.json").write_text(__import__("json").dumps(snapshot), encoding="utf-8")
    monkeypatch.setattr(refresh, "load_state", lambda _path, _manifest: deepcopy(state))
    monkeypatch.setattr(refresh, "verify_snapshot", lambda _value: {"decision": "pass"})

    rows = _rows()[:-1]
    try:
        refresh._rebind_matrix_performance(
            manifest=_manifest(), root=tmp_path, source_sha=SOURCE_SHA, rows=rows
        )
    except refresh.DemoPaperPerformanceRefreshError as exc:
        assert "exact matrix surface" in str(exc)
    else:
        raise AssertionError("incomplete performance surface must fail closed")
