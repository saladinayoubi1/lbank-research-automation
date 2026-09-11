from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import re
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

import bybit_prospective_paper_forward_v1 as forward
from bybit_derivatives_core_v1 import Client
from bybit_derivatives_validation_v1 import frozen_weights

SCHEMA = "nexus.paper-runtime-attestation.v1"
ATTESTATION_FILE = "runtime_attestation.json"
_LOCK_RE = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s]+)$")


class PaperRuntimeAttestationError(RuntimeError):
    pass


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PaperRuntimeAttestationError("runtime attestation is not canonical JSON") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    target = path.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + f".{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(dict(value), indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, target)


def _engine_sha() -> str:
    return forward._file_sha(Path(forward.__file__).resolve())  # noqa: SLF001 - exact producer binding


def load_locked_runtime(lock_path: Path, *, verify_installed: bool) -> dict[str, Any]:
    text = lock_path.read_text(encoding="utf-8")
    pins: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _LOCK_RE.fullmatch(line)
        if not match:
            raise PaperRuntimeAttestationError(f"runtime lock is not exact: {line}")
        name, version = match.groups()
        key = re.sub(r"[-_.]+", "-", name).lower()
        if key in pins:
            raise PaperRuntimeAttestationError(f"duplicate runtime lock entry: {name}")
        pins[key] = version
    if not pins:
        raise PaperRuntimeAttestationError("runtime lock is empty")

    installed: dict[str, str] = {}
    if verify_installed:
        for name, expected in sorted(pins.items()):
            try:
                actual = importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError as exc:
                raise PaperRuntimeAttestationError(f"locked runtime package is missing: {name}") from exc
            if actual != expected:
                raise PaperRuntimeAttestationError(
                    f"locked runtime package drifted: {name} expected={expected} actual={actual}"
                )
            installed[name] = actual
    else:
        installed = dict(sorted(pins.items()))

    return {
        "requirements_lock_sha256": forward._file_sha(lock_path.resolve()),  # noqa: SLF001
        "python_version": ".".join(str(x) for x in sys.version_info[:3]),
        "locked_versions": dict(sorted(pins.items())),
        "installed_versions": installed,
    }


def _assert_zero_execution_legacy(state: Mapping[str, Any], config: Mapping[str, Any]) -> None:
    if any(
        event.get("target_weights") != [0.0, 0.0] or event.get("target_changed") is not False
        for event in state["events"]
    ):
        raise PaperRuntimeAttestationError(
            "legacy runtime drift cannot be requalified after non-zero or changed targets"
        )
    for name, row in state["profiles"].items():
        initial = float(config["execution_profiles"][name]["initial_cash"])
        if (
            float(row["wallet"]) != initial
            or float(row["equity"]) != initial
            or int(row["fill_count"]) != 0
            or int(row["orders"]) != 0
            or int(row["execution_hits"]) != 0
            or int(row["margin_rejections"]) != 0
            or int(row["liquidations"]) != 0
            or float(row["fees"]) != 0.0
            or float(row["funding_cashflow"]) != 0.0
            or row["target_weights"] != [0.0, 0.0]
            or any(float(position["quantity"]) != 0.0 for position in row["positions"])
        ):
            raise PaperRuntimeAttestationError(
                "legacy runtime drift cannot be requalified after execution exposure"
            )


