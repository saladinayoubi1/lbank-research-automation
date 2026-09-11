"""Build one bounded next-generation Multi-Pair research manifest from training evidence only.

The planner is deliberately blind to locked/holdout metrics. It may use only the
selected configuration and training evidence produced by the base Discovery run.
Temporal robustness is used to allocate the bounded variant budget so unstable
training frontiers cannot crowd out stronger training-only evidence. Gates,
execution costs, the four-symbol surface, and Research/Paper-only authority remain
unchanged.
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

import nexus_multipair_strategy_discovery as discovery

SCHEMA = "nexus.multipair-training-refinement-plan.v1"
MAX_VARIANTS_PER_FAMILY = 12
CONTROL_VARIANTS_PER_UNTARGETED_FAMILY = 2


class MultiPairRefinementError(RuntimeError):
    pass


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise MultiPairRefinementError("refinement evidence is not canonical JSON") from exc


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
        raise MultiPairRefinementError(f"unsupported family: {family}")
    return _stable_unique(rows)


def _robust_neighborhood(family: str, config: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Widen only around a frontier that is stable across training-only windows."""
    rows = _neighborhood(family, config)
    if family == "momentum":
        lookback = int(config["lookback"])
        threshold = float(config["entry_threshold"])
        rows.extend([
            {"lookback": _scaled_int(lookback, 1.25, minimum=2), "entry_threshold": _round_float(max(0.0, threshold + 0.0015))},
            {"lookback": _scaled_int(lookback, 1.75, minimum=2), "entry_threshold": _round_float(max(0.0, threshold + 0.0035))},
            {"lookback": _scaled_int(lookback, 2.5, minimum=2), "entry_threshold": _round_float(max(0.0, threshold + 0.0060))},
            {"lookback": _scaled_int(lookback, 3.5, minimum=2), "entry_threshold": _round_float(max(0.0, threshold + 0.0085))},
            {"lookback": _scaled_int(lookback, 5.0, minimum=2), "entry_threshold": _round_float(max(0.0, threshold + 0.0125))},
            {"lookback": _scaled_int(lookback, 6.0, minimum=2), "entry_threshold": _round_float(max(0.0, threshold + 0.0150))},
        ])
    elif family == "trend_breakout":
        entry = int(config["entry_lookback"])
        exit_ = int(config["exit_lookback"])
        rows.extend([
            {"entry_lookback": _scaled_int(entry, 1.25, minimum=3), "exit_lookback": _scaled_int(exit_, 0.75, minimum=2)},
            {"entry_lookback": _scaled_int(entry, 1.75, minimum=3), "exit_lookback": max(2, exit_)},
            {"entry_lookback": _scaled_int(entry, 2.25, minimum=3), "exit_lookback": max(2, exit_)},
            {"entry_lookback": _scaled_int(entry, 3.5, minimum=3), "exit_lookback": _scaled_int(exit_, 1.5, minimum=2)},
            {"entry_lookback": _scaled_int(entry, 5.0, minimum=3), "exit_lookback": _scaled_int(exit_, 2.0, minimum=2)},
            {"entry_lookback": _scaled_int(entry, 6.0, minimum=3), "exit_lookback": _scaled_int(exit_, 2.5, minimum=2)},
        ])
        rows = [row for row in rows if row["exit_lookback"] < row["entry_lookback"]]
    elif family == "mean_reversion":
        lookback = int(config["lookback"])
        entry_z = float(config["entry_z"])
        exit_z = float(config["exit_z"])
        rows.extend([
            {"lookback": _scaled_int(lookback, 1.25, minimum=5), "entry_z": _round_float(entry_z - 0.25), "exit_z": _round_float(exit_z)},
            {"lookback": _scaled_int(lookback, 1.75, minimum=5), "entry_z": _round_float(entry_z - 0.25), "exit_z": _round_float(exit_z - 0.25)},
            {"lookback": _scaled_int(lookback, 2.5, minimum=5), "entry_z": _round_float(entry_z - 0.5), "exit_z": _round_float(exit_z - 0.25)},
            {"lookback": _scaled_int(lookback, 3.5, minimum=5), "entry_z": _round_float(entry_z - 0.75), "exit_z": _round_float(exit_z - 0.5)},
            {"lookback": _scaled_int(lookback, 5.0, minimum=5), "entry_z": _round_float(entry_z - 1.0), "exit_z": _round_float(exit_z - 0.5)},
            {"lookback": _scaled_int(lookback, 6.0, minimum=5), "entry_z": _round_float(entry_z - 1.25), "exit_z": _round_float(exit_z - 0.75)},
        ])
        rows = [row for row in rows if float(row["entry_z"]) < float(row["exit_z"])]
    else:
        raise MultiPairRefinementError(f"unsupported family: {family}")
    return _stable_unique(rows)


