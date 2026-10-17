"""Discover source-bar anchored V71 simulated Elliott trade chronology QA."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]/"research"
sys.path.insert(0,str(ROOT/"elliott_v71_legacy_entry_exit_source"))
from test_legacy_entries_v71 import V71ExitBarTests  # noqa: F401,E402
