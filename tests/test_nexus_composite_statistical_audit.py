"""Causal/statistical non-authority, multiple testing, and future data freeze."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

import nexus_composite_strategy_research as research
from nexus_composite_statistical_audit import (
    SCHEMA_EVIDENCE,
    StatisticalReviewError,
    _sign_p_value,
    historical_review,
    prospective_diagnostic,
)


def _ledger(*, n=1, screened=0):
    base = research.empty_ledger()
    core = {key: value for key, value in base.items() if key != "ledger_digest"}
    core["config_fingerprints_evaluated"] = [
        format(i + 1, "064x") for i in range(n)
    ]
    core["mechanisms_evaluated"] = ["old_mechanism"]
    core["frontier_screened_mechanisms"] = [
        f"reviewed_{i}" for i in range(screened)
    ]
    return {**core, "ledger_digest": research.digest(core)}


def _report(ledger, *, positive=True):
    rows = [
        {"symbol": symbol, "part": part, "profile": profile,
         "net_return_pct": 55.0 if positive else -1.0,
         "closed_round_trips": 1, "trade_count_limit": None}
        for symbol in ("BTCUSDT", "ETHUSDT")
        for part in ("train", "validation", "historically_inspected_test")
        for profile in ("conservative", "stress")
    ]
    base = {
        "schema": research.SCHEMA, "source_sha": "a"*40,
        "archive_sha256": research.ARCHIVE_SHA256,
        "status": "EVALUATED_RESEARCH_ONLY",
        "historical_test_pristine": False,
        "independent_future_data_required": True,
        "research_only": True, "auto_demo_promotion": False,
        "live_enabled": False, "ledger_digest": ledger["ledger_digest"],
        "selected": {"fingerprint": "f"*64},
        "rows": rows,
    }
    return {**base, "report_digest": research.digest(base)}


def _forward(ledger, *, weeks=16, positive=True):
    start = datetime(2026, 11, 1, tzinfo=timezone.utc)
    data = []
    for i in range(weeks):
        a = start + timedelta(days=7*i)
        b = a + timedelta(days=7)
        data.append({
            "week_start_utc": a.isoformat().replace("+00:00", "Z"),
            "week_end_utc": b.isoformat().replace("+00:00", "Z"),
            "dataset_bindings_sha256": {
                "BTCUSDT": format(4000+i, "064x"),
                "ETHUSDT": format(5000+i, "064x"),
            },
            "benchmark_net_return_pct": 0.0,
            "conservative_net_return_pct": 1.0 if positive else -1.0,
            "stress_net_return_pct": 0.5 if positive else -1.5,
            "paper_event_digest": format(6000+i, "064x"),
        })
    return {
        "schema_version": SCHEMA_EVIDENCE,
        "freeze": {
            "candidate_source_sha": "a"*40,
            "candidate_config_digest": "b"*64,
            "candidate_digest": "c"*64,
            "ledger_digest": ledger["ledger_digest"],
            "frozen_before_utc": "2026-10-10T00:00:00Z",
            "planned_weekly_windows": weeks,
            "analysis_not_before_utc": (
                start + timedelta(days=7*weeks)
            ).isoformat().replace("+00:00", "Z"),
        },
        "weekly_windows": data,
    }


def test_twelve_positive_historical_cells_do_not_establish_statistical_edge():
    ledger = _ledger(n=13, screened=10)
    report = historical_review(_report(ledger), ledger)
    assert report["cells_checked"] == 12
    assert report["independent_observations_inferred_from_cells"] == 0
    assert report["decision"] == "INSUFFICIENT_PRISTINE_PROSPECTIVE_EVIDENCE"
    assert report["statistical_significance_established"] is False
    assert report["historical_test_pristine"] is False
    assert report["owner_demo_admission_allowed"] is False
    assert report["historical_minimum_trade_count"] is None
    assert report["search_multiplicity"]["hypotheses_considered_at_least"] == 23
    assert report == historical_review(_report(ledger), ledger)


def test_even_negative_historical_cells_have_no_phantom_excess_significance():
    ledger = _ledger()
    report = historical_review(_report(ledger, positive=False), ledger)
    assert report["statistical_significance_established"] is False
    assert report["decision"] == "INSUFFICIENT_PRISTINE_PROSPECTIVE_EVIDENCE"


def test_historical_rehashed_tampered_cells_fail_closed():
    ledger = _ledger()
    report = _report(ledger)
    report["rows"][0]["profile"] = "stress"
    report["report_digest"] = research.digest({
        k: v for k, v in report.items() if k != "report_digest"
    })
    with pytest.raises(StatisticalReviewError, match="duplicate|unsupported"):
        historical_review(report, ledger)
    bad_ledger = deepcopy(ledger)
    bad_ledger["frontier_screened_mechanisms"].append("hidden_candidate")
    with pytest.raises(StatisticalReviewError, match="digest mismatch"):
        historical_review(_report(ledger), bad_ledger)


def test_historical_spurious_trade_cap_fail_closed():
    ledger = _ledger()
    report = _report(ledger)
    report["rows"][0]["trade_count_limit"] = 4
    report["report_digest"] = research.digest({
        k: v for k, v in report.items() if k != "report_digest"
    })
    with pytest.raises(StatisticalReviewError, match="artificial trade"):
        historical_review(report, ledger)


def test_onesided_sign_test_exact_and_conservative():
    assert _sign_p_value(12, 12) == 1 / 4096
    assert _sign_p_value(4, 2) == 11 / 16
    with pytest.raises(StatisticalReviewError):
        _sign_p_value(0, 0)


def test_strong_synthetic_future_pattern_is_only_conditional_diagnostic():
    ledger = _ledger(n=10)
    report = prospective_diagnostic(_forward(ledger), ledger)
    assert report["weekly_windows_observed"] == 16
    assert report["multiple_comparison_count"] == 20
    assert report["descriptive_sign_test_supported"] is True
    assert report["statistical_edge_established"] is False
    assert report["pristine_prospective_proof_verified"] is False
    assert report["owner_demo_admission_allowed"] is False
    assert report["registry_eligibility_authority"] is False
    assert report["live_trading_authority"] is False
    assert "WEEKLY_SIGN_INDEPENDENCE_NOT_PROVEN" in report["reason_codes"]
    assert report == prospective_diagnostic(_forward(ledger), ledger)


def test_multiple_comparison_correction_blocks_frequent_frontier_false_positive():
    ledger = _ledger(n=120)
    r = prospective_diagnostic(_forward(ledger, weeks=12), ledger)
    assert r["raw_onesided_sign_p"]["conservative"] == 1 / 4096
    assert r["multiple_comparison_count"] == 240
    assert r["bonferroni_familywise_adjusted_p"]["conservative"] > 0.05
    assert r["descriptive_sign_test_supported"] is False
    assert r["owner_demo_admission_allowed"] is False


def test_short_future_evidence_never_passes():
    ledger = _ledger(n=1)
    r = prospective_diagnostic(_forward(ledger, weeks=5), ledger)
    assert r["descriptive_sign_test_supported"] is False
    assert "INSUFFICIENT_NONOVERLAPPING_FUTURE_WEEKS" in r["reason_codes"]


@pytest.mark.parametrize("change", [
    lambda e: e["weekly_windows"][2].update({
        "week_start_utc": e["weekly_windows"][1]["week_start_utc"]
    }),
    lambda e: e["weekly_windows"][0].update({
        "week_start_utc": "2026-09-01T00:00:00Z"
    }),
    lambda e: e["weekly_windows"][4].update({
        "week_end_utc": e["weekly_windows"][5]["week_end_utc"]
    }),
    lambda e: e["weekly_windows"][0].update({
        "stress_net_return_pct": float("nan")
    }),
    lambda e: e["weekly_windows"][0].update({
        "conservative_net_return_pct": 101.0
    }),
    lambda e: e["weekly_windows"][0]["dataset_bindings_sha256"].pop("ETHUSDT"),
    lambda e: e["weekly_windows"][0].update({
        "paper_event_digest": None
    }),
    lambda e: e["freeze"].update({
        "candidate_source_sha": "invalid-source"
    }),
    lambda e: e["freeze"].update({
        "frozen_before_utc": "2026-12-01T00:00:00Z"
    }),
    lambda e: e["weekly_windows"][0].update({
        "fake_pristine": True
    }),
    lambda e: e["freeze"].update({
        "planned_weekly_windows": 10
    }),
    lambda e: e["freeze"].update({
        "analysis_not_before_utc": "2026-11-02T00:00:00Z"
    }),
])
def test_fake_future_leakage_and_malformed_source_never_accepted(change):
    ledger = _ledger()
    evidence = _forward(ledger)
    change(evidence)
    with pytest.raises(StatisticalReviewError):
        prospective_diagnostic(evidence, ledger)


def test_future_ledger_swap_and_double_counted_cost_profiles_fail():
    ledger = _ledger(n=4)
    false = _forward(ledger)
    false["freeze"]["ledger_digest"] = "9"*64
    with pytest.raises(StatisticalReviewError, match="novelty ledger"):
        prospective_diagnostic(false, ledger)
    result = prospective_diagnostic(_forward(ledger), ledger)
    # 16 calendar observations, NOT 32 stress+conservative observations.
    assert result["weekly_windows_observed"] == 16
    assert result["multiple_comparison_count"] == 2*4



def test_significant_win_frequency_with_large_tail_losses_is_not_economic_edge():
    ledger = _ledger(n=10)
    evidence = _forward(ledger, weeks=32)
    for row in evidence["weekly_windows"]:
        row["conservative_net_return_pct"] = 0.1
        row["stress_net_return_pct"] = 0.1
    # Two catastrophic weeks swamp thirty tiny positive weeks, even
    # though one-sided sign frequency is highly significant after Bonferroni.
    for row in evidence["weekly_windows"][:2]:
        row["conservative_net_return_pct"] = -30.0
        row["stress_net_return_pct"] = -30.0
    result = prospective_diagnostic(evidence, ledger)
    assert all(p < 0.05 for p in result["bonferroni_familywise_adjusted_p"].values())
    assert all(v < 0 for v in result["descriptive_mean_weekly_excess_pct"].values())
    assert result["descriptive_sign_test_supported"] is False
    assert "NON_POSITIVE_MEAN_BENCHMARK_EXCESS" in result["reason_codes"]
    assert result["owner_demo_admission_allowed"] is False