def _training_checks(summary: Mapping[str, Any], training_gate: Mapping[str, Any]) -> dict[str, bool]:
    return discovery.legacy._gate(summary, training_gate)  # noqa: SLF001 - same research gate contract


def _is_training_frontier(
    summary: Mapping[str, Any], checks: Mapping[str, bool], training_gate: Mapping[str, Any]
) -> bool:
    failed = sorted(key for key, passed in checks.items() if not passed)
    if not failed:
        return True
    if failed != ["drawdown"]:
        return False
    maximum = float(training_gate["maximum_drawdown"])
    drawdown = float(summary["worst_drawdown"])
    return math.isfinite(drawdown) and drawdown <= maximum * 1.5


def _robustness_rank(row: Mapping[str, Any]) -> tuple[Any, ...]:
    robustness = row.get("training_robustness")
    summary = row["training_summary"]
    if not isinstance(robustness, Mapping):
        return (0, 0, float("-inf"), float("-inf"), float("-inf"), float(summary["score"]))
    return (
        int(robustness.get("all_windows_pass_training_gate") is True),
        int(robustness.get("minimum_passed_gate_count", 0)),
        float(robustness.get("minimum_score", float("-inf"))),
        float(robustness.get("minimum_positive_ratio", float("-inf"))),
        float(robustness.get("minimum_median_return", float("-inf"))),
        float(summary["score"]),
    )


