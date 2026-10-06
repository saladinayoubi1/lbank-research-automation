"""Lightweight execution contract for fresh composite VAL-40 replay.

The full self-contained Research proof stays in the durable coordinator store.
Only this bounded contract is dispatched to a numerical worker.  The contract
can be created only from a standalone-verified composite candidate and carries
zero qualification, registry, Runtime/Paper, promotion, or Live authority.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any

from nexus_composite_validation_candidate import verify_candidate

SCHEMA = "nexus.composite-val40-execution-contract.v1"
VERIFY_SCHEMA = "nexus.composite-val40-execution-contract-verification.v1"
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class CompositeVal40ContractError(ValueError):
    pass


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise CompositeVal40ContractError("execution contract is not canonical JSON") from exc


def digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def build_execution_contract(
    candidate: Mapping[str, Any],
    verification: Mapping[str, Any],
) -> dict[str, Any]:
    computed = verify_candidate(candidate)
    if computed.get("decision") != "pass" or dict(verification) != computed:
        raise CompositeVal40ContractError("candidate proof verification rejected")
    if (
        candidate.get("decision") != "FORWARD_TO_VAL40"
        or candidate.get("eligible_for_fresh_runtime_requalification") is not True
        or candidate.get("requires_fresh_runtime_data") is not True
        or candidate.get("paper_only") is not True
        or candidate.get("candidate_state_created") is not False
        or candidate.get("qualification_authority") is not False
        or candidate.get("registry_mutation_authority") is not False
        or candidate.get("promotion_authority") is not False
        or candidate.get("paper_execution_authority") is not False
        or candidate.get("automatic_strategy_promotion") is not False
        or candidate.get("live_trading_authority") is not False
        or not isinstance(candidate.get("strategy_config"), Mapping)
        or not candidate.get("strategy_config")
        or not _HEX64.fullmatch(str(verification.get("verification_digest", "")))
    ):
        raise CompositeVal40ContractError("candidate is not eligible for bounded execution")
    core = {
        "schema_version": SCHEMA,
        "system_map_node": "VAL-40",
        "candidate_digest": candidate["candidate_digest"],
        "candidate_verification_digest": verification["verification_digest"],
        "research_task_id": candidate["research_task_id"],
        "candidate_source_sha": candidate["source_sha"],
        "mechanism": candidate["mechanism"],
        "timeframe": candidate["timeframe"],
        "strategy_config": dict(candidate["strategy_config"]),
        "config_fingerprint": candidate["config_fingerprint"],
        "requires_fresh_runtime_data": True,
        "no_minimum_trade_count_gate": True,
        "research_only": True,
        "paper_only": True,
        "qualification_authority": False,
        "registry_mutation_authority": False,
        "runtime_activation_authority": False,
        "promotion_authority": False,
        "paper_execution_authority": False,
        "automatic_strategy_promotion": False,
        "live_trading_authority": False,
    }
    return {**core, "execution_contract_digest": digest(core)}


def verify_execution_contract(value: Mapping[str, Any]) -> dict[str, Any]:
    checks = {"schema": False, "digest": False, "identity": False, "authority": False}
    try:
        core = dict(value)
        claimed = core.pop("execution_contract_digest", None)
        checks["schema"] = (
            core.get("schema_version") == SCHEMA
            and core.get("system_map_node") == "VAL-40"
        )
        checks["digest"] = isinstance(claimed, str) and claimed == digest(core)
        config = core.get("strategy_config")
        checks["identity"] = bool(
            _HEX64.fullmatch(str(core.get("candidate_digest", "")))
            and _HEX64.fullmatch(str(core.get("candidate_verification_digest", "")))
            and isinstance(core.get("research_task_id"), str)
            and core.get("research_task_id", "").startswith("P7-RESEARCH-COMPOSITE-")
            and _SHA40.fullmatch(str(core.get("candidate_source_sha", "")))
            and isinstance(core.get("mechanism"), str) and bool(core.get("mechanism"))
            and isinstance(core.get("timeframe"), str) and bool(core.get("timeframe"))
            and isinstance(config, Mapping) and bool(config)
            and config.get("mechanism") == core.get("mechanism")
            and _HEX64.fullmatch(str(config.get("factory_contract_digest", "")))
            and _HEX64.fullmatch(str(core.get("config_fingerprint", "")))
        )
        checks["authority"] = bool(
            core.get("requires_fresh_runtime_data") is True
            and core.get("no_minimum_trade_count_gate") is True
            and core.get("research_only") is True
            and core.get("paper_only") is True
            and core.get("qualification_authority") is False
            and core.get("registry_mutation_authority") is False
            and core.get("runtime_activation_authority") is False
            and core.get("promotion_authority") is False
            and core.get("paper_execution_authority") is False
            and core.get("automatic_strategy_promotion") is False
            and core.get("live_trading_authority") is False
        )
    except Exception:
        pass
    decision = "pass" if all(checks.values()) else "reject"
    result = {
        "schema_version": VERIFY_SCHEMA,
        "decision": decision,
        "checks": checks,
        "execution_contract_digest": value.get("execution_contract_digest"),
    }
    return {**result, "verification_digest": digest(result)}
