"""Audit reviewed mechanism designs against one *exact-run*, source-bound novelty ledger.

Research-only read-only classification. An unrecorded ID is NOT a novel topology,
and training-screened IDs are never relabeled as untested candidates.
No dispatch, Paper/Live admission, or source-data access.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nexus_strategy_research_feedback import (
    _PROVEN_INPUTS, ResearchFeedbackError,
    validate_catalog, validate_evaluated_ledger, validate_trigger,
)

SCHEMA = "nexus.strategy-frontier-ledger-triage.v1"


class NoveltyTriageError(ValueError):
    pass


def _digest(value: Any) -> str:
    try:
        canonical = json.dumps(
            value, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise NoveltyTriageError("non-canonical triage evidence") from exc
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _read(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 2_000_000:
        raise NoveltyTriageError("missing, symlinked or oversized triage source")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (UnicodeError, OSError, ValueError) as exc:
        raise NoveltyTriageError("triage source could not be parsed") from exc
    if not isinstance(value, dict):
        raise NoveltyTriageError("triage source must be a JSON object")
    return value


def audit(
    run: Mapping[str, Any], certificate: Mapping[str, Any],
    ledger: Mapping[str, Any], catalog: Mapping[str, Any],
) -> dict[str, Any]:
    """Structural-ID-only triage, not semantic novelty or candidate qualification."""
    try:
        validate_trigger(run, certificate)
        historical = validate_evaluated_ledger(ledger, certificate)
        reviewed = validate_catalog(catalog)
    except ResearchFeedbackError as exc:
        raise NoveltyTriageError("exact-run ledger, certificate or reviewed catalog invalid") from exc

    # Previous comprehensive screening is not a full backtest. Preserve the
    # important difference: evaluated > training-only screened > design-only.
    evaluated = set(ledger["mechanisms_evaluated"])
    screened = set(ledger.get("frontier_screened_mechanisms", []))
    if not evaluated.issubset(historical) or not screened.issubset(historical):
        raise NoveltyTriageError("evaluated evidence does not reconcile")
    rows: list[dict[str, Any]] = []
    for mechanism in reviewed:
        required = set(mechanism["inputs"])
        missing = sorted(required - _PROVEN_INPUTS)
        ident = mechanism["id"]
        if missing:
            status = "INPUT_PROOF_REQUIRED"
            next_gate = "attest_missing_independent_inputs_before_any_research"
        elif ident in evaluated:
            status = "ALREADY_EVALUATED"
            next_gate = "do_not_replay_previously_evaluated_mechanism"
        elif ident in screened:
            status = "TRAINING_SCREENED"
            next_gate = "inspect_exact_training_screening_evidence_before_requalification"
        else:
            status = "IDENTITY_ABSENT_SEMANTIC_REVIEW_REQUIRED"
            next_gate = "prove_semantic_novelty_against_old_and_generated_topologies"
        rows.append({
            "mechanism_id": ident,
            "structural_fingerprint": mechanism["mechanism_sha256"],
            "status": status,
            "source_inputs": sorted(required),
            "missing_source_proof": missing,
            "registered_in_evaluated_ledger": ident in evaluated,
            "registered_in_training_screen": ident in screened,
            "semantic_novelty_proven": False,
            "independently_backtested_as_this_design": False,
            "qualification_authority": False,
            "dispatch_allowed": False,
            "next_gate": next_gate,
        })
    rows.sort(key=lambda row: row["mechanism_id"])
    categories = (
        "ALREADY_EVALUATED", "TRAINING_SCREENED",
        "IDENTITY_ABSENT_SEMANTIC_REVIEW_REQUIRED", "INPUT_PROOF_REQUIRED",
    )
    counts = {category: sum(r["status"] == category for r in rows) for category in categories}
    if sum(counts.values()) != len(rows):
        raise NoveltyTriageError("incomplete mechanism classification")
    core = {
        "schema": SCHEMA,
        "status": "EXACT_HISTORICAL_LEDGER_TRIAGED_NO_NEW_CANDIDATE",
        "source_run_id": run["id"],
        "source_sha": certificate["source_sha"],
        "certificate_digest": certificate["certificate_digest"],
        "ledger_digest": ledger["ledger_digest"],
        "dataset_semantic_sha256": certificate["dataset_semantic_sha256"],
        "reviewed_catalog_digest": _digest(catalog),
        "historical_ledger_counts": {
            "evaluated_mechanisms": len(evaluated),
            "training_screened_mechanisms": len(screened),
            "evaluated_configuration_fingerprints": len(ledger["config_fingerprints_evaluated"]),
        },
        "reviewed_design_count": len(rows),
        "classification_counts": counts,
        "review_queue": rows,
        "source_scope": "one verified main-workflow historical run, not an all-time global ledger",
        "novel_design_verified": False,
        "new_strategy_proven_profitable": False,
        "automatic_strategy_promotion": False,
        "research_only": True,
        "paper_only": True,
        "live_trading_authority": False,
        "dispatch_allowed": False,
        "next_action": (
            "independently_review_unrecorded_semantic_topologies_and_test_only_one_"
            "genuinely_distinct_causal_mechanism_with_fee_and_slippage_stress"
        ),
    }
    return {**core, "audit_sha256": _digest(core)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--certificate", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--reviewed-catalog", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    value = audit(
        _read(args.run), _read(args.certificate),
        _read(args.ledger), _read(args.reviewed_catalog),
    )
    if args.output.resolve() in {
        args.run.resolve(), args.certificate.resolve(),
        args.ledger.resolve(), args.reviewed_catalog.resolve(),
    }:
        raise NoveltyTriageError("cannot overwrite input evidence")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    target = args.output.with_suffix(args.output.suffix + ".tmp")
    with target.open("w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(target, args.output)
    print(json.dumps({
        "status": value["status"],
        "source_run_id": value["source_run_id"],
        "reviewed_design_count": value["reviewed_design_count"],
        "classification_counts": value["classification_counts"],
        "audit_sha256": value["audit_sha256"],
        "dispatch_allowed": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
