"""Fail-closed outcome feedback into the existing NEXUS research rotation.

A successful GitHub workflow means code ran, NOT that a candidate qualified.
This adapter trusts only the *exact triggering run's* independently digest-verified
exhaustion certificate. It opens one distinct pre-reviewed hypothesis DESIGN,
never executes generated code, dispatches trades, or changes Paper authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

from nexus_multitimeframe_search_exhaustion import (
    MultiTimeframeExhaustionError,
    verify_certificate,
)

SCHEMA = "nexus.autonomous-research-frontier.v1"
RECEIPT_SCHEMA = "nexus.autonomous-research-feedback.v1"
CATALOG_SCHEMA = "nexus.reviewed-composite-mechanisms.v1"
COMPOSITE_LEDGER_SCHEMA = "nexus.automatic-composite-novelty-ledger.v1"
REQUIRED_WORKFLOW = "NEXUS multi-timeframe strategy discovery"
REQUIRED_STAGE = "nexus_multitimeframe_strategy_discovery"
_ALLOWED_INPUTS = frozenset({
    "closed_spot_ohlcv", "aligned_spot_cross_pair", "verified_signed_trade_flow",
    "verified_spot_l2", "verified_perpetual_funding", "verified_perpetual_oi",
})
# Proven from the existing signed multi-timeframe Bybit OHLCV archive only.
# Additional inputs MUST be independently proven, not inferred from indicators.
_PROVEN_INPUTS = frozenset({"closed_spot_ohlcv", "aligned_spot_cross_pair"})
_TOKEN = re.compile(r"^[a-z][a-z0-9_]{2,95}$")
_HEX40 = re.compile(r"^[a-f0-9]{40}$")
_HEX64 = re.compile(r"^[a-f0-9]{64}$")


class ResearchFeedbackError(ValueError):
    pass


def _digest(value: Any) -> str:
    try:
        b = json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError) as exc:
        raise ResearchFeedbackError("non-canonical research evidence") from exc
    return hashlib.sha256(b).hexdigest()


def _json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 2_000_000:
        raise ResearchFeedbackError("unavailable, linked, or oversized evidence")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeError, ValueError, OSError) as exc:
        raise ResearchFeedbackError("invalid JSON evidence") from exc
    if not isinstance(data, dict):
        raise ResearchFeedbackError("evidence must be an object")
    return data


def empty_frontier() -> dict[str, Any]:
    core = {
        "schema": SCHEMA,
        "research_only": True,
        "paper_only": True,
        "live_trading_authority": False,
        "automatic_strategy_promotion": False,
        "research_cycles": 0,
        "observed_exhaustion_receipts": [],
        "proposed_mechanisms": [],
        "last_feedback": None,
    }
    return {**core, "state_sha256": _digest(core)}


def validate_frontier(value: Mapping[str, Any]) -> dict[str, Any]:
    core = dict(value)
    claimed = core.pop("state_sha256", None)
    if (
        set(core) != set(empty_frontier()) - {"state_sha256"}
        or core["schema"] != SCHEMA
        or core["research_only"] is not True
        or core["paper_only"] is not True
        or core["live_trading_authority"] is not False
        or core["automatic_strategy_promotion"] is not False
        or not isinstance(core["research_cycles"], int)
        or isinstance(core["research_cycles"], bool)
        or core["research_cycles"] < 0
        or not isinstance(core["observed_exhaustion_receipts"], list)
        or not isinstance(core["proposed_mechanisms"], list)
        or len(set(core["observed_exhaustion_receipts"])) != len(core["observed_exhaustion_receipts"])
        or len(set(core["proposed_mechanisms"])) != len(core["proposed_mechanisms"])
        or any(not isinstance(x, str) or not _HEX64.fullmatch(x)
               for key in ("observed_exhaustion_receipts", "proposed_mechanisms")
               for x in core[key])
        or core["research_cycles"] != len(core["observed_exhaustion_receipts"])
        or (core["last_feedback"] is not None and
            (not isinstance(core["last_feedback"], str) or
             not _HEX64.fullmatch(core["last_feedback"])))
        or claimed != _digest(core)
    ):
        raise ResearchFeedbackError("frontier state integrity or authority rejected")
    return dict(value)


def validate_catalog(value: Mapping[str, Any]) -> list[dict[str, Any]]:
    if (
        value.get("schema") != CATALOG_SCHEMA
        or value.get("research_only") is not True
        or value.get("live_trading_authority") is not False
        or value.get("automatic_strategy_promotion") is not False
    ):
        raise ResearchFeedbackError("mechanism catalog lacks reviewed research authority")
    rows = value.get("mechanisms")
    if not isinstance(rows, list) or not rows:
        raise ResearchFeedbackError("no reviewed research mechanisms")
    seen_ids, seen_structures = set(), set()
    validated = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != {
            "id", "hypothesis", "inputs", "context", "entry", "exit", "risk"
        }:
            raise ResearchFeedbackError("invalid mechanism contract")
        if (not isinstance(row["id"], str) or not _TOKEN.fullmatch(row["id"])
                or row["id"] in seen_ids
                or not isinstance(row["hypothesis"], str)
                or not (10 <= len(row["hypothesis"]) <= 1200)):
            raise ResearchFeedbackError("invalid or duplicate mechanism ID")
        if (not isinstance(row["inputs"], list) or not row["inputs"]
                or not set(row["inputs"]).issubset(_ALLOWED_INPUTS)
                or len(set(row["inputs"])) != len(row["inputs"])):
            raise ResearchFeedbackError("unverified input vocabulary")
        for key in ("context", "entry", "exit", "risk"):
            tokens = row[key]
            if (not isinstance(tokens, list) or not tokens or
                    not all(isinstance(t, str) and _TOKEN.fullmatch(t) for t in tokens)
                    or len(set(tokens)) != len(tokens)):
                raise ResearchFeedbackError("invalid causal mechanism topology")
        structure = {k: sorted(row[k]) for k in ("inputs", "context", "entry", "exit", "risk")}
        fingerprint = _digest(structure)
        if fingerprint in seen_structures:
            raise ResearchFeedbackError("parameter/text variant posing as distinct mechanism")
        seen_ids.add(row["id"])
        seen_structures.add(fingerprint)
        validated.append({**row, "mechanism_sha256": fingerprint})
    return validated


def validate_evaluated_ledger(
    value: Mapping[str, Any], certificate: Mapping[str, Any],
) -> set[str]:
    core = dict(value)
    claimed = core.pop("ledger_digest", None)
    mechanisms = core.get("mechanisms_evaluated")
    configs = core.get("config_fingerprints_evaluated")
    base_keys = {
        "schema", "archive_sha256", "mechanisms_evaluated",
        "config_fingerprints_evaluated", "research_only",
        "auto_demo_promotion", "live_enabled",
    }
    frontier_keys = {
        "frontier_screened_mechanisms", "frontier_screening_version",
    }
    screened = core.get("frontier_screened_mechanisms")
    screen_version = core.get("frontier_screening_version")
    has_frontier_extension = bool(set(core) & frontier_keys)
    if (
        not base_keys.issubset(core)
        or not set(core).issubset(base_keys | frontier_keys)
        or (has_frontier_extension and not frontier_keys.issubset(core))
        or core.get("schema") != COMPOSITE_LEDGER_SCHEMA
        or core.get("archive_sha256") != certificate.get("dataset_semantic_sha256")
        or core.get("research_only") is not True
        or core.get("auto_demo_promotion") is not False
        or core.get("live_enabled") is not False
        or not isinstance(mechanisms, list)
        or len(set(mechanisms)) != len(mechanisms)
        or any(not isinstance(x, str) or not _TOKEN.fullmatch(x) for x in mechanisms)
        or not isinstance(configs, list)
        or len(set(configs)) != len(configs)
        or any(not isinstance(x, str) or not _HEX64.fullmatch(x) for x in configs)
        or len(configs) < len(mechanisms)
        or (has_frontier_extension and (
            not isinstance(screened, list)
            or len(set(screened)) != len(screened)
            or any(not isinstance(x, str) or not _TOKEN.fullmatch(x) for x in screened)
            or not isinstance(screen_version, str)
            or not re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,127}", screen_version)
        ))
        or claimed != _digest(core)
    ):
        raise ResearchFeedbackError("evaluated composite ledger integrity or authority rejected")
    return set(mechanisms) | (set(screened) if has_frontier_extension else set())


def validate_trigger(run: Mapping[str, Any], cert: Mapping[str, Any]) -> None:
    if (
        run.get("name") != REQUIRED_WORKFLOW
        or run.get("head_branch") != "main"
        or run.get("event") not in ("workflow_dispatch", "push")
        or run.get("status") != "completed"
        or run.get("conclusion") != "success"
        or not isinstance(run.get("id"), int)
        or isinstance(run.get("id"), bool) or run["id"] < 1
        or not _HEX40.fullmatch(str(run.get("head_sha", "")))
        or not isinstance(run.get("repository"), dict)
        or run["repository"].get("full_name") !=
            "saladinayoubi1/lbank-research-automation"
    ):
        raise ResearchFeedbackError("untrusted or incomplete triggering workflow run")
    try:
        verify_certificate(cert)
    except MultiTimeframeExhaustionError as exc:
        raise ResearchFeedbackError("source exhaustion evidence is unverified") from exc
    if cert["source_sha"] != run["head_sha"]:
        raise ResearchFeedbackError("trigger source differs from exhaustion source")
    if not _HEX64.fullmatch(str(cert.get("dataset_semantic_sha256", ""))):
        raise ResearchFeedbackError("missing certified dataset identity")


def process_feedback(
    run: Mapping[str, Any], certificate: Mapping[str, Any],
    catalog: Mapping[str, Any], previous: Mapping[str, Any] | None = None,
    evaluated_ledger: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any] | None]:
    frontier = validate_frontier(previous if previous is not None else empty_frontier())
    reviewed = validate_catalog(catalog)
    validate_trigger(run, certificate)
    evaluated = (
        validate_evaluated_ledger(evaluated_ledger, certificate)
        if evaluated_ledger is not None else set()
    )
    exhaustion_receipt = _digest({
        "stage": REQUIRED_STAGE,
        "certificate_digest": certificate["certificate_digest"],
        "source_sha": certificate["source_sha"],
        "dataset_semantic_sha256": certificate["dataset_semantic_sha256"],
    })
    prior_evidence = list(frontier["observed_exhaustion_receipts"])
    old_mechanisms = list(frontier["proposed_mechanisms"])
    replay = exhaustion_receipt in prior_evidence
    selected = None
    awaiting_inputs: list[dict[str, Any]] = []
    if not replay:
        for row in reviewed:
            missing = sorted(set(row["inputs"]) - _PROVEN_INPUTS)
            if missing:
                awaiting_inputs.append({"id": row["id"], "missing_inputs": missing})
                continue
            if row["id"] in evaluated:
                continue
            if row["mechanism_sha256"] not in old_mechanisms:
                selected = row
                break

    if replay:
        status = "VERIFIED_EXHAUSTION_REPLAY_NO_NEW_PROPOSAL"
    elif selected is not None:
        status = "NEW_DISTINCT_HYPOTHESIS_DESIGN_ONLY"
    elif awaiting_inputs:
        status = "NEEDS_VERIFIED_DATA_OR_CATALOG_EXPANSION"
    else:
        status = "REVIEWED_MECHANISM_CATALOG_EXHAUSTED"
    proposal = None
    if selected:
        proposal_core = {
            "schema": "nexus.autonomous-hypothesis-design.v1",
            "status": "PREREGISTERED_DESIGN_REQUIRES_IMPLEMENTATION_AND_INDEPENDENT_BACKTEST",
            "run_id": run["id"], "run_source_sha": run["head_sha"],
            "dataset_semantic_sha256": certificate["dataset_semantic_sha256"],
            "exhaustion_certificate_sha256": certificate["certificate_digest"],
            "mechanism": selected,
            "research_only": True, "paper_only": True,
            "live_trading_authority": False, "automatic_strategy_promotion": False,
            "data_claims": sorted(_PROVEN_INPUTS & set(selected["inputs"])),
            "next_step": "build_causal_features_then_run_separate_source_bound_backtests",
        }
        proposal = {**proposal_core, "design_sha256": _digest(proposal_core)}
    receipt_core = {
        "schema": RECEIPT_SCHEMA, "status": status,
        "triggering_run_id": run["id"], "triggering_head_sha": run["head_sha"],
        "stage": REQUIRED_STAGE, "certificate_digest": certificate["certificate_digest"],
        "exhaustion_receipt_sha256": exhaustion_receipt,
        "catalog_sha256": _digest(dict(catalog)),
        "new_hypothesis_sha256": proposal["design_sha256"] if proposal else None,
        "data_blockers": awaiting_inputs,
        "research_only": True, "paper_only": True,
        "live_trading_authority": False, "automatic_strategy_promotion": False,
        "no_backtest_or_qualification_claim": True,
    }
    receipt = {**receipt_core, "feedback_sha256": _digest(receipt_core)}
    state_core = dict(frontier)
    state_core.pop("state_sha256")
    if not replay:
        state_core["observed_exhaustion_receipts"] = prior_evidence + [exhaustion_receipt]
        state_core["research_cycles"] += 1
        if selected:
            state_core["proposed_mechanisms"] = old_mechanisms + [selected["mechanism_sha256"]]
    state_core["last_feedback"] = receipt["feedback_sha256"]
    state = {**state_core, "state_sha256": _digest(state_core)}
    validate_frontier(state)
    return state, receipt, proposal


def _write(path: Path, obj: Mapping[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        raise ResearchFeedbackError("refuse to overwrite prior feedback")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(dict(obj), indent=2, sort_keys=True, allow_nan=False) + "\n",
                   encoding="utf-8")
    tmp.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trigger-run", type=Path, required=True)
    parser.add_argument("--exhaustion-certificate", type=Path, required=True)
    parser.add_argument("--reviewed-mechanisms", type=Path, required=True)
    parser.add_argument("--evaluated-ledger", type=Path, required=True)
    parser.add_argument("--prior-state", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    previous = _json(args.prior_state) if args.prior_state else None
    state, receipt, proposal = process_feedback(
        _json(args.trigger_run), _json(args.exhaustion_certificate),
        _json(args.reviewed_mechanisms), previous,
        _json(args.evaluated_ledger),
    )
    if args.output.exists():
        raise ResearchFeedbackError("feedback output must be newly created")
    args.output.mkdir(parents=True)
    _write(args.output / "frontier-state.json", state)
    _write(args.output / "feedback-receipt.json", receipt)
    if proposal is not None:
        _write(args.output / "candidate-design.json", proposal)
    print(json.dumps({
        "feedback_status": receipt["status"],
        "research_cycles": state["research_cycles"],
        "distinct_designs": len(state["proposed_mechanisms"]),
        "demo_promotions": 0, "live_authority": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
