"""Discover read-only V65 nested corrective-wave geometric grammar tests."""
import sys
from pathlib import Path
_ROOT=Path(__file__).resolve().parents[1]/"research"
for _name in ("elliott_v40_nested_proof","elliott_v65_hierarchical_geometry"):
    sys.path.insert(0,str(_ROOT/_name))
from test_grammar_v65 import V65NestedCorrectionTests  # noqa: F401,E402
