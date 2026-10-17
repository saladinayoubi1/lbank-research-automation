"""Independent Butterfly V8 negative evidence tests; never claim new candidate."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "research/causal_butterfly_v8_cost_audit.py"
REPORT = ROOT / (
    "docs/evidence/causal-butterfly-v8-20261014/first-producer/"
    "native-artifacts/producer/research-report.json"
)
mod_spec = importlib.util.spec_from_file_location("nexus_butterfly_v8_cost_audit", SOURCE)
module = importlib.util.module_from_spec(mod_spec)
assert mod_spec.loader is not None
mod_spec.loader.exec_module(module)


def real_report():
    return json.loads(REPORT.read_text("utf-8"))


def test_real_frozen_butterfly_market_report_is_rejected_for_costs_and_no_test_trades():
    result = module.audit(real_report())
    assert result["status"].startswith("REJECTED_")
    assert result["training_conservative_positive_but_stress_negative"]
    assert result["validation_both_symbols_both_profiles_negative"]
    assert result["historically_inspected_test_has_zero_trades"]
    assert result["source_authenticity_independently_verified_here"] is False
    assert result["trade_engine_independently_replayed_here"] is False
    assert result["candidate_profitable_claim"] is False
    assert result["qualifies_for_paper_demo"] is False
    assert result["live_trading_authority"] is False
    assert len(result["aggregated_cell_diagnostics_not_one_account"]) == 6
    assert result["audit_sha256"] == module._digest({
        k: v for k, v in result.items() if k != "audit_sha256"
    })


def test_no_positions_in_old_test_is_not_a_zero_loss_success():
    result = module.audit(real_report())
    for row in result["aggregated_cell_diagnostics_not_one_account"]:
        if row["partition"] == "historically_inspected_test":
            assert row["total_closed_round_trips"] == 0
            assert row["sum_independent_account_pnl_usdt"] == 0
    assert result["trades_in_held_out_test_sufficient_to_validate"] is False


def test_training_cost_inversion_and_validation_losses_remain_a_full_denominator():
    value = module.audit(real_report())
    c = {
        (row["partition"], row["cost_profile"]): row
        for row in value["aggregated_cell_diagnostics_not_one_account"]
    }
    assert c["train", "conservative"]["total_closed_round_trips"] == 3
    assert c["train", "conservative"]["sum_independent_account_pnl_usdt"] > 0
    assert c["train", "stress"]["total_closed_round_trips"] == 3
    assert c["train", "stress"]["sum_independent_account_pnl_usdt"] < 0
    assert c["validation", "conservative"]["total_closed_round_trips"] == 2
    assert c["validation", "conservative"]["sum_independent_account_pnl_usdt"] < 0
    assert c["validation", "stress"]["sum_independent_account_pnl_usdt"] < 0


@pytest.mark.parametrize("change", [
    "different_source", "tampered_digest", "fake_future", "fake_qualification",
    "missing_row", "duplicate_row", "changed_stress_loss", "renamed_mechanism",
    "research_to_live", "altered_cost_interpretation", "invent_test_trade",
])
def test_tampered_source_or_attempted_candidate_promotion_fails_closed(change):
    report = deepcopy(real_report())
    if change == "different_source":
        report["source_sha"] = "0" * 40
    elif change == "tampered_digest":
        report["report_digest"] = "0" * 64
    elif change == "fake_future":
        report["historical_test_pristine"] = True
    elif change == "fake_qualification":
        report["qualification"] = "QUALIFIED"
    elif change == "missing_row":
        report["rows"].pop()
    elif change == "duplicate_row":
        report["rows"][0] = report["rows"][1]
    elif change == "changed_stress_loss":
        row = next(x for x in report["rows"] if x["part"] == "train" and x["profile"] == "stress")
        row["net_pnl_usdt"] = 200
    elif change == "renamed_mechanism":
        report["rows"][0]["mechanism"] = "profitable_butterfly"
    elif change == "research_to_live":
        report["live_enabled"] = True
    elif change == "altered_cost_interpretation":
        report["rows"][1]["net_return_pct"] = 999
    elif change == "invent_test_trade":
        row = next(x for x in report["rows"] if x["part"] == "historically_inspected_test")
        row["closed_round_trips"] = 50
    with pytest.raises(module.ButterflyCostAuditError):
        module.audit(report)


def test_canonical_rehash_cannot_substitute_for_pinned_first_producer_receipt():
    report = deepcopy(real_report())
    report["rows"][0]["net_pnl_usdt"] = 5000
    core = dict(report)
    core.pop("report_digest")
    report["report_digest"] = module._digest(core)
    with pytest.raises(module.ButterflyCostAuditError):
        module.audit(report)


def test_source_scope_has_no_trade_or_demo_promotion_code():
    src = SOURCE.read_text("utf8")
    assert "requests.post(" not in src
    assert "bybit_order" not in src
    assert '"qualifies_for_paper_demo": False' in src
    assert '"live_trading_authority": False' in src
