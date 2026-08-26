import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from cross_timeframe_context import (
    FEATURE_VERSION,
    REGIME_SCHEMA_VERSION,
    TAXONOMY_VERSION,
    TIMEFRAME_MS,
    build_cross_timeframe_context,
)
from nexus_regime_strategy_selector import (
    RegimeStrategySelectorError,
    select_strategy_mix,
)


ROOT = Path(__file__).resolve().parents[1]
AS_OF = 2_000_000_000


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def producer_evidence(timeframe):
    record = {
        "open_time_ms": AS_OF - TIMEFRAME_MS[timeframe],
        "regime": "TREND_UP",
        "confidence": "0.90",
        "reason_codes": ["TEST_PRODUCER_CONTRACT"],
        "liquidity_state": "ACTIVE",
        "features": {
            "return_5": "0.01", "return_20": "0.02",
            "mean_abs_return_20": "0.001", "mean_range_pct_20": "0.002",
            "volume_ratio_20": "1.1",
        },
    }
    core = {
        "schema_version": REGIME_SCHEMA_VERSION,
        "feature_version": FEATURE_VERSION,
        "taxonomy_version": TAXONOMY_VERSION,
        "dataset_binding_sha256": digest(f"dataset-{timeframe}"),
        "instrument": "BTCUSDT",
        "timeframe": timeframe,
        "source": "bybit-public",
        "finality": "closed_only",
        "paper_only": True,
        "lookahead_control": True,
        "records": [record],
        "current_regime": record,
    }
    return {**core, "evidence_sha256": digest(core)}


def policy():
    return json.loads((ROOT / "config/nexus-regime-strategy-policy-v1.json").read_text())


def context(alignment="ALIGNED_UP", confidence="0.90", liquidity="ACTIVE"):
    regimes = {
        "ALIGNED_UP": ["TREND_UP", "TREND_UP", "TREND_UP"],
        "ALIGNED_DOWN": ["TREND_DOWN", "TREND_DOWN", "TREND_DOWN"],
        "RANGE_DOMINANT": ["RANGE", "RANGE", "RANGE"],
        "VOLATILITY_ALERT": ["HIGH_VOLATILITY", "RANGE", "TREND_UP"],
        "MIXED": ["TREND_UP", "RANGE", "TREND_DOWN"],
    }[alignment]
    rows = []
    as_of = 2_000_000_000
    for index, (timeframe, step, regime) in enumerate(
        zip(("15m", "1h", "4h"), (900_000, 3_600_000, 14_400_000), regimes)
    ):
        available = as_of - step
        rows.append({
            "timeframe": timeframe,
            "open_time_ms": available - step,
            "available_at_ms": available,
            "regime": regime,
            "confidence": confidence,
            "liquidity_state": liquidity,
            "reason_codes": [f"TEST_{index}"],
            "dataset_binding_sha256": hashlib.sha256(f"dataset-{index}".encode()).hexdigest(),
            "regime_evidence_sha256": hashlib.sha256(f"regime-{index}".encode()).hexdigest(),
        })
    core = {
        "schema_version": "nexus.phase7-cross-timeframe-context.v1",
        "context_version": "nexus.cross-timeframe-context.v1",
        "as_of_ms": as_of,
        "instrument": "BTCUSDT",
        "source": "bybit-public",
        "paper_only": True,
        "lookahead_control": True,
        "alignment": alignment,
        "confidence": confidence,
        "reason_codes": [f"MTF_{alignment}"],
        "timeframes": rows,
    }
    return {**core, "context_sha256": digest(core)}


def candidate(family, health="HEALTHY", lifecycle="PAPER"):
    return {
        "family": family,
        "strategy_id": f"{family}-paper-v1",
        "strategy_version": "1.0.0",
        "lifecycle_state": lifecycle,
        "health_state": health,
        "record_digest": hashlib.sha256(f"record-{family}".encode()).hexdigest(),
        "health_digest": hashlib.sha256(f"health-{family}-{health}".encode()).hexdigest(),
        "paper_only": True,
        "live_trading_authority": False,
    }


def all_candidates():
    return [candidate("momentum"), candidate("trend_breakout"), candidate("mean_reversion")]


def select(ctx, candidates=None, selected_policy=None):
    return select_strategy_mix(
        context=ctx,
        candidates=all_candidates() if candidates is None else candidates,
        policy=policy() if selected_policy is None else selected_policy,
        source_sha="a" * 40,
    )


def weights(result):
    return {row["family"]: row["weight"] for row in result["allocations"]}


def test_trend_up_prefers_momentum_and_breakout():
    result = select(context("ALIGNED_UP"))
    assert result["mode"] == "ACTIVE"
    assert weights(result) == {
        "momentum": "0.450000", "trend_breakout": "0.450000", "mean_reversion": "0.100000"
    }
    assert result["cash_weight"] == "0.000000"


def test_real_cross_timeframe_producer_contract_is_accepted():
    produced = build_cross_timeframe_context(
        [producer_evidence("4h"), producer_evidence("15m"), producer_evidence("1h")],
        as_of_ms=AS_OF,
    )
    result = select(produced)
    assert produced["alignment"] == "ALIGNED_UP"
    assert result["alignment"] == produced["alignment"]
    assert result["context_sha256"] == produced["context_sha256"]