def _expansion_targets(targeted: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Allocate each family budget to its strongest temporal training frontier."""
    selected: list[dict[str, Any]] = []
    for family in discovery.FAMILIES:
        family_rows = [dict(row) for row in targeted if row["family"] == family]
        if not family_rows:
            continue
        robust_rows = [
            row
            for row in family_rows
            if isinstance(row.get("training_robustness"), Mapping)
            and row["training_robustness"].get("all_windows_pass_training_gate") is True
        ]
        pool = robust_rows or family_rows
        selected.append(max(pool, key=_robustness_rank))
    return selected


def build_refinement(
    manifest: Mapping[str, Any], discovery_result: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    verification = discovery.verify_discovery(discovery_result)
    if verification["decision"] != "pass":
        raise MultiPairRefinementError("base discovery verification failed")
    proposal_count = int(discovery_result.get("research_proposal_count", -1))
    if proposal_count < 0:
        raise MultiPairRefinementError("base discovery proposal count is invalid")
    if discovery_result.get("symbols") != list(discovery.SYMBOLS):
        raise MultiPairRefinementError("discovery symbol surface mismatch")
    if discovery_result.get("timeframes") != list(discovery.TIMEFRAME_NAMES):
        raise MultiPairRefinementError("discovery timeframe surface mismatch")
    if discovery_result.get("families") != list(discovery.FAMILIES):
        raise MultiPairRefinementError("discovery family surface mismatch")

    training_gate = manifest["gates"]["training"]
    targeted: list[dict[str, Any]] = []

    # Deliberately never read locked_profiles. Only training-side evidence can
    # influence the next bounded grid; locked holdout remains one-way validation.
    for cell in discovery_result["cells"] if proposal_count == 0 else []:
        timeframe = str(cell["timeframe"])
        family = str(cell["family"])
        selected_config = dict(cell["selected_config"])
        training_summary = dict(cell["training_summary"])
        training_robustness = cell.get("training_robustness")
        if training_robustness is not None and not isinstance(training_robustness, Mapping):
            raise MultiPairRefinementError("training robustness evidence is invalid")
        checks = _training_checks(training_summary, training_gate)
        failed = sorted(key for key, passed in checks.items() if not passed)
        if not _is_training_frontier(training_summary, checks, training_gate):
            continue
        basis_core = {
            "timeframe": timeframe,
            "family": family,
            "selected_config": selected_config,
            "training_summary": training_summary,
            "training_gate_checks": checks,
            "failed_training_gates": failed,
        }
        if training_robustness is not None:
            basis_core["training_robustness"] = copy.deepcopy(dict(training_robustness))
        targeted.append({**basis_core, "basis_digest": _digest(basis_core)})

    expansion_targets = _expansion_targets(targeted)
    variants_by_family: dict[str, list[dict[str, Any]]] = {
        family: [] for family in discovery.FAMILIES
    }
    for row in expansion_targets:
        family = str(row["family"])
        robustness = row.get("training_robustness")
        robust = (
            isinstance(robustness, Mapping)
            and robustness.get("all_windows_pass_training_gate") is True
        )
        generator = _robust_neighborhood if robust else _neighborhood
        variants_by_family[family].extend(generator(family, row["selected_config"]))

    final_variants: dict[str, list[dict[str, Any]]] = {}
    expansion_families = {row["family"] for row in expansion_targets}
    for family in discovery.FAMILIES:
        generated = _stable_unique(variants_by_family[family])
        base_rows = [dict(row) for row in manifest["variants"][family]]
        if family in expansion_families:
            controls = _stable_unique(
                [
                    dict(row["selected_config"])
                    for row in expansion_targets
                    if row["family"] == family
                ]
            )
            rows = _stable_unique(controls + generated)
        else:
            rows = base_rows[:CONTROL_VARIANTS_PER_UNTARGETED_FAMILY]
        rows = rows[:MAX_VARIANTS_PER_FAMILY]
        if len(rows) < 2:
            rows = _stable_unique(rows + base_rows)[:2]
        final_variants[family] = rows

    targeted_sorted = sorted(targeted, key=lambda row: (row["timeframe"], row["family"]))
    expansion_sorted = sorted(
        expansion_targets, key=lambda row: (row["timeframe"], row["family"])
    )
    training_basis_core = {
        "base_experiment_id": manifest["experiment_id"],
        "dataset_snapshot_sha256": discovery_result["dataset_snapshot_sha256"],
        "training_gate": copy.deepcopy(training_gate),
        "training_frontier_cells": targeted_sorted,
        "targeted_cells": expansion_sorted,
        "temporal_robustness_used_for_budgeting": True,
        "variants": final_variants,
    }
    training_basis_digest = _digest(training_basis_core)
    should_refine = bool(expansion_targets)

    refined_manifest = copy.deepcopy(dict(manifest))
    refined_manifest["experiment_id"] = (
        f"{manifest['experiment_id']}-training-refinement-{training_basis_digest[:12]}"
    )
    refined_manifest["variants"] = final_variants
    if refined_manifest["gates"] != manifest["gates"]:
        raise MultiPairRefinementError("refinement changed research gates")
    if refined_manifest["execution"] != manifest["execution"]:
        raise MultiPairRefinementError("refinement changed execution costs")
    if refined_manifest["authority"] != manifest["authority"]:
        raise MultiPairRefinementError("refinement changed authority")
    if any(len(rows) > MAX_VARIANTS_PER_FAMILY for rows in final_variants.values()):
        raise MultiPairRefinementError("refinement exceeded bounded family grid")

    plan_core = {
        "schema_version": SCHEMA,
        "source_discovery_sha": discovery_result["source_sha"],
        "source_discovery_digest": discovery_result["discovery_digest"],
        "base_research_proposal_count": proposal_count,
        "dataset_snapshot_sha256": discovery_result["dataset_snapshot_sha256"],
        "training_basis_digest": training_basis_digest,
        "selection_basis": "training_only",
        "locked_holdout_used_for_refinement": False,
        "temporal_robustness_used_for_budgeting": True,
        "should_refine": should_refine,
        "training_frontier_cells": targeted_sorted,
        "targeted_cells": expansion_sorted,
        "variant_counts": {family: len(final_variants[family]) for family in discovery.FAMILIES},
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
    manifest_path: str | Path, discovery_path: str | Path, output_root: str | Path
) -> dict[str, Any]:
    manifest = discovery.load_manifest(manifest_path)
    try:
        base = json.loads(Path(discovery_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MultiPairRefinementError("base discovery result is unavailable") from exc
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
