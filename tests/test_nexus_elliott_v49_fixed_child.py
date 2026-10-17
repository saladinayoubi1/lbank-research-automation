"""Include V49 bounded deterministic child-wave proposal guards in Elliott CI."""
import sys
from pathlib import Path
_RESEARCH=Path(__file__).resolve().parents[1]/"research"
sys.path.insert(0,str(_RESEARCH/"elliott_v40_nested_proof"))
sys.path.insert(0,str(_RESEARCH/"elliott_v49_fixed_child"))
from test_propose_nested_v49 import V49FixedWitnessTests  # noqa: E402,F401
