"""Discover 11 immutable V78 historical stop-bar OHLC ambiguity regressions."""
import sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]/"research"
sys.path.insert(0,str(root/"elliott_v78_historical_stopbar_ambiguity"))
from test_v78 import V78StopBarAmbiguityTests  # noqa: E402,F401
