"""Native discoverability: frozen Elliott source-trace economics audit regressions."""
import sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]/"research"
sys.path.insert(0,str(root/"elliott_v76_frozen_economic_funnel"))
from test_funnel_v76 import V76LegacyLossFunnelTests  # noqa: E402,F401
