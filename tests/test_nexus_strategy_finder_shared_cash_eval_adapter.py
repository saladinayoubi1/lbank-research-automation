"""Guardrails for reviewed-composite -> physical shared-cash gate integration."""
from __future__ import annotations

import json
import numpy as np
import pandas as pd
import pytest
from pathlib import Path

from nexus_composite_strategy_research import (
    SCHEMA as COMPOSITE_SCHEMA,digest as composite_digest
)
from nexus_demo_archive_replay import ARCHIVE_SHA256
from scripts import nexus_strategy_finder_shared_cash_eval as cli
from research.strategy_finder_shared_cash_physical import _digest


def known():
    c=cli.CONFIGS[0]
    sha=composite_digest({"config":c,"dataset":ARCHIVE_SHA256,"contract":COMPOSITE_SCHEMA})
    return c,sha


def test_known_mechanism_fingerprint_binds_all_original_fields():
    c,sha=known()
    found=cli.reviewed_config(c["mechanism"],sha)
    assert found["mechanism"]==c["mechanism"]
    assert found["fingerprint"]==sha
    assert found["risk_variant"]==c["risk_variant"]


def test_unregistered_mechanism_denied_without_probing_market():
    with pytest.raises(cli.CandidateBridgeError):
        cli.reviewed_config("elliott_live_bot", "a"*64)


def test_wrong_composite_contract_sha_denied():
    c,sha=known()
    with pytest.raises(cli.CandidateBridgeError,match="fingerprint"):
        cli.reviewed_config(c["mechanism"],"0"*64)


def test_reviewed_risk_variant_1_cannot_silently_use_different_stop_model():
    old=next(x for x in cli.CONFIGS if x["risk_variant"]==1)
    sha=composite_digest({"config":old,"dataset":ARCHIVE_SHA256,
                          "contract":COMPOSITE_SCHEMA})
    with pytest.raises(cli.CandidateBridgeError,match="risk_variant=0"):
        cli.reviewed_config(old["mechanism"],sha)


def test_short_or_uppercase_fingerprint_denied():
    c,sha=known()
    for bad in ("abc","F"*64,"z"*64):
        with pytest.raises(cli.CandidateBridgeError):
            cli.reviewed_config(c["mechanism"],bad)


def test_archive_authentication_fail_closed_before_feature_loading(monkeypatch,tmp_path):
    c,sha=known()
    def no_loader(_):
        raise AssertionError("could not fetch any invalid archive")
    monkeypatch.setattr(cli,"_load_frontier_features",no_loader)
    with pytest.raises(cli.CandidateBridgeError):
        cli.evaluate_readonly(tmp_path,c["mechanism"],sha,"deadbeef")
    with pytest.raises(cli.CandidateBridgeError):
        cli.evaluate_readonly(tmp_path/"missing",c["mechanism"],sha,ARCHIVE_SHA256)


def test_causal_integration_with_original_reviewed_identity_only(monkeypatch,tmp_path):
    c,sha=known()
    t=pd.date_range("2025-01-01T00:15:00Z",periods=120,freq="15min")
    sources={}
    for symbol in ("BTCUSDT","ETHUSDT"):
        sources[symbol]=pd.DataFrame({
            "decision_at":t,
            "open":np.full(120,100.),
            "high":np.full(120,101.),
            "low":np.full(120,99.),
            "close":np.full(120,100.),
            "atr":np.full(120,2.0),
            "mock_symbol":symbol,
        })
    monkeypatch.setattr(cli,"_load_frontier_features",lambda _:sources)
    def known_signal(frame,config):
        assert config["fingerprint"]==sha
        x=np.zeros(len(frame),dtype=bool)
        x[4]=True
        x[60]=True
        x[104]=True
        return x
    monkeypatch.setattr(cli,"signal_for",known_signal)
    evidence=cli.evaluate_readonly(tmp_path,c["mechanism"],sha,ARCHIVE_SHA256)
    assert evidence["selected_exact_config_fingerprint"]==sha
    assert evidence["research_source_archive_sha256"]==ARCHIVE_SHA256
    assert evidence["source_authentication"]=="EXISTING_VERIFIED_ARCHIVE_LOADER_PLUS_EXACT_SHA"
    assert evidence["not_qualified_for_demo"] is True
    assert evidence["qualified"] is False
    assert evidence["orders"]==0 and evidence["live_enabled"] is False
    assert evidence["result_digest"]==_digest({k:v for k,v in evidence.items() if k!="result_digest"})
    assert all(
        profile["initial_shared_cash_usdt"]==500
        for partition in evidence["partitions"].values()
        for profile in partition.values()
    )


def test_evidence_writer_is_exactly_write_once(tmp_path):
    p=tmp_path/"evidence"/"result.json"
    data={"status":"NEGATIVE","paper_eligible":False,"live_enabled":False}
    cli.write_once(p,data)
    assert json.loads(p.read_text("utf8"))==data
    with pytest.raises(cli.CandidateBridgeError,match="write-once"):
        cli.write_once(p,{"status":"POSTHOC_PROFIT"})
    assert json.loads(p.read_text("utf8"))==data


def test_no_automatic_order_connection_to_main_runner():
    source=Path(cli.__file__).read_text("utf8")
    assert "create_order(" not in source
    assert "place_order(" not in source
    assert cli.ARCHIVE_SHA256
