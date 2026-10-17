"""Enroll isolated V70 legacy Elliott economics no-promotion tests."""
import sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]/"research"
sys.path.insert(0,str(root/"elliott_v70_frozen_loss_gate"))
from test_loss_gate_v70 import V70LegacyLossGateTests  # noqa: F401,E402
