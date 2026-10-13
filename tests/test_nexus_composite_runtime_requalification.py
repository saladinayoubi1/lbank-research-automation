from __future__ import annotations

from copy import deepcopy
import subprocess
import sys

import pytest

import nexus_composite_runtime_requalification as rq


CANDIDATE_DIGEST = "a" * 64
SOURCE = "b" * 40
RUNTIME_SOURCE = "c" * 40
ASOF_MS = 1_900_000_000_000


def _candidate():
    return {
        "schema_version": "nexus.composite-validation-candidate.v2",
        "system_map_node": "VAL-40",
        "decision": "FORWARD_TO_VAL40",
        "eligible_for_fresh_runtime_requalification": True,
        "requires_fresh_runtime_data": True,
        "candidate_digest": CANDIDATE_DIGEST,
        "source_sha": SOURCE,
        "archive_sha256": "d" * 64,
        "mechanism": "factory_gen_deep_drawdown_recovery_vwap_reclaim",
        "timeframe": "minute15_with_completed_1h_4h",
        "strategy_config": {
            "mechanism": "factory_gen_deep_drawdown_recovery_vwap_reclaim",
            "risk_variant": 0,
            "entry_model": "closed_4h_1h_15m_next_open",
            "factory_contract_digest": "e" * 64,
        },
        "config_fingerprint": "f" * 64,
        "no_minimum_trade_count_gate": True,
        "research_only": True,
        "paper_only": True,
        "candidate_state_created": False,
        "qualification_authority": False,
        "registry_mutation_authority": False,
        "promotion_authority": False,
        "paper_execution_authority": False,
        "automatic_strategy_promotion": False,
        "live_trading_authority": False,
    }


def _candidate_verification():
    return {
        "schema_version": "nexus.composite-validation-candidate-verification.v2",
        "decision": "pass",
        "checks": {"proof": True},
        "candidate_digest": CANDIDATE_DIGEST,
        "verification_digest": "1" * 64,
    }


