"""Verify daily Elliott candidates cannot leak from warmup or re-score."""
import sys
from pathlib import Path
_ROOT=Path(__file__).resolve().parents[1]/"research"
for _d in ("elliott_v40_nested_proof","elliott_v49_fixed_child",
           "elliott_v50_fixed_degree","elliott_v52_prospective",
           "elliott_v53_prospective_scan","elliott_v54_score_exclusivity"):
    sys.path.insert(0,str(_ROOT/_d))
from test_score_exclusivity_v54 import V54DailyExclusivityTests  # noqa: E402,F401
