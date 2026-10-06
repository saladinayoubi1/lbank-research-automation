from __future__ import annotations

from copy import deepcopy

import numpy as np
import pandas as pd
import pytest

import nexus_composite_runtime_requalification as requal
from nexus_composite_runtime_requalification import (
    CompositeRuntimeRequalificationError,
    build_requalification,
    digest,
    verify_requalification,
)
from product_research_runtime import ProductResearchError

SOURCE = "a" * 40
CANDIDATE_SOURCE = "b" * 40
MECHANISM = "factory_gen_deep_drawdown_recovery_vwap_reclaim"
CONTRACT = "24461a4812f4e6a7dca2355b3308764b6978e3343bb21591a73e916a9b1f0e70"
FINGERPRINT = "b7afd52025f0ba4e1dedc31b31cc316ebed67c1df388c6b7769a0931df9c5933"
NOW = 1_800_000_000_000


def _candidate():
    return {
        "schema_version": "nexus.composite-validation-candidate.v2",
        "proposal_kind": "composite_mechanism",
        "decision": "FORWARD_TO_VAL40",
        "eligible_for_fresh_runtime_requalification": True,
        "requires_fresh_runtime_data": True,
        "source_sha": CANDIDATE_SOURCE,
        "mechanism": MECHANISM,
        "strategy_config": {
            "mechanism": MECHANISM,
            "risk_variant": 0,
            "entry_model": "closed_4h_1h_15m_next_open",
            "factory_contract_digest": CONTRACT,
        },
        "config_fingerprint": FINGERPRINT,
        "candidate_state_created": False,
        "qualification_authority": False,
        "registry_mutation_authority": False,
        "promotion_authority": False,
        "paper_execution_authority": False,
        "automatic_strategy_promotion": False,
        "research_only": True,
        "paper_only": True,
        "live_trading_authority": False,
        "candidate_digest": "c" * 64,
    }


def _candidate_verification(candidate):
    return {
        "schema_version": "nexus.composite-validation-candidate-verification.v2",
        "decision": "pass",
        "checks": {"all": True},
        "candidate_digest": candidate["candidate_digest"],
        "verification_digest": "d" * 64,
    }


def _evaluation(*, positive=True, activity=True):
    evaluations = []
    for index, symbol in enumerate(requal.SYMBOLS):
        windows = {
            timeframe: {
                "binding_sha256": format(index + pos + 1, "x")[-1] * 64,
                "last_open_time_ms": NOW - pos * 900_000,
                "row_count": requal.LIMITS[timeframe],
            }
            for pos, timeframe in enumerate(requal.TIMEFRAMES)
        }
        profiles = {
            "conservative": {
                "net_return_pct": 0.12 if positive else -0.01,
                "max_drawdown_pct": 0.3,
                "closed_round_trips": 1 if activity else 0,
                "halted_on_drawdown": False,
                "fee_bps": requal.ENTRY_FEE_BPS,
                "slippage_bps": requal.ENTRY_SLIP_BPS,
                "trade_count_limit": None,
            },
            "stress": {
                "net_return_pct": 0.04 if positive else -0.02,
                "max_drawdown_pct": 0.4,
                "closed_round_trips": 1 if activity else 0,
                "halted_on_drawdown": False,
                "fee_bps": requal.STRESS_FEE_BPS,
                "slippage_bps": requal.STRESS_SLIP_BPS,
                "trade_count_limit": None,
            },
        }
        reasons = []
        if not activity:
            reasons.append("ZERO_ACTIVITY")
        if not positive:
            reasons.append("NON_POSITIVE_FRESH_RUNTIME_PROFILE")
        evaluations.append({
            "symbol": symbol,
            "timeframe": "minute15_with_completed_1h_4h",
            "dataset_windows": windows,
            "profiles": profiles,
            "total_closed_round_trips": 2 if activity else 0,
            "qualification_status": "paper_candidate" if not reasons else "killed",
            "kill_reasons": reasons,
            "deterministic_replay_verified": True,
            "closed_candle_finality_verified": True,
            "data_origin": "canonical_public_bybit_runtime",
            "paper_only": True,
            "live_trading_authority": False,
            "paper_execution_started": False,
            "automatic_strategy_promotion": False,
        })
    return {
        "runtime_anchor_ms": NOW,
        "mechanism_contract_digest": CONTRACT,
        "peer_required": False,
        "evaluations": evaluations,
        "deterministic_replay_verified": True,
    }


def _patch_candidate_verifier(monkeypatch, candidate):
    verification = _candidate_verification(candidate)
    monkeypatch.setattr(
        requal,
        "verify_candidate",
        lambda value: verification
        if value == candidate
        else {"decision": "reject"},
    )
    return verification


def test_positive_fresh_runtime_window_qualifies_only_for_review(monkeypatch):
    candidate = _candidate()
    verification = _patch_candidate_verifier(monkeypatch, candidate)
    result = build_requalification(
        candidate,
        verification,
        source_sha=SOURCE,
        now_ms=NOW,
        evaluator=lambda *_: _evaluation(),
    )
    assert result["verdict"] == "QUALIFIED_FOR_REVIEW"
    assert result["qualification_authority"] is False
    assert result["paper_execution_started"] is False
    assert result["live_trading_authority"] is False
    assert all(
        row["profiles"]["conservative"]["closed_round_trips"] == 1
        for row in result["runtime_evaluations"]
    )
    assert verify_requalification(result)["decision"] == "pass"


