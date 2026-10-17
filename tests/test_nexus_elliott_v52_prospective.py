"""Discover V52 prospective source, holdout embargo and no-trading tests."""
import sys
from pathlib import Path
_ROOT=Path(__file__).resolve().parents[1]/"research"
sys.path.insert(0,str(_ROOT/"elliott_v52_prospective"))
from test_prospective_v52 import V52ProspectiveGateTests  # noqa: E402,F401
