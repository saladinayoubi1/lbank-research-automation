"""Discover V72 independent Elliott legacy prefix-causality tests."""
import sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]/"research"
sys.path.insert(0,str(root/"elliott_v72_legacy_prefix_causality"))
from test_prefix_v72 import V72HistoricalPrefixTests  # noqa: E402,F401
