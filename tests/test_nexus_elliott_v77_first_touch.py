"""Discover V77 frozen Bybit archived 15m exit-first-touch regression suite."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]/"research"
for name in ("elliott_v71_legacy_entry_exit_source",
             "elliott_v77_legacy_exit_first_touch"):
    sys.path.insert(0,str(ROOT/name))
from test_first_touch_v77 import V77FirstTouchedExitTests  # noqa: E402,F401
