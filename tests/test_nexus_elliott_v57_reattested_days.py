"""Discover real raw-trade reattestation tests before prospective scanning."""
import sys
from pathlib import Path
_ROOT=Path(__file__).resolve().parents[1]/"research"
for _d in ("elliott_v40_nested_proof","elliott_v49_fixed_child",
           "elliott_v50_fixed_degree","elliott_v52_prospective",
           "elliott_v53_prospective_scan","elliott_v55_source_intake",
           "elliott_v57_attested_scan"):
    sys.path.insert(0,str(_ROOT/_d))
from test_fully_attested_v57 import V57PhysicalRawReattestationTests  # noqa: E402,F401
