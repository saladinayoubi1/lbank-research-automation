"""Discover V55 independent official-source intake tests in Elliott CI."""
import sys
from pathlib import Path
_ROOT=Path(__file__).resolve().parents[1]/"research"
for _d in ("elliott_v52_prospective","elliott_v55_source_intake"):
    sys.path.insert(0,str(_ROOT/_d))
from test_official_source_v55 import V55OfflineOfficialIntakeTests  # noqa: E402,F401
