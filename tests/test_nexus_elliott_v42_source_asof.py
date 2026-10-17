"""Discover V42 source as-of and V40 no-witness regressions in native Elliott CI."""
import sys
from pathlib import Path

RESEARCH=Path(__file__).resolve().parents[1]/"research"
sys.path.insert(0,str(RESEARCH/"elliott_v40_nested_proof"))
sys.path.insert(0,str(RESEARCH/"elliott_v42_source_asof"))
from test_source_asof_v42 import SourceAsOfV42Tests  # noqa: E402,F401