def _dataset(tf, suffix):
    step = rq.TIMEFRAME_STEP_MS[tf]
    last_open = ((ASOF_MS - step) // step) * step
    return {
        "timeframe": tf,
        "binding_sha256": suffix * 64,
        "row_count": 1000,
        "first_open_time_ms": last_open - 999 * step,
        "last_open_time_ms": last_open,
    }


def _profile(name, *, trades=2, ret=0.2, halted=False):
    return {
        "profile": name,
        "net_return_pct": ret,
        "net_pnl_usdt": ret * 100.0,
        "max_drawdown_pct": 0.4,
        "closed_round_trips": trades,
        "win_rate_pct": 50.0 if trades else None,
        "profit_factor": 1.2 if trades else None,
        "profit_factor_status": (
            "AVAILABLE" if trades else "NOT_AVAILABLE_NO_REALIZED_LOSSES"
        ),
        "turnover_usdt": 1000.0 if trades else 0.0,
        "exposure_bar_ratio": 0.02 if trades else 0.0,
        "halted_on_drawdown": halted,
        "fee_bps": 10.0 if name == "conservative" else 25.0,
        "slippage_bps": 5.0 if name == "conservative" else 15.0,
        "trade_count_limit": None,
        "concurrent_risk_model":
            "one_collateral_backed_net_long_per_symbol;10pct_position_budget",
    }


def _evaluation(symbol, *, trades=2, conservative=0.2, stress=0.1, halted=False):
    candidate = _candidate()
    suffixes = {
        "BTCUSDT": {"minute15": "2", "hour1": "3", "hour4": "4"},
        "ETHUSDT": {"minute15": "5", "hour1": "6", "hour4": "7"},
    }[symbol]
    return {
        "symbol": symbol,
        "mechanism": candidate["mechanism"],
        "strategy_config": candidate["strategy_config"],
        "datasets": {
            tf: _dataset(tf, suffixes[tf]) for tf in rq.TIMEFRAMES
        },
        "peer_symbol": None,
        "peer_minute15_binding_sha256": None,
        "profiles": [
            _profile(
                "conservative", trades=trades, ret=conservative, halted=halted
            ),
            _profile("stress", trades=trades, ret=stress, halted=halted),
        ],
        "deterministic_replay_verified": True,
        "data_origin": "canonical_public_bybit_runtime",
        "closed_candle_finality_verified": True,
        "paper_only": True,
        "candidate_state_created": False,
        "qualification_authority": False,
        "registry_mutation_authority": False,
        "paper_execution_authority": False,
        "automatic_strategy_promotion": False,
        "live_trading_authority": False,
    }


def _fake_candidate_verifier(value):
    assert value["candidate_digest"] == CANDIDATE_DIGEST
    return _candidate_verification()


@pytest.fixture(autouse=True)
def _candidate_proof(monkeypatch):
    monkeypatch.setattr(rq, "verify_candidate", _fake_candidate_verifier)


def _run(evaluations):
    return rq.build_requalification(
        _candidate(),
        _candidate_verification(),
        source_sha=RUNTIME_SOURCE,
        now_ms=ASOF_MS,
        state_root=".",
        evaluator=lambda *args: deepcopy(evaluations),
    )


def test_fresh_positive_grid_only_qualifies_for_review():
    result = _run([
        _evaluation("BTCUSDT"),
        _evaluation("ETHUSDT", conservative=0.3, stress=0.05),
    ])
    assert result["decision"] == "QUALIFIED_FOR_REVIEW"
    assert result["qualified_for_review"] is True
    assert result["total_fresh_runtime_round_trips"] == 8
    assert result["runtime_as_of_ms"] == ASOF_MS
    assert result["no_minimum_trade_count_gate"] is True
    assert result["candidate_state_created"] is False
    assert result["qualification_authority"] is False
    assert result["registry_mutation_authority"] is False
    assert result["paper_execution_authority"] is False
    assert result["live_trading_authority"] is False
    assert rq.verify_requalification(result)["decision"] == "pass"


def test_zero_activity_rejects_without_minimum_trade_gate():
    result = _run([
        _evaluation("BTCUSDT", trades=0, conservative=0.0, stress=0.0),
        _evaluation("ETHUSDT", trades=0, conservative=0.0, stress=0.0),
    ])
    assert result["decision"] == "REJECTED"
    assert result["reason_codes"] == ["ZERO_ACTIVITY_ON_FRESH_RUNTIME_DATA"]
    assert result["no_minimum_trade_count_gate"] is True
    assert rq.verify_requalification(result)["decision"] == "pass"


def test_any_non_positive_fresh_cell_rejects():
    result = _run([
        _evaluation("BTCUSDT", conservative=0.2, stress=-0.01),
        _evaluation("ETHUSDT"),
    ])
    assert result["decision"] == "REJECTED"
    assert result["reason_codes"] == ["NON_POSITIVE_FRESH_RUNTIME_CELL"]
    assert rq.verify_requalification(result)["decision"] == "pass"


def test_drawdown_halt_rejects_even_if_returns_are_positive():
    result = _run([
        _evaluation("BTCUSDT", halted=True),
        _evaluation("ETHUSDT"),
    ])
    assert result["decision"] == "REJECTED"
    assert result["reason_codes"] == ["FRESH_RUNTIME_DRAWDOWN_HALT"]
    assert rq.verify_requalification(result)["decision"] == "pass"


def test_candidate_or_runtime_grid_tamper_fails_closed(monkeypatch):
    monkeypatch.setattr(
        rq,
        "verify_candidate",
        lambda value: {**_candidate_verification(), "decision": "reject"},
    )
    with pytest.raises(
        rq.CompositeRuntimeRequalificationError,
        match="candidate proof",
    ):
        _run([_evaluation("BTCUSDT"), _evaluation("ETHUSDT")])

    monkeypatch.setattr(rq, "verify_candidate", _fake_candidate_verifier)
    broken = _evaluation("BTCUSDT")
    broken["datasets"]["hour4"]["binding_sha256"] = "not-a-digest"
    with pytest.raises(
        rq.CompositeRuntimeRequalificationError,
        match="dataset binding",
    ):
        _run([broken, _evaluation("ETHUSDT")])


def test_requalification_redigested_authority_or_identity_tamper_rejects():
    result = _run([_evaluation("BTCUSDT"), _evaluation("ETHUSDT")])

    authority = deepcopy(result)
    authority["paper_execution_authority"] = True
    core = dict(authority)
    core.pop("requalification_digest", None)
    authority["requalification_digest"] = rq.digest(core)
    assert rq.verify_requalification(authority)["decision"] == "reject"

    identity = deepcopy(result)
    identity["mechanism"] = "factory_gen_fake"
    core = dict(identity)
    core.pop("requalification_digest", None)
    identity["requalification_digest"] = rq.digest(core)
    assert rq.verify_requalification(identity)["decision"] == "reject"


def test_verifier_import_is_control_plane_lightweight():
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                "sys.modules['pandas']=None; "
                "import nexus_composite_runtime_requalification as rq; "
                "assert callable(rq.verify_requalification); "
                "print('lightweight_composite_requalification=PASS')"
            ),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "lightweight_composite_requalification=PASS" in proc.stdout


