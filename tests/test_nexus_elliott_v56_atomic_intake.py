"""Discover independent-audit-first atomic source publication regressions."""
import sys
from pathlib import Path
_ROOT=Path(__file__).resolve().parents[1]/"research"
for _d in ("elliott_v52_prospective","elliott_v55_source_intake",
           "elliott_v56_atomic_source"):
    sys.path.insert(0,str(_ROOT/_d))
from test_atomic_v56 import V56AtomicIntakeTests  # noqa: E402,F401
