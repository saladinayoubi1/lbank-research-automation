from __future__ import annotations

from pathlib import Path

import pytest

from nexus_strategy_paper_supervisor import StrategyPaperSupervisorError, run_once


SOURCE_SHA = "a" * 40
NOW_MS = 1_800_000_000_000
DATASET_SHA = "b" * 64


class _KilledResearch:
    def run_research(self, *, symbol: str, timeframe: str, family: str, limit: int):
        return {
            "qualification": {
                "status": "killed",
                "qualification_digest": "c" * 64,
                "kill_reasons": ["bounded_test_fixture"],
            }
        }


def _research_factory(_runtime, _source_sha, _dataset, _now_ms):
    return _KilledResearch()


@pytest.mark.parametrize(
    ("symbol", "timeframe", "canonical_symbol", "interval"),
    [
        ("SOLUSDT", "minute15", "SOL/USDT", "15"),
        ("SOLUSDT", "hour1", "SOL/USDT", "60"),
        ("SOLUSDT", "hour4", "SOL/USDT", "240"),
        ("XRPUSDT", "minute15", "XRP/USDT", "15"),
        ("XRPUSDT", "hour1", "XRP/USDT", "60"),
        ("XRPUSDT", "hour4", "XRP/USDT", "240"),
    ],
)
def test_supervisor_resolves_new_pairs_from_canonical_registry(
    tmp_path: Path,
    symbol: str,
    timeframe: str,
    canonical_symbol: str,
    interval: str,
) -> None:
    calls: list[dict] = []

    def fetcher(**kwargs):
        calls.append(dict(kwargs))
        return {"binding_sha256": DATASET_SHA}

    ledger = run_once(
        source_sha=SOURCE_SHA,
        state_root=tmp_path / symbol / timeframe,
        symbol=symbol,
        timeframe=timeframe,
        families=("momentum",),
        limit=240,
        now_ms=NOW_MS,
        dataset_fetcher=fetcher,
        research_factory=_research_factory,
    )

    assert len(calls) == 1
    assert calls[0]["canonical_symbol"] == canonical_symbol
    assert calls[0]["source_symbol"] == symbol
    assert calls[0]["interval"] == interval
    assert ledger["symbol"] == symbol
    assert ledger["timeframe"] == timeframe
    assert ledger["dataset_binding_sha256"] == DATASET_SHA
    assert ledger["final_status"] == "VERIFIED"
    assert ledger["verification"]["decision"] == "pass"
    assert ledger["paper_only"] is True
    assert ledger["live_trading_authority"] is False
    assert ledger["tasks"][0]["status"] == "qualification_killed"
    assert ledger["tasks"][0]["paper_only"] is True
    assert ledger["tasks"][0]["live_trading_authority"] is False


def test_unknown_symbol_fails_before_dataset_or_paper_state(tmp_path: Path) -> None:
    called = False

    def fetcher(**_kwargs):
        nonlocal called
        called = True
        return {"binding_sha256": DATASET_SHA}

    state_root = tmp_path / "unknown"
    with pytest.raises(
        StrategyPaperSupervisorError,
        match="unsupported or non-canonical matrix symbol/timeframe",
    ):
        run_once(
            source_sha=SOURCE_SHA,
            state_root=state_root,
            symbol="DOGEUSDT",
            timeframe="minute15",
            families=("momentum",),
            now_ms=NOW_MS,
            dataset_fetcher=fetcher,
            research_factory=_research_factory,
        )

    assert called is False
    assert not state_root.exists()
