from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_demo_matrix_runtime_installs_the_locked_runtime_environment() -> None:
    workflow = (ROOT / ".github/workflows/nexus_demo_strategy_matrix.yml").read_text(
        encoding="utf-8"
    )
    runtime_lock = (ROOT / "requirements.lock").read_text(encoding="utf-8")
    runtime_ranges = (ROOT / "requirements.txt").read_text(encoding="utf-8")

    assert "python -m pip install -r requirements.lock" in workflow
    assert "PyYAML==6.0.2" in runtime_lock
    assert "PyYAML>=6.0.2,<7" in runtime_ranges


def test_demo_matrix_proof_is_triggered_by_android_release_changes() -> None:
    workflow = (ROOT / ".github/workflows/nexus_demo_strategy_matrix.yml").read_text(
        encoding="utf-8"
    )
    required_paths = (
        "android/lbank-mobile/**",
        "scripts/build_release_evidence.py",
        "scripts/release_gate.py",
        "tests/test_mobile_delivery_surface.py",
        ".github/workflows/build_lbank_mobile_apk.yml",
    )

    for path in required_paths:
        assert workflow.count(f'- "{path}"') >= 2
