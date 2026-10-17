"""Discover separate five-minute Elliott child-degree exploratory regressions."""
import sys
from pathlib import Path
_ROOT=Path(__file__).resolve().parents[1]/"research"
for _directory in ("elliott_v40_nested_proof","elliott_v49_fixed_child",
                   "elliott_v50_fixed_degree","elliott_v64_alternative_5m"):
    sys.path.insert(0,str(_ROOT/_directory))
from test_degree_v64 import V64AlternateDegreeResearchTests  # noqa: F401,E402