@pytest.mark.parametrize(
    ("positive", "activity", "reason"),
    [
        (False, True, "NON_POSITIVE_FRESH_RUNTIME_PROFILE"),
        (True, False, "ZERO_ACTIVITY"),
    ],
)
def test_fresh_runtime_rejects_negative_or_zero_activity_without_min_trade_gate(
    monkeypatch, positive, activity, reason
):
    candidate = _candidate()
    verification = _patch_candidate_verifier(monkeypatch, candidate)
    result = build_requalification(
        candidate,
        verification,
        source_sha=SOURCE,
        now_ms=NOW,
        evaluator=lambda *_: _evaluation(
            positive=positive, activity=activity
        ),
    )
    assert result["verdict"] == "REJECTED"
    assert all(
        reason in row["kill_reasons"]
        for row in result["runtime_evaluations"]
    )
    assert all(
        profile["trade_count_limit"] is None
        for row in result["runtime_evaluations"]
        for profile in row["profiles"].values()
    )


def test_runtime_data_failure_waits_without_authority(monkeypatch):
    candidate = _candidate()
    verification = _patch_candidate_verifier(monkeypatch, candidate)

    def fail(*_):
        raise ProductResearchError("canonical public dataset unavailable")

    result = build_requalification(
        candidate,
        verification,
        source_sha=SOURCE,
        now_ms=NOW,
        evaluator=fail,
    )
    assert result["verdict"] == "BLOCKED_RUNTIME_DATA"
    assert result["runtime_evaluations"] == []
    assert result["blocked"]["error_type"] == "ProductResearchError"
    assert result["live_trading_authority"] is False


def test_candidate_verification_or_contract_drift_fails_closed(monkeypatch):
    candidate = _candidate()
    verification = _candidate_verification(candidate)
    monkeypatch.setattr(
        requal, "verify_candidate", lambda _: {"decision": "reject"}
    )
    with pytest.raises(
        CompositeRuntimeRequalificationError, match="candidate verification"
    ):
        build_requalification(
            candidate,
            verification,
            source_sha=SOURCE,
            now_ms=NOW,
            evaluator=lambda *_: _evaluation(),
        )

    candidate = _candidate()
    verification = _patch_candidate_verifier(monkeypatch, candidate)
    candidate["strategy_config"]["factory_contract_digest"] = "0" * 64
    with pytest.raises(
        CompositeRuntimeRequalificationError, match="factory contract"
    ):
        build_requalification(
            candidate,
            verification,
            source_sha=SOURCE,
            now_ms=NOW,
            evaluator=lambda *_: _evaluation(),
        )


def test_requalification_tamper_is_rejected(monkeypatch):
    candidate = _candidate()
    verification = _patch_candidate_verifier(monkeypatch, candidate)
    result = build_requalification(
        candidate,
        verification,
        source_sha=SOURCE,
        now_ms=NOW,
        evaluator=lambda *_: _evaluation(),
    )
    tampered = deepcopy(result)
    tampered["runtime_evaluations"][0]["dataset_windows"]["minute15"][
        "binding_sha256"
    ] = "not-a-digest"
    core = dict(tampered)
    core.pop("requalification_digest")
    tampered["requalification_digest"] = digest(core)
    assert verify_requalification(tampered)["decision"] == "reject"


def test_default_evaluator_uses_exact_bounded_windows_and_existing_engine(
    monkeypatch,
):
    candidate = _candidate()
    calls = []

    class FakeRuntime:
        def __init__(self, *_args, **kwargs):
            assert kwargs["source_sha"] == SOURCE
            assert kwargs["clock_ms"]() == NOW

        def fetch_dataset(self, *, symbol, timeframe, limit):
            calls.append((symbol, timeframe, limit))
            return {
                "_symbol": symbol,
                "_timeframe": timeframe,
                "_limit": limit,
            }

    def fake_frame(dataset):
        limit = dataset["_limit"]
        step = {
            "minute15": 900_000,
            "hour1": 3_600_000,
            "hour4": 14_400_000,
        }[dataset["_timeframe"]]
        frame = pd.DataFrame({
            "timestamp": pd.to_datetime(
                [NOW - (limit - i) * step for i in range(limit)],
                unit="ms",
                utc=True,
            ),
            "open": [100.0] * limit,
            "high": [101.0] * limit,
            "low": [99.0] * limit,
            "close": [100.0] * limit,
            "volume": [10.0] * limit,
        })
        artifact = {
            "row_count": limit,
            "binding_sha256": digest({
                "symbol": dataset["_symbol"],
                "timeframe": dataset["_timeframe"],
            }),
            "rows": [{"open_time_ms": NOW - step}],
        }
        return artifact, frame

    monkeypatch.setattr(requal, "ProductResearchRuntime", FakeRuntime)
    monkeypatch.setattr(requal, "canonical_ohlcv_frame", fake_frame)
    monkeypatch.setattr(
        requal,
        "build_features",
        lambda frames, peer_15m=None: frames["minute15"],
    )
    monkeypatch.setattr(
        requal,
        "signal_for",
        lambda frame, config: np.zeros(len(frame), dtype=bool),
    )
    monkeypatch.setattr(
        requal,
        "backtest",
        lambda frame, signals, *, fee_bps, slip_bps, risk_variant: {
            "net_return_pct": 0.1,
            "max_drawdown_pct": 0.1,
            "closed_round_trips": 1,
            "halted_on_drawdown": False,
            "fee_bps": fee_bps,
            "slippage_bps": slip_bps,
            "trade_count_limit": None,
        },
    )

    result = requal._default_evaluator(candidate, SOURCE, NOW)
    assert result["peer_required"] is False
    assert sorted(calls) == sorted(
        (symbol, timeframe, requal.LIMITS[timeframe])
        for symbol in requal.SYMBOLS
        for timeframe in requal.TIMEFRAMES
    )
    assert result["deterministic_replay_verified"] is True
