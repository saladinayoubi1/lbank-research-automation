"""Owner-local strategy research workspace: editable hypotheses, never executable authority.

This is an intentionally separate state file. Neither selection nor proposal creation
can mutate a Paper journal, dispatch unchecked code or qualify a strategy.
"""
from __future__ import annotations

import json
import math
import os
import re
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

WORKSPACE_CONTRACT = "nexus.product-strategy-workspace.v1"
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT")
TIMEFRAMES = ("15m", "1h", "4h")
DATA_TYPES = ("closed_ohlcv", "aligned_peer_ohlcv", "authenticated_trade_flow",
              "open_interest", "funding_rate", "order_book_l2")
# Reviewed engine inventory from nexus_composite_strategy_research.py. These are
# NOT advertised as executable through the small manual product preset runner.
COMPOSITE = (
    ("structural_pullback", "Structural pullback", ("closed_ohlcv",)),
    ("volatility_compression_expansion", "Volatility compression / expansion", ("closed_ohlcv",)),
    ("bar_proxy_vwap_reclaim", "Bar-volume proxy reclaim", ("closed_ohlcv",)),
    ("failed_range_break_reversal", "Failed range breakout reversal", ("closed_ohlcv",)),
    ("cross_pair_relative_reclaim", "Cross-pair relative reclaim", ("closed_ohlcv", "aligned_peer_ohlcv")),
    ("lagged_peer_impulse_confirmation", "Lagged peer impulse", ("closed_ohlcv", "aligned_peer_ohlcv")),
    ("peer_shock_noncontagion_rebound", "Peer-shock non-contagion", ("closed_ohlcv", "aligned_peer_ohlcv")),
)
MANUAL = (
    ("momentum", "Momentum reference"),
    ("trend_breakout", "Trend breakout reference"),
    ("mean_reversion", "Mean reversion reference"),
)
MAX_WORKSPACE_BYTES = 2_000_000
MAX_PROPOSALS = 512
_HEX = re.compile(r"^[0-9a-f]{32}$")
_LOCK = threading.RLock()


class StrategyWorkspaceError(ValueError):
    """Fail-closed owner workspace input or local storage problem."""


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _catalog() -> list[dict[str, Any]]:
    return [
        {"id": "composite:" + key, "name": label, "mechanism": key,
         "kind": "reviewed_causal_family", "required_data": list(inputs),
         "execution": "requires_verified_research_worker",
         "paper_admission": False, "live_enabled": False}
        for key, label, inputs in COMPOSITE
    ] + [
        {"id": "manual:" + key, "name": label, "mechanism": key,
         "kind": "legacy_reference_only", "required_data": ["closed_ohlcv"],
         "execution": "canonical_manual_offline_available",
         "paper_admission": False, "live_enabled": False}
        for key, label in MANUAL
    ]


def _text(value: Any, name: str, lo: int, hi: int) -> str:
    if not isinstance(value, str) or not lo <= len(value.strip()) <= hi:
        raise StrategyWorkspaceError(f"{name} must contain {lo}..{hi} characters")
    # No opaque code/HTML or filesystem inputs are accepted as strategy logic.
    if any(ord(char) < 32 and char not in "\n\t" for char in value):
        raise StrategyWorkspaceError(f"{name} contains control characters")
    return value.strip()


def _list(value: Any, name: str, choices: tuple[str, ...], maximum: int) -> list[str]:
    if not isinstance(value, list) or not 1 <= len(value) <= maximum or any(
        not isinstance(item, str) or item not in choices for item in value
    ) or len(set(value)) != len(value):
        raise StrategyWorkspaceError(f"{name} contains invalid or duplicate entries")
    return value


def _metric(value: Any) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        return None
    return value if math.isfinite(value) else None