def replay_target_sequence(
    config: Mapping[str, Any],
    frozen: Mapping[str, Any],
    state: Mapping[str, Any],
    *,
    client: Client | None = None,
) -> list[dict[str, Any]]:
    if not state["events"]:
        return []
    start = forward._utc(config["start_not_before_utc"])  # noqa: SLF001
    last_execution = forward._utc(state["last_execution_utc"])  # noqa: SLF001
    warmup_start = start - pd.Timedelta(days=int(config["warmup_days"]))
    end_ms = int(last_execution.timestamp() * 1000)
    api = client or Client(
        list(config["api_base_urls"]),
        float(config["timeout_seconds"]),
        int(config["maximum_attempts"]),
        float(config["request_pause_seconds"]),
    )
    frames = {
        symbol: forward._fetch_klines(  # noqa: SLF001 - exact producer market reader
            api,
            category="spot",
            endpoint="/v5/market/kline",
            symbol=symbol,
            start_ms=int(warmup_start.timestamp() * 1000),
            end_ms=end_ms,
            include_volume=True,
        )
        for symbol in forward.SYMBOLS
    }
    for symbol, frame in frames.items():
        forward._require_complete_grid(  # noqa: SLF001
            frame,
            start_ms=int(warmup_start.timestamp() * 1000),
            end_ms=end_ms,
            label=f"runtime requalification Spot {symbol}",
        )
    timestamps = frames[forward.SYMBOLS[0]]["timestamp"]
    if not timestamps.equals(frames[forward.SYMBOLS[1]]["timestamp"]):
        raise PaperRuntimeAttestationError("runtime requalification Spot history is not aligned")
    spot = {
        "timestamps": timestamps,
        "close": np.column_stack(
            [frames[symbol]["close"].to_numpy(float) for symbol in forward.SYMBOLS]
        ),
    }
    weights = frozen_weights(spot, dict(frozen))
    index = {int(stamp.timestamp() * 1000): offset for offset, stamp in enumerate(timestamps)}
    replayed: list[dict[str, Any]] = []
    for event in state["events"]:
        execution = forward._utc(event["execution_utc"])  # noqa: SLF001
        signal_open_ms = int(execution.timestamp() * 1000) - forward.BAR_MS
        offset = index.get(signal_open_ms)
        if offset is None:
            raise PaperRuntimeAttestationError("recorded event has no replayable Spot predecessor")
        target = [float(x) for x in weights[offset].tolist()]
        recorded = [float(x) for x in event["target_weights"]]
        if not np.allclose(target, recorded, atol=1e-12, rtol=0.0):
            raise PaperRuntimeAttestationError(
                f"locked runtime changes recorded target sequence at event {event['sequence']}"
            )
        replayed.append(
            {
                "sequence": int(event["sequence"]),
                "execution_utc": event["execution_utc"],
                "target_weights": target,
            }
        )
    return replayed


def _attestation_core(
    *,
    state: Mapping[str, Any],
    runtime: Mapping[str, Any],
    legacy_completed_bar_count: int,
    legacy_state_digest: str,
    replay_digest: str,
) -> dict[str, Any]:
    lock_start = legacy_completed_bar_count + 1
    return {
        "schema_version": SCHEMA,
        "requirements_lock_sha256": runtime["requirements_lock_sha256"],
        "python_version": runtime["python_version"],
        "locked_versions": deepcopy(runtime["locked_versions"]),
        "engine_sha256": state["engine_sha256"],
        "strategy_manifest_sha256": state["strategy_manifest_sha256"],
        "legacy_runtime_environment_bound": False,
        "legacy_completed_bar_count": int(legacy_completed_bar_count),
        "legacy_state_digest_at_requalification": legacy_state_digest,
        "historical_target_replay_verified": True,
        "historical_zero_execution_exposure_verified": True,
        "historical_replay_target_digest": replay_digest,
        "lock_enforced_from_sequence": lock_start,
        "lock_enforced_event_count": max(0, int(state["completed_bar_count"]) - legacy_completed_bar_count),
        "bound_state_digest": state["state_digest"],
        "bound_completed_bar_count": int(state["completed_bar_count"]),
        "bound_last_run_id": int(state["last_run_id"]),
        "bound_source_sha": state["latest_source_sha"],
        "paper_only": True,
        "live_trading_enabled": False,
        "private_credentials_used": False,
        "automatic_live_promotion": False,
    }


