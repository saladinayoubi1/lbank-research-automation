"""Build one bounded next-generation Multi-Timeframe research manifest from training evidence only.

The refinement planner is deliberately blind to locked/holdout metrics. It may use
only the selected configuration and training summary already produced by the base
Discovery run. The output remains Research/Paper-only and cannot create Candidate,
Paper execution, private-credential use, or Live/L4 authority.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

import nexus_multitimeframe_strategy_discovery as discovery

SCHEMA = "nexus.multitimeframe-training-refinement-plan.v1"
MAX_VARIANTS_PER_FAMILY = 12
CONTROL_VARIANTS_PER_UNTARGETED_FAMILY = 2


class MultiTimeframeRefinementError(RuntimeError):
    pass


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise MultiTimeframeRefinementError("refinement evidence is not canonical JSON") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + f".{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(dict(value), indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, target)


def _stable_unique(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = json.dumps(dict(row), sort_keys=True, separators=(",", ":"), allow_nan=False)
        unique.setdefault(key, dict(row))
    return list(unique.values())


def _scaled_int(value: int, factor: float, *, minimum: int) -> int:
    return max(minimum, int(round(float(value) * float(factor))))


def _round_float(value: float) -> float:
    return float(f"{float(value):.6f}")


def _neighborhood(family: str, config: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return a small deterministic neighborhood; no performance metrics are read here."""
    if family == "momentum":
        lookback = int(config["lookback"])
        threshold = float(config["entry_threshold"])
        rows = [
            {"lookback": _scaled_int(lookback, 1.5, minimum=2), "entry_threshold": _round_float(max(0.0, threshold + 0.0025))},
            {"lookback": _scaled_int(lookback, 2.0, minimum=2), "entry_threshold": _round_float(max(0.0, threshold + 0.0050))},
            {"lookback": _scaled_int(lookback, 3.0, minimum=2), "entry_threshold": _round_float(max(0.0, threshold + 0.0075))},
            {"lookback": _scaled_int(lookback, 4.0, minimum=2), "entry_threshold": _round_float(max(0.0, threshold + 0.0100))},
        ]
    elif family == "trend_breakout":
        entry = int(config["entry_lookback"])
        exit_ = int(config["exit_lookback"])
        rows = [
            {"entry_lookback": _scaled_int(entry, 1.5, minimum=3), "exit_lookback": _scaled_int(exit_, 0.75, minimum=2)},
            {"entry_lookback": _scaled_int(entry, 2.0, minimum=3), "exit_lookback": max(2, exit_)},
            {"entry_lookback": _scaled_int(entry, 2.5, minimum=3), "exit_lookback": _scaled_int(exit_, 1.25, minimum=2)},
            {"entry_lookback": _scaled_int(entry, 3.0, minimum=3), "exit_lookback": _scaled_int(exit_, 1.5, minimum=2)},
            {"entry_lookback": _scaled_int(entry, 4.0, minimum=3), "exit_lookback": _scaled_int(exit_, 2.0, minimum=2)},
        ]
        rows = [row for row in rows if row["exit_lookback"] < row["entry_lookback"]]
    elif family == "mean_reversion":
        lookback = int(config["lookback"])
        entry_z = float(config["entry_z"])
        exit_z = float(config["exit_z"])
        rows = [
            {"lookback": _scaled_int(lookback, 1.5, minimum=5), "entry_z": _round_float(entry_z), "exit_z": _round_float(exit_z - 0.5)},
            {"lookback": _scaled_int(lookback, 1.5, minimum=5), "entry_z": _round_float(entry_z - 0.5), "exit_z": _round_float(exit_z)},
            {"lookback": _scaled_int(lookback, 2.0, minimum=5), "entry_z": _round_float(entry_z), "exit_z": _round_float(exit_z - 0.5)},
            {"lookback": _scaled_int(lookback, 2.0, minimum=5), "entry_z": _round_float(entry_z - 0.5), "exit_z": _round_float(exit_z)},
            {"lookback": _scaled_int(lookback, 3.0, minimum=5), "entry_z": _round_float(entry_z - 0.5), "exit_z": _round_float(exit_z - 0.5)},
            {"lookback": _scaled_int(lookback, 4.0, minimum=5), "entry_z": _round_float(entry_z - 1.0), "exit_z": _round_float(exit_z - 0.5)},
        ]
        rows = [row for row in rows if float(row["entry_z"]) < float(row["exit_z"])]
    else:
        raise MultiTimeframeRefinementError(f"unsupported family: {family}")
    return _stable_unique(rows)


def _training_checks(summary: Mapping[str, Any], training_gate: Mapping[str, Any]) -> dict[str, bool]:
    # Reuse the exact base Discovery gate semantics. The caller passes training data only.
    return discovery._gate(summary, training_gate)  # noqa: SLF001 - same bounded research contract


def _is_training_frontier(summary: Mapping[str, Any], checks: Mapping[str, bool], training_gate: Mapping[str, Any]) -> bool:
    failed = sorted(key for key, passed in checks.items() if not passed)
    if not failed:
        return True
    if failed != ["drawdown"]:
        return False
    maximum = float(training_gate["maximum_drawdown"])
    drawdown = float(summary["worst_drawdown"])
    return math.isfinite(drawdown) and drawdown <= maximum * 1.5


