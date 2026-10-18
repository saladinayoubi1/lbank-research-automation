from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from nexus_elliott_v119_entry_witness_qa import EntryWitnessError, entry_witnesses

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "product_ui/research-reports/elliott-v119-completed-study.json").read_bytes())["input_frozen_config"]


def physical_prefix(*, w0=10, w1=20, w2=30, retest=34, n=100):
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    rows = [{"timestamp": (start + timedelta(minutes=15 * i)).isoformat(),
             "open": 105, "high": 106, "low": 104, "close": 105} for i in range(n)]
    rows[w0]["low"] = 90
    rows[w1]["high"] = 120
    rows[w2]["low"] = 100
    rows[retest].update(open=104, high=106, low=102, close=104)
    rows[retest + 1].update(open=103, high=108, low=103, close=107)
    return rows, retest + 2


def check(rows, entry=36, **overrides):
    args = {"entry_index": entry, "partition_start": 0, "entry_mid": 105,
            "stop": 99.8, "target": 115.4, "config": CONFIG}
    return entry_witnesses(rows, **{**args, **overrides})


def test_real_strict_pivots_produce_one_pre_entry_chronology_without_mock_pivots():
    rows, entry = physical_prefix()
    found = check(rows, entry)
    assert len(found) == 1
    w = found[0]
    assert [w[k] for k in ("pivot_w0_center", "pivot_w1_center", "pivot_w2_center",
                          "w2_known_after_closed_index", "retest_completed_index",
                          "reclaim_completed_index", "entry_index")] == [10, 20, 30, 33, 34, 35, 36]
    assert w["prefix_last_index"] == entry - 1
    assert w["reclaim_available_utc"] == rows[entry]["timestamp"]
    assert w["w2_available_utc"] == rows[34]["timestamp"]
    assert len(w["reconstructed_witness_sha256"]) == 64


def test_the_checker_never_reads_entry_or_later_bar_prices():
    rows, entry = physical_prefix()
    class ClosedPrefixOnly(list):
        def __getitem__(self, index):
            assert type(index) is int and index < entry, "future or entry bar read"
            return super().__getitem__(index)
    expected = check(rows, entry)
    assert check(ClosedPrefixOnly(rows), entry) == expected
    for row in rows[entry:]:
        row.update(open=1000, high=2000, low=1, close=1500)
    assert check(rows, entry) == expected


@pytest.mark.parametrize("broken_index", [34, 35])
def test_support_breach_at_retest_or_reclaim_invalidates_the_recorded_entry(broken_index):
    rows, entry = physical_prefix()
    rows[broken_index]["low"] = 99.99
    assert check(rows, entry) == []


def test_an_earlier_valid_reclaim_cannot_be_reassigned_to_a_later_recorded_entry():
    rows, entry = physical_prefix()
    assert check(rows, entry)
    assert check(rows, entry + 2) == []


def test_adjacent_same_kind_high_events_are_not_pruned_to_create_a_witness():
    rows, entry = physical_prefix()
    rows[16]["high"] = 119
    assert check(rows, entry) == []


def test_consecutive_low_event_uses_the_immediately_preceding_low():
    rows, entry = physical_prefix()
    rows[16]["low"] = 92
    found = check(rows, entry)
    assert len(found) == 1 and found[0]["pivot_w0_center"] == 16


def test_dual_high_low_center_cannot_establish_wave1_order():
    rows, entry = physical_prefix()
    rows[20]["low"] = 89
    assert check(rows, entry) == []


def test_both_maximum_span_and_retest_horizon_boundaries_are_included():
    rows, entry = physical_prefix(w0=10, w1=74, w2=138, retest=189, n=220)
    found = check(rows, entry)
    assert len(found) == 1 and found[0]["pivot_w0_center"] == 10
    assert found[0]["prefix_first_index"] == 7
    rows, entry = physical_prefix(w0=10, w1=74, w2=138, retest=190, n=220)
    assert check(rows, entry) == []


@pytest.mark.parametrize("change", [{"stop": 99.81}, {"target": 115.41},
                                    {"entry_mid": 121}, {"entry_index": 34}, {"partition_start": 34}])
def test_wrong_brackets_right_confirmation_or_partition_cannot_pass(change):
    rows, entry = physical_prefix()
    assert check(rows, entry, **change) == []


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), "invalid"])
def test_invalid_pre_entry_source_is_rejected(bad):
    rows, entry = physical_prefix()
    rows[34]["close"] = bad
    with pytest.raises(EntryWitnessError):
        check(rows, entry)


def test_changed_past_prices_change_the_witness_digest():
    rows, entry = physical_prefix()
    original = check(rows, entry)[0]
    changed = deepcopy(rows)
    changed[15]["open"] = 104.5
    revised = check(changed, entry)[0]
    assert original["pivot_w0_center"] == revised["pivot_w0_center"]
    assert original["closed_prefix_sha256"] != revised["closed_prefix_sha256"]
    assert original["reconstructed_witness_sha256"] != revised["reconstructed_witness_sha256"]