def verify_attestation(
    attestation: Mapping[str, Any],
    state: Mapping[str, Any],
    config: Mapping[str, Any],
    runtime: Mapping[str, Any],
) -> None:
    if attestation.get("schema_version") != SCHEMA:
        raise PaperRuntimeAttestationError("runtime attestation schema mismatch")
    stored = attestation.get("attestation_digest")
    if not isinstance(stored, str) or not re.fullmatch(r"[0-9a-f]{64}", stored):
        raise PaperRuntimeAttestationError("runtime attestation digest is invalid")
    core = dict(attestation)
    core.pop("attestation_digest", None)
    if _digest(core) != stored:
        raise PaperRuntimeAttestationError("runtime attestation digest mismatch")
    if attestation.get("requirements_lock_sha256") != runtime["requirements_lock_sha256"]:
        raise PaperRuntimeAttestationError("runtime lock digest changed")
    if attestation.get("python_version") != runtime["python_version"]:
        raise PaperRuntimeAttestationError("Paper Python runtime changed")
    if attestation.get("locked_versions") != runtime["locked_versions"]:
        raise PaperRuntimeAttestationError("Paper locked package set changed")
    if attestation.get("engine_sha256") != state.get("engine_sha256"):
        raise PaperRuntimeAttestationError("runtime attestation engine binding mismatch")
    if attestation.get("strategy_manifest_sha256") != state.get("strategy_manifest_sha256"):
        raise PaperRuntimeAttestationError("runtime attestation strategy binding mismatch")
    if attestation.get("bound_state_digest") != state.get("state_digest"):
        raise PaperRuntimeAttestationError("runtime attestation state digest binding mismatch")
    if attestation.get("bound_completed_bar_count") != state.get("completed_bar_count"):
        raise PaperRuntimeAttestationError("runtime attestation bar count binding mismatch")
    if attestation.get("bound_last_run_id") != state.get("last_run_id"):
        raise PaperRuntimeAttestationError("runtime attestation run binding mismatch")
    if attestation.get("bound_source_sha") != state.get("latest_source_sha"):
        raise PaperRuntimeAttestationError("runtime attestation source binding mismatch")
    legacy_count = attestation.get("legacy_completed_bar_count")
    if isinstance(legacy_count, bool) or not isinstance(legacy_count, int) or legacy_count < 0:
        raise PaperRuntimeAttestationError("runtime attestation legacy count is invalid")
    if attestation.get("lock_enforced_from_sequence") != legacy_count + 1:
        raise PaperRuntimeAttestationError("runtime attestation lock boundary is invalid")
    if attestation.get("lock_enforced_event_count") != int(state["completed_bar_count"]) - legacy_count:
        raise PaperRuntimeAttestationError("runtime attestation locked event count mismatch")
    if (
        attestation.get("historical_target_replay_verified") is not True
        or attestation.get("historical_zero_execution_exposure_verified") is not True
        or attestation.get("legacy_runtime_environment_bound") is not False
        or attestation.get("paper_only") is not True
        or attestation.get("live_trading_enabled") is not False
        or attestation.get("private_credentials_used") is not False
        or attestation.get("automatic_live_promotion") is not False
    ):
        raise PaperRuntimeAttestationError("runtime attestation safety boundary mismatch")
    forward.verify_state(state, config, _engine_sha())


