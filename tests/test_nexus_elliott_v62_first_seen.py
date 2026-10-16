"""Native suite discovery for immutable first-observed Elliott event tests."""
import sys
from pathlib import Path
_ROOT=Path(__file__).resolve().parents[1]/"research"
for _dir in ("elliott_v40_nested_proof","elliott_v49_fixed_child",
             "elliott_v50_fixed_degree","elliott_v52_prospective",
             "elliott_v53_prospective_scan","elliott_v62_first_observed"):
    sys.path.insert(0,str(_ROOT/_dir))
from test_first_seen_v62 import V62FirstSeenGeometryTests  # noqa: E402,F401
