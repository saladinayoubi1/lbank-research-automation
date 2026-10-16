"""Native discovery for physical-first V69 source-observability tests."""
import sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]/"research"
for name in (
 "elliott_v40_nested_proof","elliott_v49_fixed_child",
 "elliott_v50_fixed_degree","elliott_v52_prospective",
 "elliott_v53_prospective_scan","elliott_v55_source_intake",
 "elliott_v57_attested_scan","elliott_v58_tls_source_capture",
 "elliott_v59_capture_chain","elliott_v60_observability",
 "elliott_v69_source_asof_gate",
):
    sys.path.insert(0,str(root/name))
from test_source_asof_v69 import V69SourceAvailabilityTests  # noqa: F401,E402
