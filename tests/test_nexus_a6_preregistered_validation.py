import copy
import gzip
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts import nexus_a6_preregistered_validation as qa

ROOT = Path(__file__).resolve().parents[1]


def test_original_preregistration_and_live_commitments_are_pinned():
    plan = qa.pinned_json(ROOT / "config/a6-future-holdout-20261010.json", "plan_sha256", qa.PLAN_SHA)
    live = qa.pinned_json(ROOT / "config/a6-live-side-commitments-20261009.json", "commitments_sha256", qa.LIVE_SHA)
    assert plan["thresholds"] == {"btc_usdt": 0.10945652649859855, "eth_usdt": 0.16623354242827754}
    assert sum(map(len, live["trade_commitments"].values())) == 1175
    assert live["capture_receipt"]["archive_same_trade_crosscheck_complete"] is False


def test_resigning_an_adapted_threshold_does_not_rewrite_preregistration(tmp_path):
    value = json.loads((ROOT / "config/a6-future-holdout-20261010.json").read_text())
    value["thresholds"]["btc_usdt"] = 0.2
    value["plan_sha256"] = qa.digest({k: v for k, v in value.items() if k != "plan_sha256"})
    path = tmp_path / "adapted.json"
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="digest changed"):
        qa.pinned_json(path, "plan_sha256", qa.PLAN_SHA)


def test_future_is_not_due_until_every_registered_bar_can_close():
    plan = json.loads((ROOT / "config/a6-future-holdout-20261010.json").read_text())
    assert not qa.future_due(plan, datetime(2026, 11, 8, 23, 59, 59, tzinfo=timezone.utc))
    assert qa.future_due(plan, datetime(2026, 11, 9, tzinfo=timezone.utc))
    plan["registered_at_utc"] = "2026-10-10T00:00:00+00:00"
    with pytest.raises(ValueError, match="registration must precede"):
        qa.future_due(plan, datetime(2026, 11, 9, tzinfo=timezone.utc))


def test_waiting_future_never_loads_a_model_or_downloads_data(tmp_path, monkeypatch):
    def forbidden(*a, **k):
        raise AssertionError("future inputs used before the registered end")
    monkeypatch.setattr(qa.subprocess, "run", forbidden)
    monkeypatch.setattr(qa, "urlopen", forbidden)
    result = qa.future(tmp_path, datetime(2026, 10, 9, tzinfo=timezone.utc), tmp_path / "missing")
    assert result["status"] == "WAITING_FULL_PREREGISTERED_FUTURE_WINDOW"
    assert result["pristine_future_holdout_complete"] is False


def test_live_crosscheck_waits_for_the_actual_archive_day(tmp_path, monkeypatch):
    monkeypatch.setattr(qa, "urlopen", lambda *a, **k: pytest.fail("current-day archive requested"))
    result = qa.live_side(tmp_path, datetime(2026, 10, 9, 23, 59, tzinfo=timezone.utc))
    assert result["archive_same_trade_crosscheck_complete"] is False


@pytest.mark.parametrize("positional", [True, False])
def test_same_trade_exact_side_price_size_and_timestamp_match(tmp_path, positional):
    key, value = qa.trade_commitment("BTCUSDT", "proof-id", 1791556200123, "Buy", "123.4500", "0.0100")
    archive = tmp_path / "a.csv.gz"
    with gzip.open(archive, "wt") as f:
        if not positional:
            f.write("id,timestamp,price,size,side\n")
        f.write("proof-id,1791556200.123,123.45,0.01,Buy\n")
    assert qa.match_archive(archive, "BTCUSDT", {key: value}, "2026-10-09") == 1


@pytest.mark.parametrize("row,reason", [
    ("proof-id,1791556200.123,123.45,0.01,Sell", "mismatch"),
    ("proof-id,1791556200.123,123.46,0.01,Buy", "mismatch"),
    ("proof-id,1791556200.123,123.45,0.02,Buy", "mismatch"),
    ("proof-id,1791556200.124,123.45,0.01,Buy", "mismatch"),
    ("other-id,1791556200.123,123.45,0.01,Buy", "missing committed"),
])
def test_wrong_counterpart_cannot_pass(tmp_path, row, reason):
    key, value = qa.trade_commitment("BTCUSDT", "proof-id", 1791556200123, "Buy", "123.45", "0.01")
    archive = tmp_path / "a.csv.gz"
    with gzip.open(archive, "wt") as f:
        f.write(row + "\n")
    with pytest.raises(ValueError, match=reason):
        qa.match_archive(archive, "BTCUSDT", {key: value}, "2026-10-09")


def test_duplicate_counterpart_rejected(tmp_path):
    key, value = qa.trade_commitment("BTCUSDT", "proof-id", 1791556200123, "Buy", "123.45", "0.01")
    archive = tmp_path / "a.csv.gz"
    with gzip.open(archive, "wt") as f:
        f.write("proof-id,1791556200.123,123.45,0.01,Buy\n" * 2)
    with pytest.raises(ValueError, match="duplicate captured"):
        qa.match_archive(archive, "BTCUSDT", {key: value}, "2026-10-09")
