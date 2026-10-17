"""Enroll physical-source H1/H4 as-of no-future regressions."""
import sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]/"research"
sys.path.insert(0,str(root/"elliott_v73_parent_source_asof"))
from test_parent_asof_v73 import V73ParentAsOfTests  # noqa: F401,E402
