from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from market_data_provenance_manifest import build_provenance_manifest
import phase5_data_binding as data_binding
import phase5_shadow_migration as migration
import phase5_strategy_factory as factory

GATE9_SCHEMA = "nexus.phase5-gate9-evidence.v1"
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
START = 1_640_995_200_000
ENDPOINT = "/v5/market/kline?category=spot&symbol=BTCUSDT&interval=15"
PROOF_SUITES = [
    "tests/test_phase5_mission_contract.py",
    "tests/test_phase5_state_store.py",
    "tests/test_phase5_attempts.py",
    "tests/test_phase5_verification.py",
    "tests/test_phase5_worker_policy.py",
    "tests/test_phase5_data_binding.py",
    "tests/test_phase5_strategy_factory.py",
    "tests/test_phase5_gate8_chaos.py",
    "tests/test_phase5_gate9_e2e.py",
]


class Gate9Error(ValueError):
    pass


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _source_sha(value: str) -> str:
    if not isinstance(value, str) or not _SHA_RE.fullmatch(value.lower()):
        raise Gate9Error("source_sha must be a 40-character Git SHA")
    return value.lower()


def _dataset() -> dict[str, Any]:
    rows = [
        {"open_time_ms": START, "open": "47000", "high": "47100", "low": "46900", "close": "47050", "volume": "12.5"},
        {"open_time_ms": START + 900_000, "open": "47050", "high": "47200", "low": "47000", "close": "47150", "volume": "10.0"},
    ]
    manifest = build_provenance_manifest(
        source="Bybit", market_type="spot", source_symbol="BTCUSDT", canonical_symbol="BTC/USDT",
        timeframe="15m", endpoint_contract=ENDPOINT, mapping_policy_version="1.0.0",
        retrieval_start_ms=START, retrieval_end_ms=START + 900_000, candles=rows,
    )
    return data_binding.bind_canonical_dataset(manifest, rows)


def run_gate9(source_sha: str) -> dict[str, Any]:
    source_sha = _source_sha(source_sha)
    dataset = _dataset()
    experiment = factory.build_experiment(
        dataset,
        hypothesis="bounded momentum evidence remains testable after conservative cost stress",
        family="momentum",
        strategy_version="phase5-gate9-momentum-v1",
        config={"lookback": 20, "threshold": 1.2},
        code_sha=source_sha,
        cost_model={"fee_bps": 10, "slippage_bps": 5, "funding_bps": 0},
        kill_criteria={
            "min_robustness_score": 0.60,
            "max_cost_stress_loss_pct": 12.0,
            "min_walk_forward_score": 0.55,
            "min_oos_score": 0.55,
            "max_drawdown_pct": 25.0,
            "min_regime_pass_ratio": 0.60,
            "max_failure_mode_severity": 0.40,
        },
    )
    qualification_input = {
        "evidence_refs": ["phase5-parent:#583", "research-input:#45", "canonical-mapping:btc-usdt-spot-minute15-v1"],
        "hypothesis_supported": True,
        "preregistered": True,
        "robustness_score": 0.40,
        "cost_stress_loss_pct": 6.0,
        "walk_forward_score": 0.70,
        "oos_score": 0.68,
        "max_drawdown_pct": 18.0,
        "regime_pass_ratio": 0.75,
        "failure_mode_severity": 0.20,
        "benchmark_score": 0.62,
        "uncertainty_width": 0.12,
        "survivorship_control": True,
        "lookahead_control": True,
        "data_snooping_control": True,
    }
    first = factory.qualify(dataset, experiment, qualification_input)
    second = factory.qualify(dataset, experiment, dict(qualification_input))
    if first != second or first["status"] != "killed" or first["kill_reasons"] != ["ROBUSTNESS_KILL"]:
        raise Gate9Error("deterministic Strategy Factory kill replay failed")

    shadow = migration.build_shadow_report(
        {"mission": "phase5", "decision": "paper-only", "next": "bounded-task"},
        {"mission": "phase5", "decision": "paper-only", "next": "bounded-task"},
        {name: True for name in migration.CHAOS_CASES},
    )
    migration.validate_shadow_report(shadow)
    if not shadow["cutover_ready"]:
        raise Gate9Error("shadow migration is not cutover ready")

    core = {
        "schema_version": GATE9_SCHEMA,
        "source_sha": source_sha,
        "paper_only": True,
        "authority": {
            "live_execution_allowed": False,
            "private_exchange_credentials_allowed": False,
            "withdrawals_allowed": False,
            "production_promotion_allowed": False,
            "billing_changes_allowed": False,
            "signing_authority_allowed": False,
            "l4_owner_required": True,
            "deterministic_risk_final_authority": True,
        },
        "gate7": {
            "dataset_binding_sha256": dataset["binding_sha256"],
            "registry_version": dataset["registry_version"],
            "mapping_id": dataset["mapping_id"],
            "instrument": dataset["instrument"],
            "market": dataset["market"],
            "source": dataset["source"],
            "source_role": dataset["source_role"],
            "timeframe": dataset["manifest_timeframe"],
            "interval": dataset["interval"],
            "category": dataset["category"],
            "finality": dataset["finality"],
        },
        "gate6": {
            "experiment_id": experiment["experiment_id"],
            "strategy_version": experiment["strategy_version"],
            "family": experiment["family"],
            "status": first["status"],
            "kill_reasons": first["kill_reasons"],
            "qualification_digest": first["qualification_digest"],
            "replay_identical": True,
            "profitability_claim": False,
        },
        "gate8": {
            "shadow_report_digest": shadow["report_digest"],
            "exact_parity": shadow["exact_parity"],
            "cutover_ready": shadow["cutover_ready"],
            "legacy_mode": shadow["legacy_mode"],
            "durable_supervisor_mode": shadow["durable_supervisor_mode"],
            "chaos": shadow["chaos"],
        },
        "proof_suites": PROOF_SUITES,
    }
    return {**core, "evidence_digest": _digest(core)}


def validate_gate9_evidence(evidence: dict[str, Any], *, expected_source_sha: str) -> None:
    if not isinstance(evidence, dict) or evidence.get("schema_version") != GATE9_SCHEMA:
        raise Gate9Error("Gate 9 evidence schema mismatch")
    if evidence.get("source_sha") != _source_sha(expected_source_sha):
        raise Gate9Error("Gate 9 source SHA mismatch")
    if evidence.get("paper_only") is not True:
        raise Gate9Error("Gate 9 evidence widened authority")
    if evidence.get("gate6", {}).get("status") not in {"paper_candidate", "killed"}:
        raise Gate9Error("Gate 6 outcome is not terminal")
    if evidence.get("gate7", {}).get("source_role") != "primary":
        raise Gate9Error("Gate 7 source is not canonical primary")
    if evidence.get("gate8", {}).get("cutover_ready") is not True:
        raise Gate9Error("Gate 8 is not cutover ready")
    core = dict(evidence)
    claimed = core.pop("evidence_digest", None)
    if not isinstance(claimed, str) or len(claimed) != 64 or _digest(core) != claimed:
        raise Gate9Error("Gate 9 evidence digest mismatch")