def test_runtime_windows_must_be_exactly_aligned_and_latest_closed():
    rows = [_evaluation("BTCUSDT"), _evaluation("ETHUSDT")]
    rows[1]["datasets"]["hour1"]["last_open_time_ms"] += 3_600_000
    with pytest.raises(
        rq.CompositeRuntimeRequalificationError,
        match="windows are not aligned",
    ):
        _run(rows)

    rows = [_evaluation("BTCUSDT"), _evaluation("ETHUSDT")]
    # Make all 15m windows stale by two complete steps while preserving cross-symbol alignment.
    for row in rows:
        row["datasets"]["minute15"]["last_open_time_ms"] -= 1_800_000
    with pytest.raises(
        rq.CompositeRuntimeRequalificationError,
        match="latest closed canonical candle",
    ):
        _run(rows)


def test_peer_dataset_binding_must_match_other_symbol_minute15():
    rows = [_evaluation("BTCUSDT"), _evaluation("ETHUSDT")]
    rows[0]["peer_symbol"] = "ETHUSDT"
    rows[0]["peer_minute15_binding_sha256"] = "9" * 64
    with pytest.raises(
        rq.CompositeRuntimeRequalificationError,
        match="peer evaluation",
    ):
        _run(rows)

    rows = [_evaluation("BTCUSDT"), _evaluation("ETHUSDT")]
    rows[0]["peer_symbol"] = "ETHUSDT"
    rows[0]["peer_minute15_binding_sha256"] = rows[1]["datasets"]["minute15"]["binding_sha256"]
    result = _run(rows)
    assert rq.verify_requalification(result)["decision"] == "pass"


def test_redigested_runtime_asof_tamper_is_rejected():
    result = _run([_evaluation("BTCUSDT"), _evaluation("ETHUSDT")])
    tampered = deepcopy(result)
    tampered["runtime_as_of_ms"] += rq.TIMEFRAME_STEP_MS["hour4"] * 3
    core = dict(tampered)
    core.pop("requalification_digest", None)
    tampered["requalification_digest"] = rq.digest(core)
    assert rq.verify_requalification(tampered)["decision"] == "reject"


def test_new_3072_bar_source_marker_has_exact_validated_history_and_no_promotion():
    dataset_rows = [
        _evaluation("BTCUSDT"),
        _evaluation("ETHUSDT"),
    ]
    for row in dataset_rows:
        info = row["datasets"]["minute15"]
        info["row_count"] = rq.PAGED_15M_LIMIT
        info["first_open_time_ms"] = (
            info["last_open_time_ms"]
            - (rq.PAGED_15M_LIMIT - 1) * rq.TIMEFRAME_STEP_MS["minute15"]
        )
    result = _run(dataset_rows)
    assert result["fresh_history_limit_per_timeframe"] == 3072
    assert result["decision"] == "QUALIFIED_FOR_REVIEW"
    assert result["automatic_strategy_promotion"] is False
    assert result["paper_execution_authority"] is False
    assert rq.verify_requalification(result)["decision"] == "pass"

    # A redigested marker claim without physical 3072-bar data fails closed.
    bad = deepcopy(result)
    bad["evaluations"][0]["datasets"]["minute15"]["row_count"] = 1000
    bad["evaluations"][0]["datasets"]["minute15"]["first_open_time_ms"] = (
        bad["evaluations"][0]["datasets"]["minute15"]["last_open_time_ms"]
        - 999 * rq.TIMEFRAME_STEP_MS["minute15"]
    )
    bad["evaluations_digest"] = rq.digest(bad["evaluations"])
    core = dict(bad)
    core.pop("requalification_digest", None)
    bad["requalification_digest"] = rq.digest(core)
    assert rq.verify_requalification(bad)["decision"] == "reject"


def test_existing_1000_bar_legacy_evidence_remains_verifiable():
    result = _run([_evaluation("BTCUSDT"), _evaluation("ETHUSDT")])
    assert result["fresh_history_limit_per_timeframe"] == rq.HISTORY_LIMIT == 1000
    assert rq.verify_requalification(result)["decision"] == "pass"
