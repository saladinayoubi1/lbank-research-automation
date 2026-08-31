from pathlib import Path


WORKFLOW = Path(".github/workflows/nexus_persistent_paper_trading_loop.yml")


def _paper_job(text: str) -> str:
    return text.split("  paper-loop:", 1)[1].split("  persist-state:", 1)[0]


def test_physical_python_binds_its_own_runtime_library_before_paper_imports() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    paper = _paper_job(text)
    prepare = paper.split(
        "Prepare exact repository and pre-provisioned Python 3.12 without JavaScript actions",
        1,
    )[1].split("Enforce eligible Bybit network execution plane", 1)[0]

    assert "python_prefix=" in prepare
    assert "sys.prefix" in prepare
    assert 'python_lib="$python_prefix/lib"' in prepare
    assert "Pre-provisioned CPython library directory is missing." in prepare
    assert 'effective_ld_library_path="$python_lib"' in prepare
    assert 'LD_LIBRARY_PATH="$effective_ld_library_path" "$python_bin" -c "import ctypes;' in prepare
    assert "physical_python_dynamic_stdlib=PASS" in prepare
    assert "printf 'LD_LIBRARY_PATH=%s\\n'" in prepare
    assert "physical_python_prefix=$python_prefix" in prepare


def test_physical_python_abi_binding_does_not_change_trading_authority() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    paper = _paper_job(text)

    assert 'assert snapshot["paper_only"] is True' in paper
    assert 'assert snapshot["live_trading_authority"] is False' in paper
    assert 'assert snapshot["private_credentials_used"] is False' in paper
    assert 'assert snapshot["automatic_strategy_promotion"] is False' in paper
    assert 'assert snapshot["deterministic_risk_final_authority"] is True' in paper