def requalify(
    *,
    manifest_path: Path,
    state_path: Path,
    lock_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    config, frozen = forward.load_contract(manifest_path.resolve())
    state = json.loads(state_path.read_text(encoding="utf-8"))
    forward.verify_state(state, config, _engine_sha())
    runtime = load_locked_runtime(lock_path.resolve(), verify_installed=True)
    _assert_zero_execution_legacy(state, config)
    replayed = replay_target_sequence(config, frozen, state)
    if len(replayed) != int(state["completed_bar_count"]):
        raise PaperRuntimeAttestationError("historical target replay count mismatch")
    replay_digest = _digest(replayed)
    core = _attestation_core(
        state=state,
        runtime=runtime,
        legacy_completed_bar_count=int(state["completed_bar_count"]),
        legacy_state_digest=state["state_digest"],
        replay_digest=replay_digest,
    )
    attestation = {**core, "attestation_digest": _digest(core)}
    verify_attestation(attestation, state, config, runtime)
    _atomic_json(output_path, attestation)
    return attestation


def rebind(
    *,
    manifest_path: Path,
    previous_state_path: Path,
    state_path: Path,
    attestation_path: Path,
    lock_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    config, _ = forward.load_contract(manifest_path.resolve())
    previous = json.loads(previous_state_path.read_text(encoding="utf-8"))
    state = json.loads(state_path.read_text(encoding="utf-8"))
    prior_attestation = json.loads(attestation_path.read_text(encoding="utf-8"))
    runtime = load_locked_runtime(lock_path.resolve(), verify_installed=True)
    verify_attestation(prior_attestation, previous, config, runtime)
    forward.verify_state(state, config, _engine_sha())
    previous_count = int(previous["completed_bar_count"])
    if int(state["completed_bar_count"]) < previous_count:
        raise PaperRuntimeAttestationError("Paper state lost previously attested events")
    if state["events"][:previous_count] != previous["events"]:
        raise PaperRuntimeAttestationError("Paper event-chain prefix changed after runtime lock")
    legacy_count = int(prior_attestation["legacy_completed_bar_count"])
    core = _attestation_core(
        state=state,
        runtime=runtime,
        legacy_completed_bar_count=legacy_count,
        legacy_state_digest=prior_attestation["legacy_state_digest_at_requalification"],
        replay_digest=prior_attestation["historical_replay_target_digest"],
    )
    attestation = {**core, "attestation_digest": _digest(core)}
    verify_attestation(attestation, state, config, runtime)
    _atomic_json(output_path, attestation)
    return attestation


def verify_files(
    *,
    manifest_path: Path,
    state_path: Path,
    attestation_path: Path,
    lock_path: Path,
    verify_installed: bool,
) -> dict[str, Any]:
    config, _ = forward.load_contract(manifest_path.resolve())
    state = json.loads(state_path.read_text(encoding="utf-8"))
    attestation = json.loads(attestation_path.read_text(encoding="utf-8"))
    runtime = load_locked_runtime(lock_path.resolve(), verify_installed=verify_installed)
    verify_attestation(attestation, state, config, runtime)
    return attestation


def main() -> int:
    parser = argparse.ArgumentParser(description="Bind prospective Paper evidence to an exact Python runtime lock.")
    sub = parser.add_subparsers(dest="command", required=True)

    requal = sub.add_parser("requalify")
    requal.add_argument("--manifest", type=Path, required=True)
    requal.add_argument("--state", type=Path, required=True)
    requal.add_argument("--lock", type=Path, required=True)
    requal.add_argument("--output", type=Path, required=True)

    reb = sub.add_parser("rebind")
    reb.add_argument("--manifest", type=Path, required=True)
    reb.add_argument("--previous-state", type=Path, required=True)
    reb.add_argument("--state", type=Path, required=True)
    reb.add_argument("--attestation", type=Path, required=True)
    reb.add_argument("--lock", type=Path, required=True)
    reb.add_argument("--output", type=Path, required=True)

    ver = sub.add_parser("verify")
    ver.add_argument("--manifest", type=Path, required=True)
    ver.add_argument("--state", type=Path, required=True)
    ver.add_argument("--attestation", type=Path, required=True)
    ver.add_argument("--lock", type=Path, required=True)
    ver.add_argument("--check-installed", action="store_true")

    args = parser.parse_args()
    if args.command == "requalify":
        result = requalify(
            manifest_path=args.manifest,
            state_path=args.state,
            lock_path=args.lock,
            output_path=args.output,
        )
    elif args.command == "rebind":
        result = rebind(
            manifest_path=args.manifest,
            previous_state_path=args.previous_state,
            state_path=args.state,
            attestation_path=args.attestation,
            lock_path=args.lock,
            output_path=args.output,
        )
    else:
        result = verify_files(
            manifest_path=args.manifest,
            state_path=args.state,
            attestation_path=args.attestation,
            lock_path=args.lock,
            verify_installed=args.check_installed,
        )
    print(json.dumps({
        "schema_version": result["schema_version"],
        "requirements_lock_sha256": result["requirements_lock_sha256"],
        "python_version": result["python_version"],
        "legacy_completed_bar_count": result["legacy_completed_bar_count"],
        "historical_target_replay_verified": result["historical_target_replay_verified"],
        "historical_zero_execution_exposure_verified": result["historical_zero_execution_exposure_verified"],
        "lock_enforced_from_sequence": result["lock_enforced_from_sequence"],
        "lock_enforced_event_count": result["lock_enforced_event_count"],
        "bound_completed_bar_count": result["bound_completed_bar_count"],
        "attestation_digest": result["attestation_digest"],
        "live_trading_enabled": result["live_trading_enabled"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
