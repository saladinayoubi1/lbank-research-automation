"""Run the actual failed pure frontier test functions and causal suites."""
from __future__ import annotations

import ast
import hashlib
import io
import json
from pathlib import Path
import platform
import sys
import time
import unittest
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd
import nexus_composite_strategy_research as research
from nexus_mechanism_factory import (
    generate_factory_contracts, generate_factory_contracts_v3, load_factory_contract,
)

SELECTED = {
    "tests/test_nexus_composite_fast_frontier.py": {
        "helper": "_legacy_complete_ledger",
        "tests": (
            "test_frontier_tournament_preempts_legacy_risk_variant_cycle",
            "test_all_frontier_mechanisms_emit_bounded_boolean_signals",
            "test_generation1_exhaustion_opens_only_generation2_frontier",
        ),
    },
    "tests/test_nexus_mechanism_generator_v2.py": {
        "helper": "_ledger_after_fixed_frontier",
        "tests": ("test_generator_v3_preserves_v2_history_then_advances_three_new_batches",),
    },
}


def selected_cases():
    if sys.flags.optimize:
        raise RuntimeError("pytest-style assertions must remain enabled")
    cases = []
    for path, selection in SELECTED.items():
        tree = ast.parse((ROOT/path).read_text(), filename=path)
        names = {selection["helper"], *selection["tests"]}
        nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
        if {node.name for node in nodes} != names or any(node.decorator_list for node in nodes):
            raise RuntimeError("selected regression function shape changed")
        space = {"research":research, "np":np, "pd":pd, "Path":Path,
                 "generate_factory_contracts":generate_factory_contracts,
                 "generate_factory_contracts_v3":generate_factory_contracts_v3,
                 "load_factory_contract":load_factory_contract}
        # Execute the original test function bodies; unrelated mission imports
        # are not needed by these four pure regressions. This is not full pytest.
        exec(compile(ast.Module(body=nodes, type_ignores=[]), path, "exec"), space)
        cases.extend(unittest.FunctionTestCase(space[name]) for name in selection["tests"])
    return cases


def main():
    start = time.monotonic()
    suite = unittest.TestSuite(selected_cases())
    suite.addTests(unittest.TestLoader().discover(
        str(ROOT/"tests"), pattern="test_nexus_causal_*features.py"))
    output = io.StringIO()
    result = unittest.TextTestRunner(stream=output, verbosity=2).run(suite)
    out = Path(__file__).resolve().parent
    (out/"targeted-regression.log").write_text(output.getvalue(),encoding="utf-8")
    paths = [*SELECTED, "nexus_composite_strategy_research.py",
        "tests/test_nexus_causal_slot_volume_features.py",
        "tests/test_nexus_causal_jump_features.py"]
    receipt = {"schema":"nexus.utc-slot-routing-targeted-regression.v1",
        "checked_at_utc":datetime.now(timezone.utc).isoformat(),
        "source_parent_sha":"a4a296182768e17ca45a0f7d3be9a137a7a96f29",
        "exit_code":0 if result.wasSuccessful() else 1, "test_count":result.testsRun,
        "selected_original_ci_test_functions":4,
        "causal_suite_tests":result.testsRun-4,
        "earlier_frontier_precedence_subcases":len(research.FRONTIER_MECHANISMS)-1,
        "elapsed_seconds":round(time.monotonic()-start,6),
        "file_sha256":{path:hashlib.sha256((ROOT/path).read_bytes()).hexdigest() for path in paths},
        "runtime":{"python":platform.python_version(),"numpy":np.__version__,"pandas":pd.__version__},
        "full_pytest_suite_executed":False, "native_windows":False,
        "native_market_research_executed":False, "independent_strategy_qa":False,
        "research_only":True,"live_enabled":False}
    (out/"targeted-regression-receipt.json").write_text(
        json.dumps(receipt,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(output.getvalue(),end="")
    print(json.dumps(receipt,sort_keys=True))
    return receipt["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
