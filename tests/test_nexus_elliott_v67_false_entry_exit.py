"""Native test discovery for V67 retrospective entry/exit reporting veto."""
import sys
from pathlib import Path
_ROOT=Path(__file__).resolve().parents[1]/"research"
sys.path.insert(0,str(_ROOT/"elliott_v67_false_entry_exit_veto"))
from test_veto_v67 import V67FalseEntryExitVetoTests  # noqa: F401,E402
