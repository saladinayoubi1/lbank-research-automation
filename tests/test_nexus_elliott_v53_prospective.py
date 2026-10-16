"""Discover V53 prospective source-day scanner and no-trade embargo tests."""
import sys
from pathlib import Path
_ROOT=Path(__file__).resolve().parents[1]/"research"
for _d in ("elliott_v40_nested_proof","elliott_v49_fixed_child",
           "elliott_v50_fixed_degree","elliott_v52_prospective",
           "elliott_v53_prospective_scan"):
    sys.path.insert(0,str(_ROOT/_d))
from test_scan_v53 import V53ProspectiveScannerTests  # noqa: E402,F401