def build_refinement(
    manifest: Mapping[str, Any],
    discovery_result: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    verification = discovery.verify_discovery(discovery_result)
    if verification["decision"] != "pass":
        raise MultiTimeframeRefinementError("base discovery verification failed")
    proposal_count = int(discovery_result.get("research_proposal_count", -1))
    if proposal_count < 0:
        raise MultiTimeframeRefinementError("base discovery proposal count is invalid")
    if discovery_result.get("dataset_archive_sha256") != manifest["dataset"]["archive_sha256"]:
        raise MultiTimeframeRefinementError("discovery dataset does not match manifest")
    if discovery_result.get("symbols") != list(discovery.APPROVED_SYMBOLS):
        raise MultiTimeframeRefinementError("discovery symbol surface mismatch")
    if discovery_result.get("timeframes") != list(discovery.APPROVED_TIMEFRAMES):
        raise MultiTimeframeRefinementError("discovery timeframe surface mismatch")
    if discovery_result.get("families") != list(discovery.APPROVED_FAMILIES):
        raise MultiTimeframeRefinementError("discovery family surface mismatch")

    training_gate = manifest["gates"]["training"]
    targeted: list[dict[str, Any]] = []
    variants_by_family: dict[str, list[dict[str, Any]]] = {
        family: [] for family in discovery.APPROVED_FAMILIES
    }

    # Intentionally do not read cell["locked_profiles"] here. Refinement selection
    # is entirely training-side so the locked holdout remains a one-way validator.
    for cell in discovery_result["cells"] if proposal_count == 0 else []:
        timeframe = str(cell["timeframe"])
        family = str(cell["family"])
        selected_config = dict(cell["selected_config"])
        training_summary = dict(cell["training_summary"])
        checks = _training_checks(training_summary, training_gate)
        failed = sorted(key for key, passed in checks.items() if not passed)
        if not _is_training_frontier(training_summary, checks, training_gate):
            continue
        generated = _neighborhood(family, selected_config)
        if not generated:
            continue
        variants_by_family[family].extend(generated)
        basis_core = {
            "timeframe": timeframe,
            "family": family,
            "selected_config": selected_config,
            "training_summary": training_summary,
            "training_gate_checks": checks,
            "failed_training_gates": failed,
        }
        targeted.append({**basis_core, "basis_digest": _digest(basis_core)})

    final_variants: dict[str, list[dict[str, Any]]] = {}
    targeted_families = {row["family"] for row in targeted}
    for family in discovery.APPROVED_FAMILIES:
        generated = _stable_unique(variants_by_family[family])
        base_rows = [dict(row) for row in manifest["variants"][family]]
        if family in targeted_families:
            # Keep the training winner(s) as controls, then test only the small new neighborhood.
            controls = _stable_unique(
                [dict(row["selected_config"]) for row in targeted if row["family"] == family]
            )
            rows = _stable_unique(controls + generated)
        else:
            rows = base_rows[:CONTROL_VARIANTS_PER_UNTARGETED_FAMILY]
        rows = rows[:MAX_VARIANTS_PER_FAMILY]
        if len(rows) < 2:
            rows = _stable_unique(rows + base_rows)[:2]
        final_variants[family] = rows

    training_basis_core = {
        "base_experiment_id": manifest["experiment_id"],
        "dataset_archive_sha256": manifest["dataset"]["archive_sha256"],
        "training_gate": copy.deepcopy(training_gate),
        "targeted_cells": sorted(targeted, key=lambda row: (row["timeframe"], row["family"])),
        "variants": final_variants,
    }
    training_basis_digest = _digest(training_basis_core)
    should_refine = bool(targeted)

    refined_manifest = copy.deepcopy(dict(manifest))
    refined_manifest["experiment_id"] = (
        f"{manifest['experiment_id']}-training-refinement-{training_basis_digest[:12]}"
    )
    refined_manifest["variants"] = final_variants

    # Validate that the planner cannot widen gates or authority.
    if refined_manifest["gates"] != manifest["gates"]:
        raise MultiTimeframeRefinementError("refinement changed research gates")
    if refined_manifest["authority"] != manifest["authority"]:
        raise MultiTimeframeRefinementError("refinement changed authority")
    if any(len(rows) > MAX_VARIANTS_PER_FAMILY for rows in final_variants.values()):
        raise MultiTimeframeRefinementError("refinement exceeded bounded family grid")

    plan_core = {
        "schema_version": SCHEMA,
        "source_discovery_sha": discovery_result["source_sha"],
        "source_discovery_digest": discovery_result["discovery_digest"],
        "base_research_proposal_count": proposal_count,
        "training_basis_digest": training_basis_digest,
        "selection_basis": "training_only",
        "locked_holdout_used_for_refinement": False,
        "should_refine": should_refine,
        "targeted_cells": training_basis_core["targeted_cells"],
        "variant_counts": {family: len(final_variants[family]) for family in discovery.APPROVED_FAMILIES},
        "research_only": True,
        "paper_only": True,
        "automatic_strategy_promotion": False,
        "automatic_paper_forward_started": False,
        "live_trading_authority": False,
        "private_credentials_used": False,
    }
    plan = {**plan_core, "plan_digest": _digest(plan_core)}
    return plan, refined_manifest


def run(
    manifest_path: str | Path,
    discovery_path: str | Path,
    output_root: str | Path,
) -> dict[str, Any]:
    manifest = discovery.load_manifest(manifest_path)
    try:
        base = json.loads(Path(discovery_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MultiTimeframeRefinementError("base discovery result is unavailable") from exc
    plan, refined_manifest = build_refinement(manifest, base)
    output = Path(output_root)
    _atomic_json(output / "refinement-plan.json", plan)
    _atomic_json(output / "refinement-manifest.json", refined_manifest)
    return plan


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--discovery", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    plan = run(args.manifest, args.discovery, args.output)
    print(json.dumps({
        "should_refine": plan["should_refine"],
        "training_basis_digest": plan["training_basis_digest"],
        "variant_counts": plan["variant_counts"],
        "live_trading_authority": plan["live_trading_authority"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
