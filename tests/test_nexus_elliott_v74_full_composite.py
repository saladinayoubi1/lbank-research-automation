"""Register V74 all-feature legacy Elliott future-suffix regressions."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]/"research"
sys.path.insert(0,str(ROOT/"elliott_v74_full_composite_prefix"))
from test_composite_prefix_v74 import V74CompleteCompositePrefixTests  # noqa: F401,E402
