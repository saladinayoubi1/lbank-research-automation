"""Verify exact source/data bytes and reproduce the uninterrupted MR40 accounts."""
from __future__ import annotations
import contextlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = "3d454b5aee5b4fadd424408be91eb3d87e77311f"
PROTOCOL = "b71e99fc4c4a5a8e98aea37ab15d5719c3729b62"
RESULT = "dee122e30911d815f426cef84bb9fa6f5a870291b94240a8265733e57c151bba"


def main():
    sys.path.insert(0, str(ROOT / "research"))
    import nexus_mr40_continuous_account_v1 as study
    inventory = json.loads((ROOT / "INVENTORY.json").read_text(encoding="utf-8"))
    for item in inventory["files"]:
        if study.file_info(ROOT / item["path"]) != {k: v for k, v in item.items() if k != "path"}:
            raise AssertionError("inventory mismatch: " + item["path"])
    test = subprocess.run([sys.executable, str(ROOT / "tests/test_nexus_mr40_continuous_account_v1.py"), "-v"],
                          cwd=ROOT, capture_output=True, text=True)
    print(test.stdout, end="");print(test.stderr, end="")
    if test.returncode:
        raise RuntimeError("continuous-account regression failure")
    recorded = json.loads((ROOT / "recorded_results/results.json").read_text(encoding="utf-8"))
    study.check_digest(recorded, "result_digest", RESULT)
    with tempfile.TemporaryDirectory(prefix="mr40-continuous-replay-") as directory:
        work = Path(directory)
        for name in ("frozen", "tests"):
            shutil.copytree(ROOT / name, work / name, ignore=shutil.ignore_patterns("__pycache__"))
        for name in ("study_contract.json", "input_manifest.json"):
            shutil.copyfile(ROOT / name, work / name)
        with contextlib.redirect_stdout(io.StringIO()):
            actual = study.run(work, SOURCE, PROTOCOL)
        if actual != recorded:
            raise AssertionError("deterministic semantic replay differs")
        names = ["results.json", *recorded["output_files"]]
        for name in names:
            if (work / "results" / name).read_bytes() != (ROOT / "recorded_results" / name).read_bytes():
                raise AssertionError("byte replay differs: " + name)
    print(json.dumps({"result_digest": RESULT, "inventory_files": len(inventory["files"]), "unit_tests": 7,
                      "account_paths": len(actual["results"]), "decimal_equity_paths": len(actual["checks"]),
                      "exact_prefix_curves_and_natural_fills": len(actual["checks"]),
                      "independent_raw_signal_bars": actual["independent_raw_signal_bars"],
                      "exact_files": names, "replay": "PASS", "orders": 0}, sort_keys=True))


if __name__ == "__main__":
    main()
