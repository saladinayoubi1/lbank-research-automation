from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = Path("research/strategy_family_catalog.json")
SCHEMA = "nexus.strategy-discovery-controller.v1"

# Ordered, bounded research ladder already reviewed in this repository.  This
# controller inventories and routes the surface; it does not execute trades,
# qualify strategies, or widen authority.
SEARCH_STAGES: tuple[dict[str, str], ...] = (
    {
        "stage": "bybit_strategy_search_v2",
        "engine": "bybit_strategy_search_v2.py",
        "experiment": "experiments/bybit_strategy_search_v2.json",
        "workflow": ".github/workflows/bybit_strategy_search_v2.yml",
    },
    {
        "stage": "bybit_portfolio_search_v3",
        "engine": "bybit_portfolio_search_v3_scheduled.py",
        "experiment": "experiments/bybit_portfolio_search_v3.json",
        "workflow": ".github/workflows/bybit_portfolio_search_v3.yml",
    },
    {
        "stage": "bybit_long_short_search_v4",
        "engine": "bybit_long_short_search_v4.py",
        "experiment": "experiments/bybit_long_short_search_v4.json",
        "workflow": ".github/workflows/bybit_long_short_search_v4.yml",
    },
    {
        "stage": "bybit_consensus_search_v5",
        "engine": "bybit_consensus_search_v5.py",
        "experiment": "experiments/bybit_consensus_search_v5.json",
        "workflow": ".github/workflows/bybit_consensus_search_v5.yml",
    },
    {
        "stage": "bybit_regime_search_v6",
        "engine": "bybit_regime_search_v6.py",
        "experiment": "experiments/bybit_regime_search_v6.json",
        "workflow": ".github/workflows/bybit_regime_search_v6.yml",
    },
    {
        "stage": "bybit_neighborhood_validation_v7",
        "engine": "bybit_neighborhood_validation_v7.py",
        "experiment": "experiments/bybit_neighborhood_validation_v7.json",
        "workflow": ".github/workflows/bybit_neighborhood_validation_v7.yml",
    },
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _catalog_status(root: Path) -> tuple[dict[str, Any], list[str]]:
    path = root / CATALOG_PATH
    errors: list[str] = []
    if not path.is_file():
        return {
            "path": CATALOG_PATH.as_posix(),
            "status": "BLOCKED",
            "families": [],
        }, ["strategy_family_catalog_missing"]

    try:
        catalog = _load_json(path)
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "path": CATALOG_PATH.as_posix(),
            "status": "BLOCKED",
            "families": [],
        }, [f"strategy_family_catalog_invalid:{type(exc).__name__}"]

    if not isinstance(catalog, dict):
        errors.append("strategy_family_catalog_not_object")
        families_raw: list[Any] = []
    else:
        if catalog.get("schema") != "nexus.strategy-family-catalog.v1":
            errors.append("strategy_family_catalog_schema_mismatch")
        if catalog.get("status") != "research-only":
            errors.append("strategy_family_catalog_not_research_only")
        if catalog.get("paper_trading_only") is not True:
            errors.append("strategy_family_catalog_not_paper_only")
        families_value = catalog.get("families")
        families_raw = families_value if isinstance(families_value, list) else []
        if not families_raw:
            errors.append("strategy_family_catalog_has_no_families")

    families: list[str] = []
    for row in families_raw:
        if not isinstance(row, dict) or not isinstance(row.get("family"), str) or not row["family"]:
            errors.append("strategy_family_catalog_invalid_family")
            continue
        families.append(row["family"])
    if len(families) != len(set(families)):
        errors.append("strategy_family_catalog_duplicate_family")

    return {
        "path": CATALOG_PATH.as_posix(),
        "sha256": _sha256(path),
        "status": "READY" if not errors else "BLOCKED",
        "family_count": len(families),
        "families": sorted(families),
    }, errors


def _stage_status(root: Path, spec: dict[str, str]) -> tuple[dict[str, Any], list[str]]:
    missing = [key for key in ("engine", "experiment", "workflow") if not (root / spec[key]).is_file()]
    errors: list[str] = [f"{spec['stage']}:missing_{key}" for key in missing]
    experiment_id: str | None = None
    experiment_sha256: str | None = None
    workflow_dispatch = False

    experiment_path = root / spec["experiment"]
    if experiment_path.is_file():
        experiment_sha256 = _sha256(experiment_path)
        try:
            experiment = _load_json(experiment_path)
            if not isinstance(experiment, dict) or not isinstance(experiment.get("experiment_id"), str):
                errors.append(f"{spec['stage']}:invalid_experiment_contract")
            else:
                experiment_id = experiment["experiment_id"]
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{spec['stage']}:invalid_experiment_json:{type(exc).__name__}")

    workflow_path = root / spec["workflow"]
    if workflow_path.is_file():
        try:
            workflow_text = workflow_path.read_text(encoding="utf-8")
            workflow_dispatch = "workflow_dispatch:" in workflow_text
            if not workflow_dispatch:
                errors.append(f"{spec['stage']}:workflow_dispatch_missing")
        except OSError as exc:
            errors.append(f"{spec['stage']}:workflow_unreadable:{type(exc).__name__}")

    return {
        "stage": spec["stage"],
        "engine": spec["engine"],
        "experiment": spec["experiment"],
        "workflow": spec["workflow"],
        "experiment_id": experiment_id,
        "experiment_sha256": experiment_sha256,
        "dispatch_mode": "reviewed_workflow_dispatch" if workflow_dispatch else "unavailable",
        "status": "READY_FOR_RESEARCH_DISPATCH" if not errors else "BLOCKED",
        "missing": missing,
    }, errors


def build_status(root: Path = ROOT) -> dict[str, Any]:
    root = root.resolve()
    catalog, errors = _catalog_status(root)
    stages: list[dict[str, Any]] = []
    for spec in SEARCH_STAGES:
        stage, stage_errors = _stage_status(root, spec)
        stages.append(stage)
        errors.extend(stage_errors)

    ready = [row for row in stages if row["status"] == "READY_FOR_RESEARCH_DISPATCH"]
    blocked = [row for row in stages if row["status"] == "BLOCKED"]
    controller_verified = not errors

    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "mode": "research-backtest-paper-only",
        "paper_only": True,
        "live_trading_authority": False,
        "controller_verified": controller_verified,
        "catalog": catalog,
        "search_stages": stages,
        "summary": {
            "strategy_family_count": catalog.get("family_count", 0),
            "search_stage_count": len(stages),
            "ready_search_stage_count": len(ready),
            "blocked_search_stage_count": len(blocked),
        },
        "qualified_candidates": [],
        "qualification_claimed": False,
        "qualification_policy": (
            "Configuration, workflow availability, or controller readiness never qualifies a strategy. "
            "Qualification requires produced deterministic validation evidence under the existing research gates."
        ),
        "errors": sorted(set(errors)),
        "next_research_action": (
            ready[0]["stage"]
            if controller_verified and ready
            else "repair_discovery_surface_before_dispatch"
        ),
    }
    payload["status_sha256"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Inventory the bounded NEXUS strategy-discovery surface")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    payload = build_status(args.root)
    if args.output:
        _atomic_write(args.output, payload)
    print(json.dumps(payload, sort_keys=True))
    return 0 if payload["controller_verified"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
