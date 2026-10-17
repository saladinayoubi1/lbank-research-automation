"""Discover V50 fixed 3m degree and as-of safeguards in Elliott research CI."""
import sys
from pathlib import Path
_ROOT=Path(__file__).resolve().parents[1]/"research"
for _dir in ("elliott_v40_nested_proof","elliott_v49_fixed_child","elliott_v50_fixed_degree"):
    sys.path.insert(0,str(_ROOT/_dir))
from test_degree_v50 import V50FixedDegreeTests  # noqa: E402,F401
