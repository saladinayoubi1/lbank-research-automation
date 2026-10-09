"""Legacy candle roots must stay frozen across source-row ordering migration."""
import hashlib
import json
from pathlib import Path

import pytest

import bybit_spot_backfill as backfill


def test_legacy_root_rejected_before_inventory_network_or_file_mutation(tmp_path):
    state = tmp_path / "legacy"
    state.mkdir()
    checkpoint = dict(schema_version=1, completed_units=[dict(unit_id="monthly:2022-12")],
                      failed_units=[], runs=[])
    path = state / backfill.CHECKPOINT_NAME
    path.write_text(json.dumps(checkpoint))
    before = {p.name: p.read_bytes() for p in state.iterdir()}
    def no_network(*_):
        pytest.fail("legacy root validation must precede network access")
    with pytest.raises(backfill.BybitBackfillError, match="Legacy or mixed candle semantics"):
        backfill.run_backfill(state_root=state, inventory_fetcher=no_network)
    assert {p.name: p.read_bytes() for p in state.iterdir()} == before


def test_mixed_source_manifest_rejected_even_with_versioned_root(tmp_path):
    (tmp_path/backfill.CHECKPOINT_NAME).write_text(json.dumps(dict(
        schema_version=1, completed_units=[dict(unit_id="a")], failed_units=[], runs=[])))
    model = backfill.candle_model_receipt()
    (tmp_path/backfill.CANDLE_MODEL_NAME).write_text(json.dumps(model))
    (tmp_path/backfill.SOURCE_MANIFEST_NAME).write_text(json.dumps([
        dict(candle_model=model), dict(filename="legacy.csv.gz")]))
    with pytest.raises(backfill.BybitBackfillError, match="Legacy or mixed"):
        backfill.validate_candle_model_state(tmp_path)


def test_versioned_source_receipt_and_manifest_resume_are_source_bound(tmp_path):
    model = backfill.candle_model_receipt()
    assert model["module_sha256"] == hashlib.sha256(Path(backfill.__file__).read_bytes()).hexdigest()
    assert model["live_trading_authority"] is False
    assert model["historical_report_compatibility"] == "explicit_replay_required"
    (tmp_path/backfill.CHECKPOINT_NAME).write_text(json.dumps(dict(
        schema_version=1, completed_units=[dict(unit_id="a")], failed_units=[], runs=[])))
    (tmp_path/backfill.CANDLE_MODEL_NAME).write_text(json.dumps(model))
    (tmp_path/backfill.SOURCE_MANIFEST_NAME).write_text(json.dumps([dict(candle_model=model)]))
    backfill.validate_candle_model_state(tmp_path)
