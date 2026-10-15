"""Bounded synthetic research qualification; no archive or market producer."""
from datetime import datetime, timezone
from pathlib import Path
import argparse
import ast
import hashlib
import json
import os
import platform
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "source"
parser = argparse.ArgumentParser()
parser.add_argument("--native", action="store_true")
args = parser.parse_args()
start = time.monotonic()
expected = json.loads((ROOT / "source-hashes.json").read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


if args.native:
    require(platform.system() == "Windows" and os.environ.get("COMPUTERNAME") == "DESKTOP-F4SA4VL"
            and sys.version_info[:2] == (3, 12) and not sys.flags.optimize, "Wrong native research lane")
for relative, digest in expected["source_file_sha256"].items():
    require(sha(SOURCE / relative) == digest, "Source differs before tests: " + relative)
sys.path.insert(0, str(SOURCE))
sys.path.insert(0, str(SOURCE / "tests"))
import numpy
import pandas
import nexus_composite_strategy_research as engine
pyarrow_version = None
if args.native:
    import pyarrow
    pyarrow_version = pyarrow.__version__
    require((numpy.__version__, pandas.__version__, pyarrow.__version__) == ("2.3.5", "2.3.3", "23.0.1"),
            "Pinned native dependencies differ")
suite = unittest.TestSuite()
loader = unittest.TestLoader()
for pattern in ("test_nexus_causal_*features.py", "test_nexus_elliott_*.py"):
    suite.addTests(loader.discover(str(SOURCE / "tests"), pattern=pattern))
result = unittest.TextTestRunner(verbosity=2).run(suite)
require(result.wasSuccessful() and result.testsRun == 163, "Research test result/count differs")
# Reuse the previous source gate's pure frontier schema test unchanged. The
# full control-plane pytest module is exercised by hosted CI, not this child.
path = SOURCE / "tests/test_nexus_composite_fast_frontier.py"
node = next(n for n in ast.parse(path.read_text(encoding="utf-8")).body
            if isinstance(n, ast.FunctionDef)
            and n.name == "test_all_frontier_mechanisms_emit_bounded_boolean_signals")
namespace = {"np": numpy, "pd": pandas, "research": engine}
exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), namespace)
namespace[node.name]()
for relative, digest in expected["source_file_sha256"].items():
    require(sha(SOURCE / relative) == digest, "Source changed during tests: " + relative)
inventory = {"factory_specs": engine.FACTORY_SPECS, "all_mechanisms": list(engine.ALL_MECHANISMS),
             "frontier_configs": list(engine.FRONTIER_CONFIGS)}
receipt = {
    "schema": "nexus.elliott-five-swing-adapter-source-test.v1",
    "completed_at_utc": datetime.now(timezone.utc).isoformat(),
    "native_windows": args.native,
    "python": platform.python_version(), "numpy": numpy.__version__,
    "pandas": pandas.__version__, "pyarrow": pyarrow_version,
    "tests_run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
    "previous_research_methods": 148, "new_adapter_observation_methods": 15,
    "source_schema_regression_functions": 1,
    "source_schema_frontier_mechanisms": len(engine.FRONTIER_MECHANISMS),
    "full_control_plane_pytest_module_executed": False,
    "registered_inventory": [len(engine.FACTORY_SPECS), len(engine.ALL_MECHANISMS), len(engine.FRONTIER_CONFIGS)],
    "prior_full_inventory_semantic_digest": engine.digest(inventory),
    "source_file_sha256": expected["source_file_sha256"], "source_unchanged": True,
    "worker_sha256": sha(Path(__file__)), "duration_seconds": time.monotonic() - start,
    "market_replays": 0, "archive_opened": False, "research_only": True, "live_enabled": False,
}
(ROOT / "test-worker-receipt.json").write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"tests_run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
                  "schema_test_functions": 1, "frontier_mechanisms": len(engine.FRONTIER_MECHANISMS),
                  "source_unchanged": True, "market_replays": 0}), flush=True)
