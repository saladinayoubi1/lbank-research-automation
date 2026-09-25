from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from paper_event_store import build_event
from product_runtime import ProductRuntime, _paper_provenance, _utc_now
from scripts.reset_owner_desktop_demo_500 import DemoBalanceResetError, reset_closed_unused_desktop_demo


def close_unused_session(runtime: ProductRuntime) -> None:
    events = runtime._read_events()
    at = _utc_now()
    closing = build_event(
        event_id="test:session:3", event_type="session_boundary_recorded",
        aggregate_id=events[0]["aggregate_id"], sequence=len(events) + 1,
        occurred_at=at, correlation_id="test-closed-session",
        causation_id="test-closed-session",
        provenance=_paper_provenance(timeframe="session", at=at),
        previous_event_digest=events[-1]["event_digest"],
        payload={"boundary": "close"},
    )
    runtime._write_events([*events, closing])


def test_unused_owner_demo_resets_to_500_with_immutable_archive(tmp_path: Path) -> None:
    owner = ProductRuntime(tmp_path, opening_cash="10000")
    close_unused_session(owner)
    prior = owner.paper_events_path.read_bytes()
    historical = tmp_path / "prospective-paper-immutable.json"
    historical.write_text('{"status":"QUARANTINED"}', encoding="utf-8")
    proof = reset_closed_unused_desktop_demo(tmp_path)
    assert proof["status"] == "verified"
    assert proof["previous_journal_sha256"] == hashlib.sha256(prior).hexdigest()
    archive = tmp_path / "demo-account-archives" / proof["archived_journal"]
    assert archive.read_bytes() == prior
    assert historical.read_text(encoding="utf-8") == '{"status":"QUARANTINED"}'
    current = ProductRuntime(tmp_path).paper_snapshot()
    assert current["account"]["cash"] == "500"
    assert current["account"]["equity"] == "500"
    assert current["account"]["session_open"] is False
    assert current["account"]["positions"] == []
    assert current["event_count"] == 3
    assert current["live_trading_authority"] is False
    assert proof["historical_prospective_evidence_modified"] is False
    current_journal = owner.paper_events_path.read_bytes()
    with pytest.raises(DemoBalanceResetError, match="not the closed, unused"):
        reset_closed_unused_desktop_demo(tmp_path)
    assert owner.paper_events_path.read_bytes() == current_journal


def test_owner_reset_rejects_open_session_and_nonlegacy_wallet(tmp_path: Path) -> None:
    owner = ProductRuntime(tmp_path / "open", opening_cash="10000")
    prior = owner.paper_events_path.read_bytes()
    with pytest.raises(DemoBalanceResetError, match="not the closed, unused"):
        reset_closed_unused_desktop_demo(tmp_path / "open")
    assert owner.paper_events_path.read_bytes() == prior
    assert not (tmp_path / "open" / "demo-account-archives").exists()

    new = ProductRuntime(tmp_path / "new", opening_cash="500")
    close_unused_session(new)
    prior = new.paper_events_path.read_bytes()
    with pytest.raises(DemoBalanceResetError, match="not the closed, unused"):
        reset_closed_unused_desktop_demo(tmp_path / "new")
    assert new.paper_events_path.read_bytes() == prior
