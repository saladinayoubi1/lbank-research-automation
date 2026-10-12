"""Prevent scheduled portfolio adapter from mutating the canonical simulator on import."""
from __future__ import annotations

import subprocess
import sys


def test_scheduled_import_does_not_replace_canonical_exact_engine():
    script = (
        "import bybit_portfolio_search_v3 as canonical\n"
        "original = canonical.exact_backtest\n"
        "import bybit_portfolio_search_v3_scheduled as adapter\n"
        "assert canonical.exact_backtest is original\n"
        "assert adapter.exact_backtest is not original\n"
        "assert 'rebalance_mask' in original.__code__.co_varnames\n"
    )
    finished = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True, check=False, timeout=25,
    )
    assert finished.returncode == 0, finished.stdout + finished.stderr
