from __future__ import annotations

from pathlib import Path

from product_offline_web_server import build_handler as build_offline_handler
from product_runtime import ProductRuntime
from product_web_server import DESKTOP_DEMO_OPENING_CASH
from web_dashboard import GatewayConfig


def _offline_handler(data_root: Path, **kwargs):
    data_root.mkdir(parents=True, exist_ok=True)
    return build_offline_handler(
        data_root,
        config=GatewayConfig(mode="local", host="127.0.0.1", port=8765),
        **kwargs,
    )


def test_packaged_offline_first_fresh_paper_uses_owner_500_default(tmp_path: Path) -> None:
    root = tmp_path / "fresh"
    assert DESKTOP_DEMO_OPENING_CASH == "500"
    _offline_handler(root / "market")
    observed = ProductRuntime(root, opening_cash="999")
    snapshot = observed.paper_snapshot()
    assert snapshot["account"]["cash"] == "500"
    assert snapshot["account"]["equity"] == "500"
    assert snapshot["account"]["positions"] == []
    assert snapshot["event_count"] == 2
    assert snapshot["paper_only"] is True
    assert snapshot["live_trading_authority"] is False

    before = observed.paper_events_path.read_bytes()
    _offline_handler(root / "market")
    assert observed.paper_events_path.read_bytes() == before


def test_packaged_offline_first_preserves_existing_legacy_journal(tmp_path: Path) -> None:
    root = tmp_path / "historical"
    existing = ProductRuntime(root, opening_cash="10000")
    before = existing.paper_events_path.read_bytes()
    _offline_handler(root / "market")
    assert existing.paper_events_path.read_bytes() == before
    snapshot = ProductRuntime(root, opening_cash="500").paper_snapshot()
    assert snapshot["account"]["cash"] == "10000"


def test_packaged_offline_first_honors_explicit_runtime(tmp_path: Path) -> None:
    root = tmp_path / "injected"
    custom = ProductRuntime(root, opening_cash="743")
    before = custom.paper_events_path.read_bytes()
    _offline_handler(root / "market", runtime=custom)
    assert custom.paper_events_path.read_bytes() == before
    assert custom.paper_snapshot()["account"]["cash"] == "743"
