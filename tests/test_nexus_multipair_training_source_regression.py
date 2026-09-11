from __future__ import annotations

import inspect

import nexus_multipair_strategy_discovery as discovery


def test_training_robustness_keeps_public_selection_source_contract() -> None:
    """Robustness may change training rank, never the downstream source label."""
    source = inspect.getsource(discovery.discover)
    assert '"selection_source": "training_only"' in source
    assert '"selection_source": "training_temporal_robustness"' not in source


def test_training_rank_does_not_depend_on_selection_source_label() -> None:
    stable = {
        "variant_id": "stable",
        "selection_source": "training_only",
        "summary": {"score": 3.0},
        "training_robustness": {
            "all_windows_pass_training_gate": True,
            "minimum_passed_gate_count": 7,
            "minimum_score": 0.4,
            "minimum_positive_ratio": 0.75,
            "minimum_median_return": 0.01,
        },
    }
    fragile = {
        "variant_id": "fragile",
        "selection_source": "training_only",
        "summary": {"score": 9.0},
        "training_robustness": {
            "all_windows_pass_training_gate": False,
            "minimum_passed_gate_count": 6,
            "minimum_score": -0.5,
            "minimum_positive_ratio": 0.5,
            "minimum_median_return": -0.01,
        },
    }

    ranked = sorted([fragile, stable], key=discovery._training_rank_key)
    assert ranked[0]["variant_id"] == "stable"
    assert all(row["selection_source"] == "training_only" for row in ranked)
