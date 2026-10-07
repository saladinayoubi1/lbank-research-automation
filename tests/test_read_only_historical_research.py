from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import date
from pathlib import Path

import pytest

from read_only_historical_research import (
    FAMILIES, FRAMES, PAIRS, HistoricalArchiveUnavailable, archive_view,
    load_historical_month,
)

SOURCE = "a" * 40
START = date(2026, 8, 1)
END = date(2026, 9, 1)
START_MS = (START - date(1970, 1, 1)).days * 86_400_000


def _encoded(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _archive(root: Path) -> tuple[Path, str]:
    root.mkdir()
    (root / "datasets").mkdir()
    acquisitions = []
    table, records = [], []
    for pair in PAIRS:
        for tf, (grid, per_day) in FRAMES.items():
            count = per_day * 31
            binding = hashlib.sha256((pair + tf).encode()).hexdigest()
            dataset = {
                "source": "Bybit", "source_symbol": pair,
                "source_role": "primary", "finality": "closed_only",
                "interval": {"15m": "15", "1h": "60", "4h": "240"}[tf],
                "timestamp_grid_ms": grid,
                "row_count": count, "binding_sha256": binding,
                "rows": [{"open_time_ms": START_MS + i * grid} for i in range(count)],
            }
            raw = _encoded(dataset)
            (root / "datasets" / f"{pair}-{tf}.json").write_bytes(raw)
            acquisitions.append({
                "symbol": pair, "timeframe": tf, "rows": count,
                "binding_sha256": binding, "dataset_sha256": hashlib.sha256(raw).hexdigest(),
            })
            for fam in FAMILIES:
                row = {
                    "symbol": pair, "timeframe": tf, "strategy": fam,
                    "source_sha": SOURCE, "dataset_binding_sha256": binding,
                    "qualification": "killed", "kill_reasons": "OOS_KILL;WALK_FORWARD_KILL",
                    # Positive historical return is never accepted as evidence of qualification.
                    "net_return_pct": 12.0, "stress_net_return_pct": 8.0,
                    "closed_trades": 2, "profit_factor": None,
                    "max_drawdown_pct": 3.0, "win_rate_pct": 50.0,
                }
                records.append(row)
                table.append(row)
    fields = list(table[0])
    csv_output = io.StringIO(newline="")
    writer = csv.DictWriter(csv_output, fieldnames=fields)
    writer.writeheader()
    writer.writerows(table)
    raw_csv = csv_output.getvalue().encode("utf-8")
    # All rows in journal share the exact verified source grid and metric shape.
    (root / "review-table.csv").write_bytes(raw_csv)
    (root / "cells.jsonl").write_text(
        "\n".join(json.dumps(r, sort_keys=True, allow_nan=False) for r in records) + "\n",
        encoding="utf-8",
    )
    pinned = hashlib.sha256(raw_csv).hexdigest()
    summary = {
        "contract_version": "nexus.bybit-calendar-month-pre-demo-research.v1",
        "decision": "FULL_MONTH_HISTORICAL_BACKTEST_COMPLETE",
        "start_utc": START.isoformat(), "end_exclusive_utc": END.isoformat(),
        "code_sha": SOURCE, "bybit_only": True, "exact_canonical_months": 12,
        "strategy_cells": 36, "no_demo_or_live_execution": True,
        "owner_review_required_before_any_new_demo": True,
        "no_profitability_claim": True, "report_sha256": pinned,
        "acquisitions": acquisitions,
    }
    (root / "summary.json").write_bytes(_encoded(summary))
    return root, pinned


@pytest.fixture
def archive(tmp_path):
    return _archive(tmp_path / "readonly-source-archive")


def _load(archive):
    root, pin = archive
    return load_historical_month(root, expected_report_sha256=pin,
                                 expected_source_sha=SOURCE)


def test_full_august_archive_is_verified_only_for_read_only_historical_display(archive):
    result = _load(archive)
    assert result["contract_version"] == "nexus.historical-monthly-research.v1"
    assert result["status"] == "verified_historical_only"
    assert result["dataset_count"] == 12
    assert result["cell_count"] == result["rejected_count"] == 36
    assert result["qualified_count"] == 0
    assert all(row["qualification"] == "killed" for row in result["cells"])
    assert result["cells"][0]["net_return_pct"] > 0
    assert result["auto_demo_admission"] is False
    assert result["live_trading_authority"] is False
    assert "archive" not in result  # Never return local filesystem locations.


def test_missing_or_bad_pins_fail_closed(archive):
    root, pin = archive
    with pytest.raises(HistoricalArchiveUnavailable, match="source-pinned"):
        load_historical_month(root, expected_source_sha=SOURCE)
    with pytest.raises(HistoricalArchiveUnavailable, match="summary contract"):
        load_historical_month(root, expected_report_sha256=pin, expected_source_sha="b" * 40)
    with pytest.raises(HistoricalArchiveUnavailable, match="source-pinned"):
        load_historical_month(root, expected_report_sha256=pin, expected_source_sha="not-sha")


def test_changed_report_bytes_never_appear_in_ui(archive):
    root, _ = archive
    with (root / "review-table.csv").open("ab") as f:
        f.write(b"\n")
    with pytest.raises(HistoricalArchiveUnavailable, match="digest"):
        _load(archive)


def test_broken_dataset_hash_is_rejected_even_when_report_csv_is_unchanged(archive):
    root, _ = archive
    with (root / "datasets" / "ETHUSDT-4h.json").open("ab") as f:
        f.write(b" ")
    with pytest.raises(HistoricalArchiveUnavailable, match="digest"):
        _load(archive)


def test_timestamp_gap_fails_even_when_supplier_rehashes_dataset(archive):
    root, _ = archive
    p = root / "datasets" / "SOLUSDT-1h.json"
    ds = json.loads(p.read_text())
    ds["rows"][11]["open_time_ms"] += 3_600_000
    raw = _encoded(ds)
    p.write_bytes(raw)
    summary = json.loads((root / "summary.json").read_text())
    for x in summary["acquisitions"]:
        if x["symbol"] == "SOLUSDT" and x["timeframe"] == "1h":
            x["dataset_sha256"] = hashlib.sha256(raw).hexdigest()
    (root / "summary.json").write_bytes(_encoded(summary))
    with pytest.raises(HistoricalArchiveUnavailable, match="timestamp gaps"):
        _load(archive)


def test_unsupported_source_fails_even_after_supplier_rehash(archive):
    root, _ = archive
    p = root / "datasets" / "XRPUSDT-15m.json"
    ds = json.loads(p.read_text())
    ds["source"] = "Synthetic"
    raw = _encoded(ds)
    p.write_bytes(raw)
    summary = json.loads((root / "summary.json").read_text())
    for x in summary["acquisitions"]:
        if x["symbol"] == "XRPUSDT" and x["timeframe"] == "15m":
            x["dataset_sha256"] = hashlib.sha256(raw).hexdigest()
    (root / "summary.json").write_bytes(_encoded(summary))
    with pytest.raises(HistoricalArchiveUnavailable, match="source or grid"):
        _load(archive)


def test_symlinked_report_never_accepted(archive, tmp_path):
    root, _ = archive
    original = root / "review-table.csv"
    target = tmp_path / "elsewhere.csv"
    target.write_bytes(original.read_bytes())
    original.unlink()
    original.symlink_to(target)
    with pytest.raises(HistoricalArchiveUnavailable, match="unsafe"):
        _load(archive)


def test_unsafe_admission_statement_never_shown_even_if_new_csv_is_pinned(archive):
    root, _ = archive
    csv_path = root / "review-table.csv"
    rows = list(csv.DictReader(io.StringIO(csv_path.read_text())))
    rows[0]["qualification"] = "paper_candidate"
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    raw = stream.getvalue().encode()
    csv_path.write_bytes(raw)
    summary = json.loads((root / "summary.json").read_text())
    summary["report_sha256"] = hashlib.sha256(raw).hexdigest()
    (root / "summary.json").write_bytes(_encoded(summary))
    with pytest.raises(HistoricalArchiveUnavailable, match="journal mismatch"):
        load_historical_month(root, expected_report_sha256=summary["report_sha256"],
                              expected_source_sha=SOURCE)


def test_separately_unavailable_does_not_forge_live_research(monkeypatch, tmp_path):
    monkeypatch.delenv("NEXUS_HISTORICAL_MONTHLY_ARCHIVE_DIR", raising=False)
    monkeypatch.delenv("NEXUS_HISTORICAL_MONTHLY_REPORT_SHA256", raising=False)
    monkeypatch.delenv("NEXUS_HISTORICAL_MONTHLY_CODE_SHA", raising=False)
    unavailable = archive_view()
    assert unavailable["status"] == "unavailable"
    assert unavailable["cells"] == []
    assert unavailable["live_trading_authority"] is False

    from product_mission_runtime import ProductMissionRuntime
    # The historical module is separate from the live 24h-fresh trusted producer.
    snapshot = ProductMissionRuntime(tmp_path / "state").snapshot()
    assert snapshot["historical_monthly_research"]["status"] == "unavailable"
    assert snapshot["research_integration"]["status"] == "unavailable"


def test_pinned_archive_is_a_separate_mission_surface(monkeypatch, tmp_path, archive):
    from product_mission_runtime import ProductMissionRuntime

    root, pin = archive
    monkeypatch.setenv("NEXUS_HISTORICAL_MONTHLY_ARCHIVE_DIR", str(root))
    monkeypatch.setenv("NEXUS_HISTORICAL_MONTHLY_REPORT_SHA256", pin)
    monkeypatch.setenv("NEXUS_HISTORICAL_MONTHLY_CODE_SHA", SOURCE)
    snapshot = ProductMissionRuntime(tmp_path / "state").snapshot()
    hist = snapshot["historical_monthly_research"]
    assert hist["cell_count"] == 36 and hist["qualified_count"] == 0
    assert snapshot["research_integration"]["status"] == "unavailable"
    assert snapshot["strategy_center"]["candidate_count"] == 0


def test_pro_ui_displays_frozen_month_with_filters_and_no_approval_claim():
    ui = Path(__file__).resolve().parents[1] / "product_ui"
    js = (ui / "research-operations.js").read_text(encoding="utf-8")
    css = (ui / "research-operations.css").read_text(encoding="utf-8")
    assert "historical_monthly_research" in js
    assert "data-month-pair" in js and "renderResearch(m)" in js
    assert "archive.qualified_count !== 0" in js
    assert "auto_demo_admission !== false" in js
    assert "historicalMonth(m) +" in js
    assert ".ops-month-table-wrap" in css


def test_malformed_closed_trades_fails_closed_without_taking_full_mission_down(
    archive, monkeypatch,
):
    root, _ = archive
    p = root / "review-table.csv"
    rows = list(csv.DictReader(io.StringIO(p.read_text())))
    rows[0]["closed_trades"] = "NaN"
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    raw = stream.getvalue().encode()
    p.write_bytes(raw)
    updated = json.loads((root / "summary.json").read_text())
    updated["report_sha256"] = hashlib.sha256(raw).hexdigest()
    (root / "summary.json").write_bytes(_encoded(updated))
    monkeypatch.setenv("NEXUS_HISTORICAL_MONTHLY_ARCHIVE_DIR", str(root))
    monkeypatch.setenv("NEXUS_HISTORICAL_MONTHLY_REPORT_SHA256",
                       updated["report_sha256"])
    monkeypatch.setenv("NEXUS_HISTORICAL_MONTHLY_CODE_SHA", SOURCE)
    result = archive_view()
    assert result["status"] == "unavailable"
    assert result["cells"] == []
    assert result["live_trading_authority"] is False
