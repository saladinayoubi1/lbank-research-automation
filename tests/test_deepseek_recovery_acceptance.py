from pathlib import Path

import pytest

import deepseek_provider as ds


def _path(tmp_path: Path) -> Path:
    return tmp_path / "usage.json"


def test_corrupt_persisted_ledger_fails_closed(tmp_path):
    path = _path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not-json", encoding="utf-8")

    with pytest.raises(ds.DeepSeekError, match="unreadable"):
        ds.load_ledger(path)


def test_tampered_reservation_total_fails_closed(tmp_path):
    path = _path(tmp_path)
    ledger = ds._fresh_ledger()
    ledger["inflight"] = {
        "req": {
            "reserved_usd": 0.25,
            "model": ds.DEFAULT_MODEL,
            "pricing_version": ds.PRICING_VERSION,
            "created_at": "2026-08-15T00:00:00+00:00",
            "status": "reserved",
        }
    }
    ledger["reserved_usd"] = 0.10

    with pytest.raises(ds.DeepSeekError, match="reservation total is inconsistent"):
        ds.save_ledger(path, ledger)


def test_reconciliation_without_reservation_fails_closed(tmp_path):
    path = _path(tmp_path)
    ds.save_ledger(path, ds._fresh_ledger())

    with pytest.raises(ds.DeepSeekError, match="reservation missing during reconciliation"):
        ds._reconcile(
            path,
            "missing-request",
            ds.DEFAULT_MODEL,
            {
                "prompt_tokens": 1,
                "prompt_cache_hit_tokens": 0,
                "prompt_cache_miss_tokens": 1,
                "completion_tokens": 1,
            },
        )


def test_provider_usage_above_reservation_is_quarantined(tmp_path):
    path = _path(tmp_path)
    request_id, reserved = ds._reserve(
        path,
        ds.DEFAULT_MODEL,
        [{"role": "user", "content": "bounded"}],
        1,
        False,
    )

    with pytest.raises(ds.AmbiguousCharge, match="exceeded conservative reservation"):
        ds._reconcile(
            path,
            request_id,
            ds.DEFAULT_MODEL,
            {
                "prompt_tokens": 1,
                "prompt_cache_hit_tokens": 0,
                "prompt_cache_miss_tokens": 1,
                "completion_tokens": 1_000_000,
            },
        )

    recovered = ds.load_ledger(path)
    assert request_id in recovered["inflight"]
    assert recovered["inflight"][request_id]["status"] == "quarantined_actual_exceeds_reservation"
    assert recovered["reserved_usd"] == pytest.approx(reserved, abs=1e-7)
    assert recovered["spent_usd"] == 0


def test_restart_recovery_preserves_unresolved_reservation(tmp_path):
    path = _path(tmp_path)
    request_id, reserved = ds._reserve(
        path,
        ds.PRO_MODEL,
        [{"role": "user", "content": "critical recovery"}],
        64,
        True,
    )

    first = ds.load_ledger(path)
    recovered = ds.load_ledger(path)

    assert request_id in recovered["inflight"]
    assert recovered["reserved_usd"] == pytest.approx(reserved, abs=1e-7)
    assert recovered["spent_usd"] + recovered["reserved_usd"] <= ds.MONTHLY_BUDGET_USD
    assert ds.remaining_budget(recovered) == pytest.approx(ds.remaining_budget(first), abs=1e-7)
