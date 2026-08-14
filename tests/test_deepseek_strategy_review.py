import json
from pathlib import Path

import scripts.deepseek_strategy_review as review
from deepseek_provider import DeepSeekError


def _setup_paths(tmp_path: Path, monkeypatch):
    root = tmp_path
    target = root / "research" / "evidence" / "ema_crossover_evidence_matrix.md"
    output = root / "build" / "deepseek" / "strategy-review.json"
    target.parent.mkdir(parents=True)
    target.write_text("# deterministic EMA evidence\n", encoding="utf-8")
    monkeypatch.setattr(review, "ROOT", root)
    monkeypatch.setattr(review, "TARGET", target)
    monkeypatch.setattr(review, "OUTPUT", output)
    return output


def test_provider_unavailable_is_recorded_nonblocking(tmp_path, monkeypatch):
    output = _setup_paths(tmp_path, monkeypatch)

    def unavailable(*_args, **_kwargs):
        raise DeepSeekError("provider unavailable")

    monkeypatch.setattr(review, "chat", unavailable)
    result = review.run_review()

    assert result["ok"] is False
    assert result["unavailable"] is True
    assert result["blocking"] is False
    assert result["reason"] == "DeepSeekError"
    persisted = json.loads(output.read_text(encoding="utf-8"))
    assert persisted == result


def test_malformed_provider_output_is_recorded_nonblocking(tmp_path, monkeypatch):
    output = _setup_paths(tmp_path, monkeypatch)

    def malformed(*_args, **_kwargs):
        return {
            "content": "not-json",
            "model": "deepseek-v4-flash",
            "thinking": False,
            "cost_usd": 0.0,
            "month_spent_usd": 0.0,
            "month_remaining_usd": 5.0,
        }

    monkeypatch.setattr(review, "chat", malformed)
    result = review.run_review()

    assert result["ok"] is False
    assert result["unavailable"] is True
    assert result["blocking"] is False
    assert result["reason"] == "invalid_advisory_output"
    assert json.loads(output.read_text(encoding="utf-8")) == result
