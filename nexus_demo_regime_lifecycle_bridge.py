"""Run the existing regime-selected Paper lifecycle on verified Bybit archive replay.

This adapter does not implement another execution or Risk engine.  It binds the
already-reviewed regime-selected rebalance and fresh-Risk increase bridges to the
same immutable Bybit Spot archive fetcher that produced the verified Demo regime
snapshot.  The binding is process-local, scoped, restored on every exit path, and
remains Paper-only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

import nexus_regime_selected_exposure_increase as increase_module
import nexus_regime_selected_position_rebalance as rebalance_module
from nexus_demo_archive_replay import ARCHIVE_SHA256, build_archive_dataset_fetcher
from nexus_demo_regime_cycle import verify_cycle_snapshot
from nexus_demo_strategy_matrix import load_manifest
from nexus_regime_selected_exposure_increase import (
    run_regime_selected_exposure_increase,
    verify_regime_selected_exposure_increase,
)
from nexus_regime_selected_position_rebalance import (
    run_regime_selected_rebalance,
    verify_regime_selected_rebalance,
)


SCHEMA = "nexus.demo-regime-lifecycle-bridge.v1"
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class DemoRegimeLifecycleBridgeError(RuntimeError):
    pass


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise DemoRegimeLifecycleBridgeError("lifecycle evidence is not canonical JSON") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


@contextmanager
def bind_verified_archive_research(
    fetcher: Callable[..., Mapping[str, Any]],
) -> Iterator[None]:
    """Scope the existing lifecycle research calls to one verified archive fetcher.

    Both lifecycle modules normally resolve the public REST fetcher from their own
    module globals.  Demo replay must use the exact archive source that produced the
    regime context, otherwise their dataset-binding checks correctly fail.  This
    adapter changes only those two dependency references for the lifetime of this
    one-shot process and restores them unconditionally.
    """
    if not callable(fetcher):
        raise DemoRegimeLifecycleBridgeError("archive research fetcher must be callable")
    prior_rebalance = rebalance_module.fetch_bind_bybit_dataset
    prior_increase = increase_module.fetch_bind_bybit_dataset
    try:
        rebalance_module.fetch_bind_bybit_dataset = fetcher
        increase_module.fetch_bind_bybit_dataset = fetcher
        yield
    finally:
        rebalance_module.fetch_bind_bybit_dataset = prior_rebalance
        increase_module.fetch_bind_bybit_dataset = prior_increase


def run_demo_regime_lifecycle(
    *,
    manifest: Mapping[str, Any],
    state_root: str | Path,
    source_sha: str,
    regime_snapshot: Mapping[str, Any],
    archive_root: str | Path,
    archive_sha256: str,
) -> dict[str, Any]:
    source_sha = str(source_sha).strip().lower()
    archive_sha256 = str(archive_sha256).strip().lower()
    if not _SHA_RE.fullmatch(source_sha):
        raise DemoRegimeLifecycleBridgeError("source_sha must be an exact Git SHA")
    if archive_sha256 != ARCHIVE_SHA256:
        raise DemoRegimeLifecycleBridgeError("only the approved immutable Bybit archive is eligible")
    if verify_cycle_snapshot(regime_snapshot).get("decision") != "pass":
        raise DemoRegimeLifecycleBridgeError("Demo regime snapshot failed independent verification")
    if (
        regime_snapshot.get("source_sha") != source_sha
        or regime_snapshot.get("archive_sha256") != archive_sha256
        or regime_snapshot.get("paper_only") is not True
        or regime_snapshot.get("live_trading_authority") is not False
        or regime_snapshot.get("private_credentials_used") is not False
        or regime_snapshot.get("automatic_strategy_promotion") is not False
        or regime_snapshot.get("deterministic_risk_final_authority") is not True
    ):
        raise DemoRegimeLifecycleBridgeError("Demo regime source/authority binding failed")

    fetcher = build_archive_dataset_fetcher(
        archive_root,
        archive_sha256=archive_sha256,
    )
    with bind_verified_archive_research(fetcher):
        rebalance = run_regime_selected_rebalance(
            manifest=manifest,
            state_root=state_root,
            source_sha=source_sha,
            regime_snapshot=regime_snapshot,
        )
        if verify_regime_selected_rebalance(rebalance).get("decision") != "pass":
            raise DemoRegimeLifecycleBridgeError("risk-reducing rebalance failed verification")
        increase = run_regime_selected_exposure_increase(
            manifest=manifest,
            state_root=state_root,
            source_sha=source_sha,
            regime_snapshot=regime_snapshot,
            rebalance_snapshot=rebalance,
        )
        if verify_regime_selected_exposure_increase(increase).get("decision") != "pass":
            raise DemoRegimeLifecycleBridgeError("fresh-Risk exposure increase failed verification")

    if (
        rebalance.get("risk_reducing_rebalance_operational") is not True
        or rebalance.get("exposure_increased") is not False
        or increase.get("exposure_increase_operational") is not True
        or increase.get("fresh_deterministic_risk_required") is not True
        or increase.get("unauthorized_exposure_increase") is not False
    ):
        raise DemoRegimeLifecycleBridgeError("regime lifecycle did not preserve deterministic authority")

    core = {
        "schema_version": SCHEMA,
        "source_sha": source_sha,
        "archive_sha256": archive_sha256,
        "regime_cycle_digest": regime_snapshot["cycle_digest"],
        "rebalance_digest": rebalance["rebalance_digest"],
        "increase_digest": increase["increase_digest"],
        "risk_reducing_rebalance_operational": True,
        "exposure_increase_operational": True,
        "regime_selected_rebalance_operational": True,
        "fresh_deterministic_risk_required": True,
        "paper_only": True,
        "live_trading_authority": False,
        "private_credentials_used": False,
        "automatic_strategy_promotion": False,
        "deterministic_risk_final_authority": True,
        "parallel_execution_engine_created": False,
    }
    result = {**core, "lifecycle_digest": _digest(core)}
    if verify_demo_regime_lifecycle(result).get("decision") != "pass":
        raise DemoRegimeLifecycleBridgeError("Demo lifecycle snapshot failed verification")
    output = Path(state_root).resolve() / "demo" / "regime-lifecycle-bridge.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def verify_demo_regime_lifecycle(value: Mapping[str, Any]) -> dict[str, Any]:
    checks = {
        "schema": False,
        "digest": False,
        "authority": False,
        "operational": False,
        "bindings": False,
    }
    try:
        core = dict(value)
        claimed = core.pop("lifecycle_digest", None)
        checks["schema"] = core.get("schema_version") == SCHEMA
        checks["digest"] = isinstance(claimed, str) and claimed == _digest(core)
        checks["authority"] = bool(
            core.get("paper_only") is True
            and core.get("live_trading_authority") is False
            and core.get("private_credentials_used") is False
            and core.get("automatic_strategy_promotion") is False
            and core.get("deterministic_risk_final_authority") is True
            and core.get("parallel_execution_engine_created") is False
        )
        checks["operational"] = bool(
            core.get("risk_reducing_rebalance_operational") is True
            and core.get("exposure_increase_operational") is True
            and core.get("regime_selected_rebalance_operational") is True
            and core.get("fresh_deterministic_risk_required") is True
        )
        checks["bindings"] = bool(
            core.get("archive_sha256") == ARCHIVE_SHA256
            and isinstance(core.get("source_sha"), str)
            and _SHA_RE.fullmatch(core["source_sha"])
            and all(
                isinstance(core.get(name), str) and re.fullmatch(r"[0-9a-f]{64}", core[name])
                for name in ("regime_cycle_digest", "rebalance_digest", "increase_digest")
            )
        )
    except (KeyError, TypeError, ValueError):
        pass
    return {"decision": "pass" if all(checks.values()) else "reject", "checks": checks}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--replay-archive-root", type=Path, required=True)
    parser.add_argument("--archive-sha256", required=True)
    args = parser.parse_args()
    regime_path = args.state_root / "demo" / "regime-cycle.json"
    try:
        regime = json.loads(regime_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DemoRegimeLifecycleBridgeError("verified Demo regime snapshot is unavailable") from exc
    result = run_demo_regime_lifecycle(
        manifest=load_manifest(args.manifest),
        state_root=args.state_root,
        source_sha=args.source_sha,
        regime_snapshot=regime,
        archive_root=args.replay_archive_root,
        archive_sha256=args.archive_sha256,
    )
    print(json.dumps({
        "decision": verify_demo_regime_lifecycle(result)["decision"],
        "rebalance_operational": result["risk_reducing_rebalance_operational"],
        "increase_operational": result["exposure_increase_operational"],
        "lifecycle_digest": result["lifecycle_digest"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
