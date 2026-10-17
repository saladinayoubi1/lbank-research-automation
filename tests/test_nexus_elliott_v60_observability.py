"""Discover physical daily archive availability and retrospective-label regressions."""
import sys
from pathlib import Path
_ROOT=Path(__file__).resolve().parents[1]/"research"
for _d in ("elliott_v40_nested_proof","elliott_v49_fixed_child",
           "elliott_v50_fixed_degree","elliott_v52_prospective",
           "elliott_v53_prospective_scan","elliott_v55_source_intake",
           "elliott_v57_attested_scan","elliott_v58_tls_source_capture",
           "elliott_v59_capture_chain","elliott_v60_observability"):
    sys.path.insert(0,str(_ROOT/_d))
from test_observability_v60 import V60SourceObservabilityTests  # noqa: F401,E402
