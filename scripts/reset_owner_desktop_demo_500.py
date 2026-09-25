"""Owner-only, audited reset of an unused closed desktop Paper wallet to 500 USDT.

This never touches historical prospective Paper artifacts, research capital or Live.
Old event-sourced journal is verified and archived before atomic replacement.
Only the explicitly unused 10000-USDT desktop account can be reset.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from paper_event_store import GENESIS_DIGEST, build_event, replay  # noqa: E402
from product_runtime import (  # noqa: E402
    PAPER_ACCOUNT_ID, PAPER_CURRENCY, ProductRuntime, _paper_provenance, _utc_now,
)


class DemoBalanceResetError(RuntimeError):
    pass


def reset_closed_unused_desktop_demo(root: Path) -> dict:
    root = Path(root).resolve(strict=True)
    journal = root / "product_runtime" / "paper-events.jsonl"
    if journal.is_symlink() or not journal.is_file() or journal.stat().st_size > 16_000_000:
        raise DemoBalanceResetError("existing local Paper journal missing or unsafe")
    runtime = ProductRuntime(root, opening_cash="500")
    events = runtime._read_events()
    state = replay(events).state
    allowed = {"demo_account_opened", "session_boundary_recorded", "kill_switch_transitioned"}
    if (
        not events or events[0]["event_type"] != "demo_account_opened"
        or events[0]["payload"] != {"currency": PAPER_CURRENCY, "opening_cash": "10000"}
        or any(event["event_type"] not in allowed for event in events)
        or state.aggregate_id != PAPER_ACCOUNT_ID or state.currency != PAPER_CURRENCY
        or str(state.cash) != "10000" or str(state.equity) != "10000"
        or state.positions or state.realized_pnl != 0 or state.unrealized_pnl != 0
        or state.session_open or state.kill_switch_enabled
    ):
        raise DemoBalanceResetError("wallet is not the closed, unused 10000-USDT Paper account")
    old_bytes = journal.read_bytes()
    old_sha = hashlib.sha256(old_bytes).hexdigest()
    if len(old_bytes.splitlines()) != len(events):
        raise DemoBalanceResetError("journal changed during verification")
    archive_dir = root / "demo-account-archives"
    archive_dir.mkdir(mode=0o700, exist_ok=True)
    reset_id = uuid.uuid4().hex
    archive = archive_dir / f"before-500-{reset_id}.jsonl"
    with archive.open("xb") as handle:
        handle.write(old_bytes)
        handle.flush()
        os.fsync(handle.fileno())
    if hashlib.sha256(archive.read_bytes()).hexdigest() != old_sha:
        raise DemoBalanceResetError("journal archive verification failed")

    at = _utc_now()
    provenance = _paper_provenance(timeframe="session", at=at)
    correlation = f"owner-paper-reset-{reset_id}"
    account = build_event(
        event_id="product:account:1", event_type="demo_account_opened",
        aggregate_id=PAPER_ACCOUNT_ID, sequence=1, occurred_at=at,
        correlation_id=correlation, causation_id=correlation,
        provenance=provenance, previous_event_digest=GENESIS_DIGEST,
        payload={"currency": PAPER_CURRENCY, "opening_cash": "500"},
    )
    opened = build_event(
        event_id="product:account:2", event_type="session_boundary_recorded",
        aggregate_id=PAPER_ACCOUNT_ID, sequence=2, occurred_at=at,
        correlation_id=correlation, causation_id=correlation,
        provenance=provenance, previous_event_digest=account["event_digest"],
        payload={"boundary": "open"},
    )
    closed = build_event(
        event_id="product:account:3", event_type="session_boundary_recorded",
        aggregate_id=PAPER_ACCOUNT_ID, sequence=3, occurred_at=at,
        correlation_id=correlation, causation_id=correlation,
        provenance=provenance, previous_event_digest=opened["event_digest"],
        payload={"boundary": "close"},
    )
    new_events = [account, opened, closed]
    new_state = replay(new_events).state
    if new_state.cash != 500 or new_state.session_open or new_state.positions:
        raise DemoBalanceResetError("new closed 500-USDT journal verification failed")
    new_bytes = "".join(
        json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
        for event in new_events
    ).encode("utf-8")
    if hashlib.sha256(journal.read_bytes()).hexdigest() != old_sha:
        raise DemoBalanceResetError("Paper journal changed before atomic swap")
    temporary = journal.with_name(f".owner-reset-{reset_id}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(new_bytes)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, journal)
    finally:
        temporary.unlink(missing_ok=True)
    applied = runtime._read_events()
    applied_state = replay(applied).state
    if (applied_state.cash != 500 or applied_state.equity != 500
            or applied_state.session_open or applied_state.positions
            or applied_state.last_event_digest != closed["event_digest"]):
        raise DemoBalanceResetError("installed desktop journal does not match 500-USDT proof")
    audit = {
        "status": "verified", "paper_only": True, "live_trading_authority": False,
        "previous_opening_cash": "10000", "new_opening_cash": "500",
        "previous_event_count": len(events), "new_event_count": len(applied),
        "previous_journal_sha256": old_sha,
        "previous_head_digest": state.last_event_digest,
        "new_journal_sha256": hashlib.sha256(journal.read_bytes()).hexdigest(),
        "new_head_digest": applied_state.last_event_digest,
        "archived_journal": archive.name,
        "reset_id": reset_id, "reset_at": at,
        "historical_prospective_evidence_modified": False,
    }
    with (archive_dir / f"reset-proof-{reset_id}.json").open("x", encoding="utf-8") as handle:
        json.dump(audit, handle, sort_keys=True, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    return audit


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--confirm-closed-unused-demo-reset", action="store_true", required=True)
    args = parser.parse_args()
    print(json.dumps(reset_closed_unused_desktop_demo(args.root), sort_keys=True))


if __name__ == "__main__":
    main()
