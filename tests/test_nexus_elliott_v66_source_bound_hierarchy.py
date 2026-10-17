"""Native discovery for V66 read-only physical Elliott vertex source gates."""
import sys
from pathlib import Path
_ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(_ROOT))
for _directory in ("elliott_v40_nested_proof","elliott_v49_fixed_child",
                   "elliott_v65_hierarchical_geometry","elliott_v66_source_bound_hierarchy"):
    sys.path.insert(0,str(_ROOT/"research"/_directory))
from test_witness_v66 import V66StrictPhysicalGateTests  # noqa: F401,E402
