"""Research-only V40 bounded nested Elliott subwave and ABC tests.

Makes the isolated synthetic source-bound validation tests part of the normal
Elliott regression suite. It must not register a strategy or order producer.
"""
import sys
from pathlib import Path

RESEARCH_DIR = Path(__file__).resolve().parents[1] / "research" / "elliott_v40_nested_proof"
sys.path.insert(0, str(RESEARCH_DIR))

from test_nested_elliott_v40 import V40NestedResearchTests  # noqa: E402,F401
