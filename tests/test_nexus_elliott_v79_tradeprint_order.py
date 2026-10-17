"""Discover V79 bounded raw public Spot print-order audit regressions."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]/"research"
sys.path.insert(0,str(ROOT/"elliott_v79_historical_spot_tradeprint_order"))
from test_raw_tick_order_v79 import V79PublicTradePrintOrderTests  # noqa: E402,F401