def test_range_prefers_mean_reversion():
    result = select(context("RANGE_DOMINANT"))
    assert weights(result)["mean_reversion"] == "0.750000"
    assert result["alignment"] == "RANGE_DOMINANT"


@pytest.mark.parametrize("alignment", ["VOLATILITY_ALERT", "MIXED"])
def test_ambiguous_or_high_volatility_preserves_cash(alignment):
    result = select(context(alignment))
    assert result["mode"] == "PRESERVE_CASH"
    assert result["allocations"] == []
    assert result["cash_weight"] == "1.000000"


def test_low_confidence_preserves_cash():
    result = select(context("ALIGNED_UP", confidence="0.40"))
    assert result["mode"] == "PRESERVE_CASH"
    assert "CONTEXT_CONFIDENCE_BELOW_POLICY" in result["reason_codes"]


def test_thin_liquidity_preserves_cash():
    result = select(context("RANGE_DOMINANT", liquidity="THIN"))
    assert result["mode"] == "PRESERVE_CASH"
    assert "LIQUIDITY_PRESERVE_CASH" in result["reason_codes"]


def test_quarantined_family_is_excluded_without_redistribution():
    candidates = all_candidates()
    candidates[0] = candidate("momentum", health="QUARANTINED")
    result = select(context("ALIGNED_UP"), candidates)
    assert "momentum" not in weights(result)
    assert result["cash_weight"] == "0.450000"
    assert "FAMILY_UNHEALTHY_MOMENTUM" in result["reason_codes"]


def test_watch_state_receives_policy_haircut():
    candidates = all_candidates()
    candidates[1] = candidate("trend_breakout", health="WATCH")
    result = select(context("ALIGNED_UP"), candidates)
    assert weights(result)["trend_breakout"] == "0.225000"
    assert result["cash_weight"] == "0.225000"
    assert "WATCH_HAIRCUT_TREND_BREAKOUT" in result["reason_codes"]


def test_candidate_must_already_be_in_paper():
    candidates = all_candidates()
    candidates[2] = candidate("mean_reversion", lifecycle="CANDIDATE")
    result = select(context("RANGE_DOMINANT"), candidates)
    assert "mean_reversion" not in weights(result)
    assert result["cash_weight"] == "0.750000"


def test_tampered_context_fails_closed():
    ctx = context("ALIGNED_UP")
    ctx["alignment"] = "RANGE_DOMINANT"
    with pytest.raises(RegimeStrategySelectorError, match="contradicts"):
        select(ctx)


def test_digest_valid_but_contradictory_alignment_fails_closed():
    ctx = context("ALIGNED_UP")
    for row in ctx["timeframes"]:
        row["regime"] = "RANGE"
    unsigned = dict(ctx)
    unsigned.pop("context_sha256")
    ctx["context_sha256"] = digest(unsigned)
    with pytest.raises(RegimeStrategySelectorError, match="contradicts"):
        select(ctx)


def test_all_three_canonical_timeframes_are_required():
    ctx = context("ALIGNED_UP")
    ctx["timeframes"] = ctx["timeframes"][:2]
    unsigned = dict(ctx)
    unsigned.pop("context_sha256")
    ctx["context_sha256"] = digest(unsigned)
    with pytest.raises(RegimeStrategySelectorError, match="all three"):
        select(ctx)


def test_digest_valid_but_stale_context_fails_closed():
    ctx = context("ALIGNED_UP")
    ctx["timeframes"][0]["available_at_ms"] -= 1_800_001
    unsigned = dict(ctx)
    unsigned.pop("context_sha256")
    ctx["context_sha256"] = digest(unsigned)
    with pytest.raises(RegimeStrategySelectorError, match="stale"):
        select(ctx)


def test_unknown_context_version_fails_closed():
    ctx = context("ALIGNED_UP")
    ctx["context_version"] = "nexus.cross-timeframe-context.v0"
    unsigned = dict(ctx)
    unsigned.pop("context_sha256")
    ctx["context_sha256"] = digest(unsigned)
    with pytest.raises(RegimeStrategySelectorError, match="context version"):
        select(ctx)


def test_authority_widening_policy_is_rejected():
    selected_policy = policy()
    selected_policy["live_trading_authority"] = True
    with pytest.raises(RegimeStrategySelectorError, match="widens authority"):
        select(context(), selected_policy=selected_policy)


def test_duplicate_family_is_rejected():
    candidates = [candidate("momentum"), candidate("momentum")]
    with pytest.raises(RegimeStrategySelectorError, match="duplicate candidate family"):
        select(context(), candidates)


def test_selection_is_deterministic_and_proposal_only():
    first = select(context("ALIGNED_DOWN"))
    second = select(context("ALIGNED_DOWN"))
    assert first == second
    assert first["selection_digest"] == second["selection_digest"]
    assert first["paper_only"] is True
    assert first["live_trading_authority"] is False
    assert first["automatic_strategy_promotion"] is False
    assert first["deterministic_risk_final_authority"] is True
