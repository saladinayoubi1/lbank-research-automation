"""Reproduce Git's Windows-style checkout and run the unchanged failing test."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--attributes-before", type=Path, required=True)
    parser.add_argument("--attributes-after", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    args = parser.parse_args()
    source = args.source_root.resolve()
    evidence = args.evidence_dir.resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    fixture = evidence/("checkout-fixture-"+str(os.getpid()))
    assert not fixture.exists()
    fixture.mkdir()
    target = "tests/fixtures/macro_retest_v10_previous_engine.py"
    reference = (source/target).read_bytes()
    lf_hash = hashlib.sha256(reference).hexdigest()
    assert lf_hash == "15bece0ef68256a625532651d10e11f6c32444040f9c9d720ffcc5e29685afeb"
    expected_windows_hash = "d2a8509bf883a07cb835fe4582afe3f1129a4ebb5ce46af32b339912a91acd4c"
    assert hashlib.sha256(reference.replace(b"\n", b"\r\n")).hexdigest() == expected_windows_hash
    before = args.attributes_before.read_bytes()
    after = args.attributes_after.read_bytes()
    assert after.startswith(before)
    assert after[len(before):].decode().strip().splitlines() == [
        "# Preserve the frozen source fixture bytes under Windows checkout conversion.",
        target+" text eol=lf",
    ]
    commands = []

    def git(*arguments):
        result = subprocess.run(["git", "-c", "core.attributesFile="+os.devnull, *arguments],
                                cwd=fixture, capture_output=True, timeout=15)
        commands.append({"arguments": list(arguments), "exit_code": result.returncode,
                         "stdout": result.stdout.decode(errors="replace"),
                         "stderr": result.stderr.decode(errors="replace")})
        assert result.returncode == 0, result.stderr.decode(errors="replace")
        return result.stdout

    git("init", "-q")
    git("config", "core.autocrlf", "true")
    git("config", "core.eol", "crlf")
    controls = {
        "tests/fixtures/untargeted_reference.py": b"# control\nvalue = 1\n",
        "scripts/provision_nexus_bybit_wsl_runner.ps1": b"# existing LF rule\nWrite-Output 'control'\n",
    }
    for path, content in {target: reference, **controls}.items():
        p = fixture/path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
    (fixture/".gitattributes").write_bytes(before)
    git("add", "--", ".gitattributes", target, *controls)
    assert git("show", ":"+target) == reference

    # Stage just the fixed previous-engine contracts needed by the existing
    # comparison test. These are copied unchanged, never tracked or edited.
    (fixture/"research").mkdir()
    for p in (source/"research").glob("*.json"):
        shutil.copyfile(p, fixture/"research"/p.name)
    sys.path.insert(0, str(source))
    test_path = source/"tests/test_nexus_causal_macro_retest_features.py"
    spec = importlib.util.spec_from_file_location("fixture_checkout_existing_tests", test_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ROOT = fixture
    method = "test_feature_engine_preserves_all_old_columns_on_source_bound_fixture"

    def checkout():
        for path in (target, *controls):
            (fixture/path).unlink()
            git("checkout-index", "--force", "--", path)
        return {p: (fixture/p).read_bytes() for p in (target, *controls)}

    old_checkout = checkout()
    assert hashlib.sha256(old_checkout[target]).hexdigest() == expected_windows_hash
    baseline = unittest.TestResult()
    module.IntegrationTests(method).run(baseline)
    assert baseline.testsRun == 1 and len(baseline.failures) == 1 and not baseline.errors
    assert expected_windows_hash in baseline.failures[0][1]
    (fixture/".gitattributes").write_bytes(after)
    git("add", "--", ".gitattributes")
    new_checkout = checkout()
    assert new_checkout[target] == reference
    assert git("show", ":"+target) == reference
    for control in controls:
        assert new_checkout[control] == old_checkout[control]
    assert new_checkout[next(iter(controls))].count(b"\r\n") == 2
    assert b"\r\n" not in new_checkout["scripts/provision_nexus_bybit_wsl_runner.ps1"]
    fixed = unittest.TestResult()
    module.IntegrationTests(method).run(fixed)
    assert fixed.testsRun == 1 and not fixed.failures and not fixed.errors
    attrs = git("check-attr", "text", "eol", "--", target).decode()
    assert "text: set" in attrs and "eol: lf" in attrs
    manifest = json.loads((source/"docs/evidence/causal-macro-break-retest-v10-20261014/computational-source-binding.json").read_text())
    source_match = [{"path": f["path"], "match": hashlib.sha256((source/f["path"]).read_bytes()).hexdigest() == f["sha256"]}
                    for f in manifest["files"]]
    assert len(source_match) == 42 and all(x["match"] for x in source_match)
    result = {
        "schema": "nexus.macro-retest-v10-frozen-fixture-checkout.v1",
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_version": git("--version").decode().strip(), "python": sys.version.split()[0],
        "platform_boundary": "Local actual Git checkout with core.autocrlf=true/core.eol=crlf; not native Windows or full hosted CI.",
        "target": target, "expected_frozen_lf_sha256": lf_hash,
        "observed_hosted_windows_sha256": expected_windows_hash,
        "baseline_checkout_sha256": hashlib.sha256(old_checkout[target]).hexdigest(),
        "fixed_checkout_sha256": hashlib.sha256(new_checkout[target]).hexdigest(),
        "existing_test_method": method,
        "baseline_existing_test": {"run": 1, "expected_failures": 1, "errors": 0},
        "fixed_existing_test": {"run": 1, "failures": 0, "errors": 0},
        "reference_git_blob_bytes_unchanged": True, "unrelated_control_checkout_unchanged": True,
        "existing_lf_rule_checkout_unchanged": True, "fixed_attributes": attrs.strip(),
        "computational_closure_digest": manifest["closure_digest"], "source_file_sha256_checks": source_match,
        "fixture_hash_assertion_unchanged": True, "network_requests": 0, "v10_market_runs": 0,
        "full_hosted_gate_complete": False, "native_source_gate_complete": False,
        "research_only": True, "live_enabled": False,
    }
    result["receipt_digest"] = hashlib.sha256(json.dumps(result, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    (evidence/"checkout-verification.json").write_text(json.dumps(result, indent=2)+"\n")
    (evidence/"git-commands.json").write_text(json.dumps(commands, indent=2)+"\n")
    print(json.dumps({k: v for k, v in result.items() if k != "source_file_sha256_checks"}, indent=2))


if __name__ == "__main__":
    main()
