"""Bounded recovery for legacy Demo replay journals created on the wrong clock.

Only an intact ProductRuntime bootstrap-only journal may be quarantined. Journals
that contain any stateful Paper activity remain fail-closed and are never reset.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from nexus_demo_archive_replay import ARCHIVE_SHA256, next_replay_now_ms
from nexus_demo_strategy_matrix import load_manifest, load_state
from paper_event_store import replay, validate_event

SCHEMA = "nexus.demo-bootstrap-clock-recovery.v1"
SUMMARY_SCHEMA = "nexus.demo-bootstrap-clock-recovery-summary.v1"
Resolver = Callable[[str, str, int, int], int]


class DemoStateRecoveryError(RuntimeError):
    pass


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise DemoStateRecoveryError("recovery evidence is not canonical JSON") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(dict(value), indent=2, sort_keys=True, ensure_ascii=False))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except OSError as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise DemoStateRecoveryError("failed to persist recovery evidence") from exc


def _utc_ms(value: Any) -> int:
    if not isinstance(value, str) or not value or len(value) > 64:
        raise DemoStateRecoveryError("Paper journal timestamp is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DemoStateRecoveryError("Paper journal timestamp is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise DemoStateRecoveryError("Paper journal timestamp must be UTC")
    return int(parsed.timestamp() * 1000)


def _read_journal(path: Path) -> tuple[list[dict[str, Any]], bytes]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 20_000_000:
        raise DemoStateRecoveryError("Paper journal is unavailable or unsafe")
    try:
        raw = path.read_bytes()
        rows: list[dict[str, Any]] = []
        for index, line in enumerate(raw.decode("utf-8").splitlines(), start=1):
            if index > 100_000 or not line.strip():
                raise DemoStateRecoveryError("Paper journal is invalid or unbounded")
            value = json.loads(line)
            if not isinstance(value, dict):
                raise DemoStateRecoveryError("Paper journal row is not an object")
            rows.append(validate_event(value))
        if rows:
            replay(rows)
        return rows, raw
    except DemoStateRecoveryError:
        raise
    except Exception as exc:
        raise DemoStateRecoveryError("Paper journal cannot be verified for recovery") from exc


def _is_product_bootstrap_only(rows: list[dict[str, Any]]) -> bool:
    if len(rows) != 2:
        return False
    account, session = rows
    return bool(
        account.get("event_id") == "product:account:1"
        and account.get("event_type") == "demo_account_opened"
        and account.get("sequence") == 1
        and account.get("aggregate_id") == "nexus-demo-paper"
        and account.get("correlation_id") == "product-bootstrap"
        and account.get("causation_id") == "product-bootstrap-account"
        and account.get("payload", {}).get("currency") == "USDT"
        and session.get("event_id") == "product:account:2"
        and session.get("event_type") == "session_boundary_recorded"
        and session.get("sequence") == 2
        and session.get("aggregate_id") == account.get("aggregate_id")
        and session.get("correlation_id") == "product-bootstrap"
        and session.get("causation_id") == "product-bootstrap-session"
        and session.get("payload") == {"boundary": "open"}
        and session.get("previous_event_digest") == account.get("event_digest")
        and account.get("paper_trading_only") is True
        and session.get("paper_trading_only") is True
    )


def recover_bootstrap_journals(
    *,
    manifest: Mapping[str, Any],
    state: Mapping[str, Any],
    state_root: str | Path,
    logical_now_resolver: Resolver,
) -> dict[str, Any]:
    """Quarantine only future-dated bootstrap-only journals before archive replay."""
    root = Path(state_root).resolve()
    prior_cells = state.get("cells", {})
    if not isinstance(prior_cells, Mapping):
        raise DemoStateRecoveryError("matrix state cells are invalid")
    recovered: list[dict[str, Any]] = []

    for symbol in manifest["symbols"]:
        for timeframe in manifest["timeframes"]:
            cell_id = f"{symbol}:{timeframe}"
            previous = prior_cells.get(cell_id, {})
            if not isinstance(previous, Mapping):
                raise DemoStateRecoveryError("matrix cell state is invalid")
            previous_open = previous.get("last_completed_open_ms", -1)
            if isinstance(previous_open, bool) or not isinstance(previous_open, int):
                raise DemoStateRecoveryError("matrix cell cursor is invalid")
            logical_now_ms = logical_now_resolver(
                symbol, timeframe, previous_open, int(manifest["history_limit"])
            )
            if isinstance(logical_now_ms, bool) or not isinstance(logical_now_ms, int) or logical_now_ms <= 0:
                raise DemoStateRecoveryError("logical replay clock is invalid")

            for family in manifest["families"]:
                runtime_dir = (
                    root / "cells" / symbol.lower() / timeframe
                    / "portfolios" / family / "product_runtime"
                )
                journal = runtime_dir / "paper-events.jsonl"
                if not journal.exists():
                    continue
                rows, raw = _read_journal(journal)
                if not rows:
                    continue
                legacy_last_ms = _utc_ms(rows[-1].get("occurred_at"))
                if legacy_last_ms <= logical_now_ms:
                    continue
                if not _is_product_bootstrap_only(rows):
                    raise DemoStateRecoveryError(
                        f"{cell_id}/{family} has future-dated stateful Paper history; automatic recovery is forbidden"
                    )

                journal_sha256 = hashlib.sha256(raw).hexdigest()
                quarantine_dir = runtime_dir / "quarantine" / "bootstrap-clock"
                quarantine_dir.mkdir(parents=True, exist_ok=True)
                archived = quarantine_dir / f"{journal_sha256}.paper-events.jsonl"
                evidence_path = quarantine_dir / f"{journal_sha256}.recovery.json"
                if archived.exists() or evidence_path.exists():
                    raise DemoStateRecoveryError("recovery quarantine target already exists")
                try:
                    os.replace(journal, archived)
                except OSError as exc:
                    raise DemoStateRecoveryError("failed to quarantine legacy Paper bootstrap") from exc

                core = {
                    "schema_version": SCHEMA,
                    "cell_id": cell_id,
                    "family": family,
                    "reason": "future_bootstrap_only_clock_mismatch",
                    "logical_now_ms": logical_now_ms,
                    "legacy_last_occurred_at": rows[-1]["occurred_at"],
                    "journal_sha256": journal_sha256,
                    "quarantine_file": archived.name,
                    "paper_only": True,
                    "live_trading_authority": False,
                }
                evidence = {**core, "recovery_digest": _digest(core)}
                _atomic_json(evidence_path, evidence)
                recovered.append(evidence)

    summary_core = {
        "schema_version": SUMMARY_SCHEMA,
        "recovered_count": len(recovered),
        "recoveries": recovered,
        "paper_only": True,
        "live_trading_authority": False,
    }
    return {**summary_core, "summary_digest": _digest(summary_core)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--replay-archive-root", type=Path, required=True)
    parser.add_argument("--archive-sha256", required=True)
    args = parser.parse_args()
    if str(args.archive_sha256).lower() != ARCHIVE_SHA256:
        raise DemoStateRecoveryError("archive digest is not the approved immutable dataset")

    manifest = load_manifest(args.manifest)
    state = load_state(args.state_root / "matrix-state.json", manifest)
    summary = recover_bootstrap_journals(
        manifest=manifest,
        state=state,
        state_root=args.state_root,
        logical_now_resolver=lambda symbol, timeframe, previous, limit: next_replay_now_ms(
            args.replay_archive_root, symbol, timeframe, previous, limit
        ),
    )
    _atomic_json(args.state_root / "recovery" / "bootstrap-clock-recovery.json", summary)
    print(json.dumps({
        "status": "RECOVERED" if summary["recovered_count"] else "NO_ACTION",
        "recovered_count": summary["recovered_count"],
        "summary_digest": summary["summary_digest"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
