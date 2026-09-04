from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "nexus_multipair_runtime_requalification_snapshot.py"


def test_runtime_requalification_snapshot_module_compiles_and_keeps_boundaries() -> None:
    text = MODULE.read_text(encoding="utf-8")
    ast.parse(text)
    assert 'HISTORY_LIMIT = 240' in text
    assert 'MAX_SNAPSHOT_TRANSPORT_AGE_MS = 20 * 60 * 1000' in text
    assert 'TRANSPORT_ORIGIN = "digest_pinned_hosted_bybit_rest_snapshot"' in text
    assert 'runtime_snapshot_distinct_from_discovery' in text
    assert 'historical_discovery_snapshot_reused' in text
    assert '"paper_execution_started": False' in text
    assert '"live_trading_authority": False' in text
    assert '"automatic_strategy_promotion": False' in text
    assert '"deterministic_risk_final_authority": True' in text
