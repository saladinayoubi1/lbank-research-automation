"""Synthetic-only, adversarial frozen future source preflight tests.

Generated future-looking candles are TEST FIXTURES, NOT MARKET EVIDENCE.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime,timezone
from hashlib import sha256
import json

import numpy as np
import pandas as pd
import pytest

from scripts import nexus_portfolio_v3_forward_source_preflight as module

AFTER=datetime(2027,1,18,tzinfo=timezone.utc)
BEFORE=datetime(2026,10,18,tzinfo=timezone.utc)


def fixture(tmp_path):
    n=len(pd.date_range(module.SOURCE_START,module.SCORE_END-module.STEP,freq="4h"))
    t=pd.date_range(module.SOURCE_START,periods=n,freq="4h")
    src={}
    files={}
    for symbol in module.SYMBOLS:
        price=np.full(n, 250. if symbol=="BTCUSDT" else 80.)
        frame=pd.DataFrame({
            "timestamp":t,"open":price,"high":price*1.01,
            "low":price*.99,"close":price,"volume":np.full(n,2.)
        })
        path=tmp_path/(symbol+".parquet")
        frame.to_parquet(path,index=False)
        files[symbol]=path
        src[symbol]=sha256(path.read_bytes()).hexdigest()
    receipt={
        "schema":module.INPUT_SCHEMA,
        "claimed_provider":"BYBIT_SPOT",
        "claimed_4h_api_endpoint":"https://api.bybit.com/v5/market/kline",
        "claimed_http_status":200,
        "file_sha256_by_symbol":src,
        "collected_after_utc":"2027-01-18T00:00:00Z",
    }
    receipt_path=tmp_path/"source-claim.json"
    receipt_path.write_text(json.dumps(receipt))
    return files,receipt_path,receipt


def test_precommitted_forward_protocol_starts_after_known_archive():
    freeze,digest=module.verified_freeze()
    assert len(digest)==64
    assert digest==module.EXPECTED_FREEZE_SHA256
    assert module.SCORE_START==pd.Timestamp("2026-10-19T00:00:00Z")
    assert module.SCORE_END==pd.Timestamp("2027-01-17T00:00:00Z")
    assert module.SOURCE_START==pd.Timestamp("2026-08-01T00:00:00Z")
    assert freeze["original_pinned_archive_last_4h_open_utc"]=="2026-07-31T20:00:00Z"
    assert freeze["original_strategy_id"]=="b4e4a2c33304aec1"
    assert freeze["risk_threshold_selected_after_seeing_historical_34pct_drawdown"] is True
    assert freeze["auto_qualification"] is False and freeze["live_enabled"] is False
    assert freeze["current_provider_connectivity"].endswith("HTTP_403_ON_2026_10_18")


@pytest.mark.parametrize("field,value",[
    ("original_wallet_start_cash_usdt",10000),
    ("future_scoring_start_utc","2026-07-01T00:00:00Z"),
    ("original_strategy_id","renamed_fake_strategy"),
    ("independent_qa_required",False),
    ("no_parameter_search",False),
    ("live_enabled",True),
    ("auto_qualification",True),
    ("risk_policy",{"schema":"something_else"}),
    ("comparators",["cash_only"]),
    ("current_provider_connectivity","UNVERIFIED_CLAIM_OF_HTTP200"),
])
def test_freeze_cannot_be_tuned_later(tmp_path,field,value):
    original,_=module.verified_freeze()
    mutated=deepcopy(original)
    mutated[field]=value
    p=tmp_path/"modified-freeze.json"
    p.write_text(json.dumps(mutated))
    with pytest.raises(module.ForwardSourceError,match="freeze altered"):
        module.verified_freeze(p)


def test_true_future_horizon_not_finished_today_even_if_caller_forces_file_claim(tmp_path):
    files,receipt,_=fixture(tmp_path)
    with pytest.raises(module.ForwardSourceError,match="horizon incomplete"):
        module.audit_future_extension(receipt,files["BTCUSDT"],files["ETHUSDT"],
                                      observed_at_utc=BEFORE)


def test_fully_completed_synthetic_grid_only_proves_bytes_not_exchange_origin(tmp_path):
    files,receipt,_=fixture(tmp_path)
    o=module.audit_future_extension(receipt,files["BTCUSDT"],files["ETHUSDT"],
                                   observed_at_utc=AFTER)
    assert o["extension_start_matches_previously_verified_original_archive_tail"] is True
    assert o["original_historical_archive_six_sha_rechecked_in_this_preflight"] is False
    assert o["source_provider_claim_not_independently_authenticated"] is True
    assert o["market_data_real_exchange_provenance_independently_verified"] is False
    assert o["ready_for_strategy_result_or_paper"] is False
    assert o["paper_eligible"] is False and o["live_enabled"] is False
    assert o["sources"]["BTCUSDT"]["future_scoring_4h_bars"]>0
    assert o["sources"]["ETHUSDT"]["warmup_4h_bars"]>0


def test_one_missing_bar_and_duplicate_bar_rejected(tmp_path):
    files,receipt,claims=fixture(tmp_path)
    p=files["BTCUSDT"]
    altered=pd.read_parquet(p)
    altered.drop(index=2).reset_index(drop=True).to_parquet(p,index=False)
    claims["file_sha256_by_symbol"]["BTCUSDT"]=sha256(p.read_bytes()).hexdigest()
    receipt.write_text(json.dumps(claims))
    with pytest.raises(module.ForwardSourceError,match="missing/extra"):
        module.audit_future_extension(receipt,p,files["ETHUSDT"],observed_at_utc=AFTER)
    frame=pd.read_parquet(files["ETHUSDT"])
    frame.loc[7,"timestamp"]=frame.loc[6,"timestamp"]
    with pytest.raises(module.ForwardSourceError,match="strictly contiguous"):
        module.validate_physical_4h(frame,"ETHUSDT")


def test_wrong_source_hash_even_with_valid_candles_fails(tmp_path):
    files,receipt,claims=fixture(tmp_path)
    claims["file_sha256_by_symbol"]["BTCUSDT"]="0"*64
    receipt.write_text(json.dumps(claims))
    with pytest.raises(module.ForwardSourceError,match="raw physical parquet"):
        module.audit_future_extension(receipt,files["BTCUSDT"],files["ETHUSDT"],
                                      observed_at_utc=AFTER)


def test_other_market_provider_and_backdated_collection_refused(tmp_path):
    files,receipt,claims=fixture(tmp_path)
    claims["claimed_provider"]="BITGET"
    receipt.write_text(json.dumps(claims))
    with pytest.raises(module.ForwardSourceError,match="untrusted substitute"):
        module.audit_future_extension(receipt,files["BTCUSDT"],files["ETHUSDT"],
                                      observed_at_utc=AFTER)
    claims["claimed_provider"]="BYBIT_SPOT"
    claims["collected_after_utc"]="2026-10-18T00:00:00Z"
    receipt.write_text(json.dumps(claims))
    with pytest.raises(module.ForwardSourceError,match="uncredible claimed"):
        module.audit_future_extension(receipt,files["BTCUSDT"],files["ETHUSDT"],
                                      observed_at_utc=AFTER)


def test_unphysical_ohlc_and_negative_volume_block_any_scoring(tmp_path):
    files,_,_=fixture(tmp_path)
    f=pd.read_parquet(files["BTCUSDT"])
    f.loc[8,"high"]=f.loc[8,"low"]-1
    with pytest.raises(module.ForwardSourceError,match="unphysical OHLC"):
        module.validate_physical_4h(f,"BTCUSDT")
    f=pd.read_parquet(files["BTCUSDT"])
    f.loc[9,"volume"]=-2
    with pytest.raises(module.ForwardSourceError,match="unphysical price/volume"):
        module.validate_physical_4h(f,"BTCUSDT")


def test_disallow_naive_source_4h_timestamps(tmp_path):
    files,_,_=fixture(tmp_path)
    f=pd.read_parquet(files["BTCUSDT"])
    f["timestamp"]=f["timestamp"].dt.tz_localize(None)
    # pandas datetime64 naive would silently be interpreted UTC; block at
    # source contract instead of guessing physical exchange timezone.
    with pytest.raises(module.ForwardSourceError,match="explicit UTC"):
        module.validate_physical_4h(f,"BTCUSDT")
