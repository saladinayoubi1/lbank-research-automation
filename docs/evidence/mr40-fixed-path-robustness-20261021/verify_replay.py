"""Verify archived bytes and repeat all 27 frozen-path accounting cases offline."""
from __future__ import annotations
import contextlib
import hashlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RESULT = "a2458859f9462208a6127d738e4a104de6dc066342436692394bc9048d12591b"
SOURCE = "205e99a38a7d50e564b22202166e5cbdbac4590f"
PROTOCOL = "0f58362edf77b9484466a4a49d2b6a754c777b9e"
TABLES = ("summary.csv", "cost_boundaries.csv", "fills.csv", "closed_positions.csv",
          "equity_curve.csv", "monthly_attribution.csv")


def main():
    inventory = json.loads((ROOT / "INVENTORY.json").read_text(encoding="utf-8"))
    for item in inventory["files"]:
        raw = (ROOT / item["path"]).read_bytes()
        if len(raw) != item["bytes"] or hashlib.sha256(raw).hexdigest() != item["sha256"]:
            raise AssertionError("archive file mismatch: " + item["path"])
    test = subprocess.run([sys.executable, str(ROOT / "tests" / "test_nexus_mr40_fixed_path_robustness_v1.py"), "-v"],
                          cwd=ROOT, capture_output=True, text=True)
    print(test.stdout, end="")
    print(test.stderr, end="")
    if test.returncode:
        raise RuntimeError("robustness unit tests failed")
    sys.path.insert(0, str(ROOT / "research"))
    import nexus_mr40_fixed_path_robustness_v1 as audit
    recorded = json.loads((ROOT / "recorded_results" / "results.json").read_text(encoding="utf-8"))
    audit.check_digest(recorded, "result_digest", RESULT)
    with tempfile.TemporaryDirectory(prefix="mr40-robustness-replay-") as directory:
        work = Path(directory)
        shutil.copytree(ROOT / "inputs", work / "inputs")
        shutil.copytree(ROOT / "tests", work / "tests", ignore=shutil.ignore_patterns("__pycache__"))
        for name in ("study_contract.json", "input_manifest.json"):
            shutil.copyfile(ROOT / name, work / name)
        with contextlib.redirect_stdout(io.StringIO()):
            actual = audit.run(work, SOURCE, PROTOCOL)
        ignore = {"created_utc", "worker", "result_digest"}
        if {k: v for k, v in actual.items() if k not in ignore} != {k: v for k, v in recorded.items() if k not in ignore}:
            raise AssertionError("semantic replay mismatch")
        for name in TABLES:
            if (work / "results" / name).read_bytes() != (ROOT / "recorded_results" / name).read_bytes():
                raise AssertionError("CSV bytes differ: " + name)
    print(json.dumps({"recorded_result_digest": RESULT, "inventory_members": len(inventory["files"]),
                      "unit_tests": 7, "account_paths": len(actual["checks"]),
                      "exact_baseline_curves": sum(c["baseline_curve_exact"] is True for c in actual["checks"]),
                      "independent_decimal_equity_paths": len(actual["checks"]),
                      "independent_product_checks": len(actual["checks"]),
                      "zero_pnl_root_checks": sum(c["break_even_pnl_error_usdt"] is not None for c in actual["checks"]),
                      "semantic_replay": "PASS", "exact_csv_files": list(TABLES), "orders": 0}, sort_keys=True))


if __name__ == "__main__":
    main()
