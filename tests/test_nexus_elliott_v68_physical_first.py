"""Enroll V68 physical-first retrospective Elliott claim regressions."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]/"research"
for name in (
    "elliott_v40_nested_proof",
    "elliott_v49_fixed_child",
    "elliott_v65_hierarchical_geometry",
    "elliott_v66_source_bound_hierarchy",
    "elliott_v67_false_entry_exit_veto",
    "elliott_v68_physical_first_veto",
):
    sys.path.insert(0,str(ROOT/name))
from test_physical_veto_v68 import V68PhysicalFirstVetoTests
