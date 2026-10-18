from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

import pandas as pd
import pytest

from nexus_elliott_v119_accounting_qa import (
    ENGINE_SHA256, LEDGER_SHA256, RESULT_DIGEST, digest, fixed_trade_exit,
)
from product_elliott_research import (
    DISPOSITION, ENTRY_QA_FILE, LEDGER_FILE, QA_FILE, REPORT_ID, WORKSPACE_ID, completed_study,
)
from product_research_reports import ResearchReportStore, safe_json
from product_strategy_workspace import StrategyWorkspace, StrategyWorkspaceError

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "product_ui" / "research-reports"


def test_frozen_code_and_full_original_ledger_are_byte_identical():
    assert hashlib.sha256((ROOT / "research/elliott_v119_wave2_support/retest_v119.py").read_bytes()).hexdigest() == ENGINE_SHA256
    assert hashlib.sha256((ASSETS / LEDGER_FILE).read_bytes()).hexdigest() == LEDGER_SHA256
    ledger = safe_json(ASSETS / LEDGER_FILE)
    assert digest({k: v for k, v in ledger.items() if k != "result_digest"}) == RESULT_DIGEST


def test_projection_preserves_shared_cash_negative_results_and_evidence_limits():
    item = completed_study(ASSETS, safe_json)
    assert item["id"] == REPORT_ID and item["reference_capital_usdt"] == 500
    assert item["original_verdict"] == DISPOSITION and item["execution_eligible"] is False
    report = item["report"]
    assert report["backtest_reexecuted"] is False
    assert report["signal_to_entry_causality_independently_verified"] is False
    assert report["full_elliott_wave_count_verified"] is False
    assert report["independent_future_holdout"] is False
    assert len(report["rows"]) == 6
    assert {r["profile"] for r in report["rows"]} == {"conservative", "stress"}
    assert sum(r["round_trips"] for r in report["rows"] if r["profile"] == "conservative") == 77
    assert sum(len(r["monthly"]) for r in report["rows"]) == 74
    assert all(r["net_pnl_usdt"] < 0 and r["initial_shared_cash_usdt"] == 500
               and r["max_drawdown_pct"] is None for r in report["rows"])
    assert [r["net_pnl_usdt"] for r in report["rows"]] == [
        -22.80314596, -55.03704742, -19.94146730, -30.12331491, -6.40778594, -18.81775580,
    ]
    assert set(report["system_rules"]) == {"context", "pattern", "entry", "exit", "timeout", "sizing", "no_trade", "costs"}


def test_entry_prefix_proof_covers_exact_recorded_entries_without_promoting_its_scope():
    item = completed_study(ASSETS, safe_json)
    proof = item["report"]["entry_prefix_qa"]
    assert proof["counts"] == {"unique_compatible_witness": 77}
    assert proof["recorded_unique_entries_checked"] == len(proof["entries"]) == 77
    assert proof["all_recorded_entries_compatible"] is True
    assert proof["historical_backtest_reexecuted"] is False
    assert proof["original_signal_event_identity_verified"] is False
    assert proof["signal_to_entry_causality_independently_verified"] is False
    assert item["report"]["signal_to_entry_causality_independently_verified"] is False
    assert item["original_verdict"] == DISPOSITION and item["execution_eligible"] is False


@pytest.mark.parametrize("target,mutation", [
    (LEDGER_FILE, "positive_result"), (LEDGER_FILE, "promote"),
    (QA_FILE, "scope"), (QA_FILE, "missing"), (QA_FILE, "duplicate_key"),
    (ENTRY_QA_FILE, "missing"), (ENTRY_QA_FILE, "entry_scope"), (ENTRY_QA_FILE, "entry_index"),
])
def test_missing_or_changed_evidence_cannot_publish_a_verified_elliott_report(tmp_path, target, mutation):
    shutil.copytree(ASSETS, tmp_path / "research-reports")
    path = tmp_path / "research-reports" / target
    if mutation == "missing":
        path.unlink()
    elif mutation == "duplicate_key":
        path.write_text('{"passed":true,"passed":false}', encoding="utf-8")
    else:
        value = json.loads(path.read_bytes())
        if mutation == "positive_result":
            value["results"]["training"]["profiles"]["stress"]["net_pnl_usdt"] = 1
            value["result_digest"] = digest({k: v for k, v in value.items() if k != "result_digest"})
        elif mutation == "promote":
            value["paper_eligible"] = True
        elif mutation == "entry_scope":
            value["original_signal_event_identity_verified"] = True
            value["entry_witness_qa_digest"] = digest({k: v for k, v in value.items() if k != "entry_witness_qa_digest"})
        elif mutation == "entry_index":
            value["entries"][0]["entry_index"] += 1
            value["entry_witness_qa_digest"] = digest({k: v for k, v in value.items() if k != "entry_witness_qa_digest"})
        else:
            value["signal_to_entry_causality_independently_verified"] = True
            value["qa_digest"] = digest({k: v for k, v in value.items() if k != "qa_digest"})
        path.write_text(json.dumps(value), encoding="utf-8")
    result = ResearchReportStore(tmp_path).snapshot()
    assert REPORT_ID not in {r["id"] for r in result["reports"]}
    assert {e["id"] for e in result["errors"]} == {REPORT_ID}


def test_selecting_archived_elliott_never_falls_back_to_a_manual_preset(tmp_path):
    owner = tmp_path / "owner"
    owner.mkdir()
    journal = owner / "paper-events.jsonl"
    journal.write_bytes(b'{"existing":"preserve"}\n')
    before = journal.read_bytes()
    workspace = StrategyWorkspace(owner)
    item = next(x for x in workspace.snapshot()["catalog"] if x["id"] == WORKSPACE_ID)
    assert item["kind"] == "frozen_research_system" and item["paper_admission"] is False
    workspace.select(WORKSPACE_ID)
    with pytest.raises(StrategyWorkspaceError, match="reviewed Research Agent"):
        workspace.selected_manual_family(WORKSPACE_ID)
    assert journal.read_bytes() == before


@pytest.mark.parametrize("opened,low,high,expected", [
    (100, 89, 111, (0, 90, "STOP_FIRST_AMBIGUOUS")),
    (85, 84, 111, (0, 85, "STRUCTURE_STOP_GAP")),
    (100, 95, 111, (0, 110, "PRECOMMITTED_TARGET")),
])
def test_independent_physical_checker_uses_stop_first_gap_and_precommitted_target(opened, low, high, expected):
    frame = pd.DataFrame([{"open": opened, "low": low, "high": high}] * 4)
    trade = {"entry_index": 0, "structural_stop": 90, "structural_target": 110}
    assert fixed_trade_exit(frame, trade, 4) == expected


@pytest.mark.parametrize("length", [4, 100])
def test_predeclared_timeout_open_precedes_intrabar_bracket_on_timeout_bar(length):
    frame = pd.DataFrame([{"open": 100, "low": 95, "high": 105}] * length)
    index = min(96, length - 1)
    frame.loc[index] = {"open": 80, "low": 70, "high": 120}
    trade = {"entry_index": 0, "structural_stop": 90, "structural_target": 110}
    assert fixed_trade_exit(frame, trade, length) == (index, 80, "TIMEOUT_OR_PARTITION_END_OPEN")
