"""Bounded offline verification of one CI development dependency pin.

The pipx metadata fixture models the exact observed hosted requirement; it is
not an installation of pipx. The replacement packaging code/metadata are copied
from an already installed real 26.3 distribution into an exclusive scratch venv.
No network, global installation, or owner profile changes are performed.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import types
import venv


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture-root", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    args = parser.parse_args()
    root, source, evidence = (p.resolve() for p in (args.fixture_root, args.source_root, args.evidence_dir))
    evidence.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc).isoformat()
    distribution = metadata.distribution("packaging")
    assert distribution.version == "26.3", "Verification requires the real pinned packaging 26.3"

    module_path = root/"tests/test_dependency_lock.py"
    module = types.ModuleType("existing_dependency_lock_tests")
    module.__file__ = str(module_path)
    exec(compile(module_path.read_bytes(), str(module_path), "exec"), module.__dict__)
    existing = sorted((n for n in vars(module) if n.startswith("test_")), reverse=True)
    for name in existing:
        getattr(module, name)()
    assert len(existing) == 4
    assert "packaging==26.3" in (root/"requirements-dev.lock").read_text().splitlines()

    binding_path = source/"docs/evidence/causal-macro-break-retest-v10-20261014/computational-source-binding.json"
    binding = json.loads(binding_path.read_text())
    matches = [{"path": f["path"], "match": hashlib.sha256((source/f["path"]).read_bytes()).hexdigest() == f["sha256"]}
               for f in binding["files"]]
    assert len(matches) == 42 and all(f["match"] for f in matches)

    env_dir = evidence/("pip-check-fixture-"+str(os.getpid()))
    assert not env_dir.exists(), "Verification fixture must be exclusive"
    venv.EnvBuilder(with_pip=True).create(env_dir)
    python = env_dir/("Scripts/python.exe" if os.name == "nt" else "bin/python")
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    env.update(PYTHONNOUSERSITE="1", PIP_DISABLE_PIP_VERSION_CHECK="1")

    def run(label, command):
        result = subprocess.run([str(python), *command], env=env, capture_output=True, text=True, timeout=15)
        (evidence/(label+".stdout.log")).write_text(result.stdout)
        (evidence/(label+".stderr.log")).write_text(result.stderr)
        return result

    library = Path(run("fixture-site", ["-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"]).stdout.strip())
    assert library.is_relative_to(env_dir)
    stub = library/"pipx-1.17.12.dist-info"
    stub.mkdir()
    (stub/"METADATA").write_text("Metadata-Version: 2.1\nName: pipx\nVersion: 1.17.12\nRequires-Dist: packaging>=26.3\n")
    old = library/"packaging-26.2.dist-info"
    old.mkdir()
    (old/"METADATA").write_text("Metadata-Version: 2.1\nName: packaging\nVersion: 26.2\n")
    before = run("pip-check-before", ["-m", "pip", "check"])
    assert before.returncode == 1 and "packaging>=26.3" in before.stdout and "26.2" in before.stdout
    shutil.rmtree(old)
    actual_metadata = next(distribution.locate_file(f).parent for f in distribution.files
                           if str(f).endswith(".dist-info/METADATA"))
    shutil.copytree(distribution.locate_file("packaging"), library/"packaging", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(actual_metadata, library/actual_metadata.name)
    after = run("pip-check-after", ["-m", "pip", "check"])
    assert after.returncode == 0 and "No broken requirements found" in after.stdout
    imported = run("real-packaging-version", ["-c", "import packaging,importlib.metadata as m; print(packaging.__version__,m.version('packaging'))"])
    assert imported.returncode == 0 and imported.stdout.strip() == "26.3 26.3"
    result = {
        "schema": "nexus.macro-retest-v10-ci-dev-pin-verification.v1",
        "started_at_utc": started, "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "python": sys.version.split()[0], "packaging_code_and_metadata_version": distribution.version,
        "four_existing_test_functions": existing, "test_function_count": len(existing),
        "full_pytest_executed": False,
        "pip_check_before": {"exit_code": before.returncode, "stdout": before.stdout.strip()},
        "pip_check_after": {"exit_code": after.returncode, "stdout": after.stdout.strip()},
        "fixture_boundary": "Synthetic pipx requirement/old 26.2 metadata; real already installed packaging 26.3 module and metadata. This is an offline compatibility reproduction, not full locked dependency installation or hosted Windows proof.",
        "unchanged_computational_files": matches, "computational_closure_digest": binding["closure_digest"],
        "network_requests": 0, "market_runs": 0, "owner_state_changes": 0,
        "hosted_gate_complete": False, "native_source_gate_complete": False,
        "research_only": True, "live_enabled": False,
    }
    result["receipt_digest"] = hashlib.sha256(json.dumps(result, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    (evidence/"ci-dev-pin-verification.json").write_text(json.dumps(result, indent=2)+"\n")
    print(json.dumps({k: v for k, v in result.items() if k != "unchanged_computational_files"}, indent=2))


if __name__ == "__main__":
    main()
