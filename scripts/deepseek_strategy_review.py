"""Bounded DeepSeek advisory review for Phase 3 strategy validation.

This is research/backtest/paper-only. DeepSeek is advisory and has no merge,
risk, billing, production, or live-trading authority.
"""
from __future__ import annotations

import json
from pathlib import Path

from deepseek_provider import chat

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "research" / "evidence" / "ema_crossover_evidence_matrix.md"
OUTPUT = ROOT / "build" / "deepseek" / "strategy-review.json"

REQUIRED_KEYS = {
    "findings",
    "edge_case_tests",
    "execution_realism",
    "oos_robustness",
    "kill_conditions",
    "uncertainties",
}


def _parse_json(text: str) -> dict:
    value = text.strip()
    if value.startswith("```"):
        lines = value.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        value = "\n".join(lines)
    data = json.loads(value)
    if not isinstance(data, dict):
        raise ValueError("DeepSeek review must be a JSON object")
    missing = sorted(REQUIRED_KEYS - data.keys())
    if missing:
        raise ValueError(f"DeepSeek review missing keys: {', '.join(missing)}")
    for key in REQUIRED_KEYS:
        if not isinstance(data[key], list):
            raise ValueError(f"DeepSeek review field {key} must be a list")
    return data


def main() -> None:
    evidence = TARGET.read_text(encoding="utf-8")
    prompt = f"""
You are an independent quantitative-research reviewer for NEXUS. Review the evidence below only for research/backtest/paper work. Do not recommend live trading or production actions.

Focus on: deterministic EMA strategy rules; look-ahead/leakage; transaction fees, slippage, funding and latency assumptions; execution edge cases; OOS/walk-forward design; parameter perturbation and multiple-testing risk; benchmarks/statistical uncertainty; failure modes and kill criteria.

Return ONLY valid JSON with exactly these top-level list fields:
findings, edge_case_tests, execution_realism, oos_robustness, kill_conditions, uncertainties.
Each list item must be a short object containing at least recommendation and rationale; findings should also include severity (low|medium|high). State uncertainty rather than guessing.

Repository evidence target:\n{evidence[:18000]}
""".strip()

    result = chat(
        [{"role": "user", "content": prompt}],
        complexity="complex",
        max_tokens=1800,
        ledger_path="build/deepseek/usage.json",
        timeout=120,
    )
    review = _parse_json(result["content"])
    safe = {
        "schema_version": 1,
        "target": str(TARGET.relative_to(ROOT)).replace("\\", "/"),
        "model": result["model"],
        "thinking": result["thinking"],
        "cost_usd": round(result["cost_usd"], 8),
        "month_spent_usd": result["month_spent_usd"],
        "month_remaining_usd": result["month_remaining_usd"],
        "review": review,
        "authority": "advisory-research-backtest-paper-only",
        "independent_verification_required": True,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(safe, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "ok": True,
        "model": safe["model"],
        "cost_usd": safe["cost_usd"],
        "month_spent_usd": safe["month_spent_usd"],
        "month_remaining_usd": safe["month_remaining_usd"],
        "finding_count": len(review["findings"]),
        "edge_case_test_count": len(review["edge_case_tests"]),
    }, sort_keys=True))


if __name__ == "__main__":
    main()