def _historical_rows(history: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Only show measured local research-ledger values; never fill missing metrics."""
    result = []
    for record in history.get("runs", [])[-50:]:
        if not isinstance(record, Mapping):
            continue
        request = record.get("request", {})
        dataset = record.get("dataset", {})
        backtest = record.get("backtest", {})
        qualification = record.get("qualification", {})
        if not all(isinstance(row, Mapping) for row in (request, dataset, backtest, qualification)):
            continue
        metrics = backtest.get("metrics", {})
        if not isinstance(metrics, Mapping):
            continue
        binding = dataset.get("binding_sha256")
        if not isinstance(binding, str) or re.fullmatch("[0-9a-f]{64}", binding) is None:
            continue
        evidence = record.get("evidence", {})
        if not isinstance(evidence, Mapping):
            evidence = {}
        result.append({
            "recorded_at": record.get("recorded_at"),
            "family": request.get("family"), "symbol": request.get("symbol"),
            "timeframe": request.get("timeframe"), "row_count": dataset.get("row_count"),
            "dataset_binding_sha256": binding,
            "source_sha": record.get("source_sha") or qualification.get("source_sha"),
            "qualification": qualification.get("status", "unverified"),
            "reason": qualification.get("kill_reasons", []),
            "total_return": _metric(metrics.get("total_return")),
            "max_drawdown": _metric(metrics.get("max_drawdown")),
            "fill_count": _metric(metrics.get("fill_count")),
            "win_rate": _metric(metrics.get("win_rate")),
            "profit_factor": _metric(metrics.get("profit_factor")),
            "stress": _metric(evidence.get("stress_score")),
            "data_mode": record.get("data_mode", "online_canonical"),
            "independent_qa_verified": False,
            "pristine_oos_verified": False,
            "auto_demo_promotion": False,
        })
    return result


class StrategyWorkspace:
    """Versioned, atomic, owner-local write/selection store with no trading hooks."""

    def __init__(self, root: Path) -> None:
        self.path = Path(root) / "product_runtime" / "strategy-workspace.v1.json"

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"contract_version": WORKSPACE_CONTRACT, "revision": 0,
                    "selected_id": None, "proposals": []}
        if self.path.is_symlink() or not self.path.is_file() or not 2 <= self.path.stat().st_size <= MAX_WORKSPACE_BYTES:
            raise StrategyWorkspaceError("unsafe owner strategy workspace file")
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise StrategyWorkspaceError("owner strategy workspace cannot be decoded") from exc
        if (not isinstance(value, dict) or value.get("contract_version") != WORKSPACE_CONTRACT
                or type(value.get("revision")) is not int or not isinstance(value.get("proposals"), list)
                or len(value["proposals"]) > MAX_PROPOSALS):
            raise StrategyWorkspaceError("owner strategy workspace contract mismatch")
        return value

    def _save(self, state: Mapping[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.parent.is_symlink() or (self.path.exists() and self.path.is_symlink()):
            raise StrategyWorkspaceError("owner strategy workspace cannot use symlinks")
        payload = json.dumps(state, ensure_ascii=False, sort_keys=True,
                             allow_nan=False, separators=(",", ":")).encode("utf-8")
        if len(payload) > MAX_WORKSPACE_BYTES:
            raise StrategyWorkspaceError("owner strategy workspace exceeds size bound")
        fd, tmp = tempfile.mkstemp(prefix=".strategy-workspace-", dir=self.path.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def _known(self, state: Mapping[str, Any]) -> set[str]:
        return {item["id"] for item in _catalog()} | {
            row["id"] for row in state["proposals"]
            if isinstance(row, dict) and isinstance(row.get("id"), str)
        }

    def snapshot(self, *, evidence: Mapping[str, Any] | None = None,
                 datasets: Mapping[str, Any] | None = None) -> dict[str, Any]:
        with _LOCK:
            state = self._read()
        evidence = evidence or {}
        datasets = datasets or {}
        selected = state.get("selected_id")
        if selected is not None and selected not in self._known(state):
            raise StrategyWorkspaceError("selected strategy is no longer valid")
        data = datasets.get("datasets", [])
        return {
            "contract_version": WORKSPACE_CONTRACT, "revision": state["revision"],
            "selected_id": selected, "catalog": _catalog(), "proposals": state["proposals"],
            "datasets": data if isinstance(data, list) else [],
            "history": _historical_rows(evidence),
            "run_count": evidence.get("run_count", 0),
            "agent_evidence_integrated": False,
            "agent_evidence_reason": "Requires a source-bound real Research Agent report and independent QA receipt",
            "selected_means": "research_focus_only",
            "auto_demo_promotion": False, "live_enabled": False, "paper_only": True,
        }

    def create(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        required = {"name", "mechanism", "hypothesis", "invalidation",
                    "symbols", "timeframes", "required_data"}
        if not isinstance(payload, Mapping) or set(payload) != required:
            raise StrategyWorkspaceError("strategy proposal schema mismatch")
        name = _text(payload["name"], "name", 3, 100)
        mechanism = _text(payload["mechanism"], "mechanism", 5, 120)
        hypothesis = _text(payload["hypothesis"], "hypothesis", 20, 1200)
        invalidation = _text(payload["invalidation"], "invalidation", 20, 1200)
        symbols = _list(payload["symbols"], "symbols", SYMBOLS, len(SYMBOLS))
        timeframes = _list(payload["timeframes"], "timeframes", TIMEFRAMES, len(TIMEFRAMES))
        inputs = _list(payload["required_data"], "required_data", DATA_TYPES, len(DATA_TYPES))
        with _LOCK:
            state = self._read()
            if len(state["proposals"]) >= MAX_PROPOSALS:
                raise StrategyWorkspaceError("workspace file retention full; export before adding more")
            # The workspace is a design queue, never arbitrary Python/JS execution.
            proposal = {
                "id": "proposal:" + uuid.uuid4().hex,
                "name": name, "mechanism": mechanism, "hypothesis": hypothesis,
                "invalidation": invalidation, "symbols": symbols, "timeframes": timeframes,
                "required_data": inputs, "kind": "owner_research_proposal",
                "status": "requires_developer_and_independent_qa",
                "execution": "not_implemented", "auto_demo_promotion": False,
                "live_enabled": False, "created_at": _utc(),
            }
            state["proposals"].append(proposal)
            state["revision"] += 1
            self._save(state)
        return proposal

    def select(self, proposal_id: str) -> dict[str, Any]:
        if not isinstance(proposal_id, str) or len(proposal_id) > 80:
            raise StrategyWorkspaceError("invalid selection")
        with _LOCK:
            state = self._read()
            if proposal_id not in self._known(state):
                raise StrategyWorkspaceError("unknown strategy id")
            state["selected_id"] = proposal_id
            state["revision"] += 1
            self._save(state)
            return {"contract_version": WORKSPACE_CONTRACT, "selected_id": proposal_id,
                    "revision": state["revision"], "selection_is_not_execution": True,
                    "paper_only": True, "live_enabled": False}

    def selected_manual_family(self, strategy_id: str) -> str:
        with _LOCK:
            state = self._read()
        if not isinstance(strategy_id, str) or strategy_id != state.get("selected_id"):
            raise StrategyWorkspaceError("run requires explicitly selected strategy")
        allowed = {"manual:" + family: family for family, _ in MANUAL}
        if strategy_id not in allowed:
            raise StrategyWorkspaceError("this hypothesis requires a reviewed Research Agent implementation; it cannot be executed as a legacy preset")
        return allowed[strategy_id]
