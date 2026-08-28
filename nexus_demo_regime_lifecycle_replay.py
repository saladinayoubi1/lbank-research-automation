"""Replay the verified regime lifecycle on the immutable official Bybit archive.

This controller is intentionally separate from the prospective public-data Paper loop.
It lets CI exercise the same regime-selected rebalance and fresh Deterministic-Risk
exposure-increase bridges while Issue #1041 blocks live-forward public Bybit access
from GitHub-hosted runners.  The only data source is the already-approved immutable
Bybit Spot archive; no exchange substitution, proxy, credentials, Live/L4 authority,
or automatic strategy promotion is introduced.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

from nexus_demo_archive_replay import ARCHIVE_SHA256, build_archive_dataset_fetcher
from nexus_demo_regime_cycle import verify_cycle_snapshot
from nexus_demo_strategy_matrix import load_manifest
import nexus_regime_selected_exposure_increase as increase_mod
import nexus_regime_selected_position_rebalance as rebalance_mod


SCHEMA = "nexus.demo-regime-lifecycle-replay.v1"
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_MAX_JSON_BYTES = 20_000_000


class DemoRegimeLifecycleReplayError(RuntimeError):
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
        raise DemoRegimeLifecycleReplayError("lifecycle replay evidence is not canonical JSON") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    target = Path(path)
    if target.is_symlink() or not target.is_file() or target.stat().st_size > _MAX_JSON_BYTES:
        raise DemoRegimeLifecycleReplayError(f"required evidence is unavailable or unsafe: {target.name}")
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DemoRegimeLifecycleReplayError(f"required evidence is unreadable: {target.name}") from exc
    if not isinstance(value, dict):
        raise DemoRegimeLifecycleReplayError("required evidence is not an object")
    return value


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + f".{os.getpid()}.tmp")
    payload = json.dumps(
        dict(value), indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False
    ) + "\n"
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise DemoRegimeLifecycleReplayError("lifecycle replay persistence failed") from exc


@contextmanager
def _archive_fetch_scope(fetcher: Callable[..., Mapping[str, Any]]) -> Iterator[None]:
    """Bind both lifecycle bridges to one immutable archive fetcher for this process."""
    previous_rebalance = rebalance_mod.fetch_bind_bybit_dataset
    previous_increase = increase_mod.fetch_bind_bybit_dataset
    rebalance_mod.fetch_bind_bybit_dataset = fetcher
    increase_mod.fetch_bind_bybit_dataset = fetcher
    try:
        yield
    finally:
        rebalance_mod.fetch_bind_bybit_dataset = previous_rebalance
        increase_mod.fetch_bind_bybit_dataset = previous_increase


def run_demo_regime_lifecycle_replay(
    *,
    manifest: Mapping[str, Any],
    state_root: str | Path,
    source_sha: str,
    replay_archive_root: str | Path,
    archive_sha256: str,
    dataset_fetcher: Callable[..., Mapping[str, Any]] | None = None,
    regime_snapshot: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    source_sha = str(source_sha).strip().lower()
    archive_sha256 = str(archive_sha256).strip().lower()
    if not _SHA_RE.fullmatch(source_sha):
        raise DemoRegimeLifecycleReplayError("source_sha must be an exact Git SHA")
    if archive_sha256 != ARCHIVE_SHA256:
        raise DemoRegimeLifecycleReplayError("only the approved immutable Bybit archive is eligible")

    root = Path(state_root).resolve()
    regime = (
        dict(regime_snapshot)
        if regime_snapshot is not None
        else _read_json(root / "demo" / "regime-cycle.json")
    )
    if (
        verify_cycle_snapshot(regime).get("decision") != "pass"
        or regime.get("source_sha") != source_sha
        or regime.get("archive_sha256") != ARCHIVE_SHA256
        or regime.get("paper_only") is not True
        or regime.get("live_trading_authority") is not False
        or regime.get("private_credentials_used") is not False
        or regime.get("automatic_strategy_promotion") is not False
        or regime.get("deterministic_risk_final_authority") is not True
    ):
        raise DemoRegimeLifecycleReplayError("regime snapshot is not exact-source immutable-archive evidence")

    fetcher = dataset_fetcher or build_archive_dataset_fetcher(
        replay_archive_root, archive_sha256=archive_sha256
    )
    with _archive_fetch_scope(fetcher):
        rebalance = rebalance_mod.run_regime_selected_rebalance(
            manifest=manifest,
            state_root=root,
            source_sha=source_sha,
            regime_snapshot=regime,
        )
        if rebalance_mod.verify_regime_selected_rebalance(rebalance).get("decision") != "pass":
            raise DemoRegimeLifecycleReplayError("archive-backed rebalance failed independent verification")
        increase = increase_mod.run_regime_selected_exposure_increase(
            manifest=manifest,
            state_root=root,
            source_sha=source_sha,
            regime_snapshot=regime,
            rebalance_snapshot=rebalance,
        )
        if increase_mod.verify_regime_selected_exposure_increase(increase).get("decision") != "pass":
            raise DemoRegimeLifecycleReplayError("archive-backed exposure increase failed verification")

    core = {
        "schema_version": SCHEMA,
        "source_sha": source_sha,
        "archive_sha256": archive_sha256,
        "regime_cycle_digest": regime["cycle_digest"],
        "rebalance_digest": rebalance["rebalance_digest"],
        "increase_digest": increase["increase_digest"],
        "risk_reducing_rebalance_operational": rebalance.get("risk_reducing_rebalance_operational") is True,
        "exposure_increase_operational": increase.get("exposure_increase_operational") is True,
        "fresh_deterministic_risk_required": increase.get("fresh_deterministic_risk_required") is True,
        "unauthorized_exposure_increase": increase.get("unauthorized_exposure_increase") is True,
        "paper_only": True,
        "live_trading_authority": False,
        "private_credentials_used": False,
        "automatic_strategy_promotion": False,
        "deterministic_risk_final_authority": True,
    }
    result = {**core, "replay_digest": _digest(core)}
    if verify_demo_regime_lifecycle_replay(result).get("decision") != "pass":
        raise DemoRegimeLifecycleReplayError("lifecycle replay snapshot failed independent verification")
    _atomic_json(root / "demo" / "regime-lifecycle-replay.json", result)
    return result


def verify_demo_regime_lifecycle_replay(value: Mapping[str, Any]) -> dict[str, Any]:
    checks = {
        "schema": False,
        "digest": False,
        "shape": False,
        "authority": False,
        "lifecycle": False,
    }
    try:
        core = dict(value)
        claimed = core.pop("replay_digest", None)
        checks["schema"] = core.get("schema_version") == SCHEMA
        checks["digest"] = isinstance(claimed, str) and claimed == _digest(core)
        checks["shape"] = bool(
            core.get("archive_sha256") == ARCHIVE_SHA256
            and _SHA_RE.fullmatch(str(core.get("source_sha", "")))
            and all(
                isinstance(core.get(field), str) and re.fullmatch(r"[0-9a-f]{64}", core[field])
                for field in ("regime_cycle_digest", "rebalance_digest", "increase_digest")
            )
        )
        checks["authority"] = bool(
            core.get("paper_only") is True
            and core.get("live_trading_authority") is False
            and core.get("private_credentials_used") is False
            and core.get("automatic_strategy_promotion") is False
            and core.get("deterministic_risk_final_authority") is True
            and core.get("unauthorized_exposure_increase") is False
        )
        checks["lifecycle"] = bool(
            core.get("risk_reducing_rebalance_operational") is True
            and core.get("exposure_increase_operational") is True
            and core.get("fresh_deterministic_risk_required") is True
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
    result = run_demo_regime_lifecycle_replay(
        manifest=load_manifest(args.manifest),
        state_root=args.state_root,
        source_sha=args.source_sha,
        replay_archive_root=args.replay_archive_root,
        archive_sha256=args.archive_sha256,
    )
    verification = verify_demo_regime_lifecycle_replay(result)
    print(json.dumps({
        "decision": verification["decision"],
        "risk_reducing_rebalance_operational": result["risk_reducing_rebalance_operational"],
        "exposure_increase_operational": result["exposure_increase_operational"],
        "replay_digest": result["replay_digest"],
    }, sort_keys=True))
    return 0 if verification["decision"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
