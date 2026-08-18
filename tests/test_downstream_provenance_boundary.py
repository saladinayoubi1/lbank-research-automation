from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUTHORITATIVE_MARKET_CONSUMERS = (
    "phase6_research_pipeline.py",
    "product_research_runtime.py",
)
RAW_BACKTEST_NAME = "run_target_exposure_backtest"


def _tree(path: str) -> ast.AST:
    return ast.parse((ROOT / path).read_text(encoding="utf-8"), filename=path)


def _imports_raw_backtest(path: str) -> bool:
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.ImportFrom) and node.module == "backtest_engine":
            if any(alias.name == RAW_BACKTEST_NAME for alias in node.names):
                return True
    return False


def test_authoritative_research_and_product_code_cannot_import_raw_backtest_engine():
    offenders = [path for path in AUTHORITATIVE_MARKET_CONSUMERS if _imports_raw_backtest(path)]
    assert offenders == [], f"raw backtest bypass is forbidden in authoritative consumers: {offenders}"


def test_only_canonical_boundary_calls_raw_target_exposure_backtest_for_authoritative_path():
    tree = _tree("canonical_backtest.py")
    imported_raw = False
    validates = False
    raw_calls = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "backtest_engine":
            imported_raw = imported_raw or any(alias.name == RAW_BACKTEST_NAME for alias in node.names)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            validates = validates or node.func.id == "validate_canonical_dataset"
            raw_calls += int(node.func.id == RAW_BACKTEST_NAME)
    assert imported_raw is True
    assert validates is True
    assert raw_calls == 1


def test_strategy_factory_revalidates_gate7_dataset_before_experiment_and_qualification():
    tree = _tree("phase5_strategy_factory.py")
    functions = {node.name: node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    for name in ("build_experiment", "qualify"):
        assert name in functions
        calls = [
            node.func.id
            for node in ast.walk(functions[name])
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        ]
        assert "validate_canonical_dataset" in calls


def test_automated_paper_revalidates_dataset_and_recomputes_qualification():
    tree = _tree("product_research_runtime.py")
    auto_paper = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "auto_paper")
    calls = [
        node.func.id
        for node in ast.walk(auto_paper)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]
    assert "validate_canonical_dataset" in calls
    assert "qualify" in calls


def test_generic_manual_paper_runtime_has_no_market_data_or_backtest_import_path():
    tree = _tree("product_runtime.py")
    forbidden_modules = {"backtest_engine", "bybit_public_klines", "research_data", "phase5_data_binding"}
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module in forbidden_modules
    }
    assert imported == set()
