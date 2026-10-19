from copy import deepcopy
import ast
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import nexus_composite_higher_timeframe_audit as audit
import nexus_composite_strategy_research as producer

SOURCE, CANDIDATE = "a" * 40, "b" * 64
FIELDS = [f for tf in audit.INTERVALS for f in audit.FIELDS[tf]]


def fixture(seed=7):
    rng = np.random.default_rng(seed)
    frames = {}
    for tf, step, n in (("minute15", audit.STEP, 3072), ("hour1", 3_600_000, 768),
                        ("hour4", 14_400_000, 192)):
        price = 100 + np.cumsum(rng.normal(0, .2, n))
        span = rng.uniform(.05, 2, n)
        frames[tf] = pd.DataFrame({"timestamp": pd.date_range("2026-01-01", periods=n,
                                  freq=pd.Timedelta(milliseconds=step), tz="UTC"),
                                  "open": price, "high": price+span, "low": price-span,
                                  "close": price, "volume": rng.uniform(1, 100, n)})
    return frames


def bindings(frames):
    return {tf: {"timeframe": tf, "binding_sha256": str(i) * 64, "row_count": len(f),
                 "first_open_time_ms": int(f.timestamp.iloc[0].value // 1_000_000),
                 "last_open_time_ms": int(f.timestamp.iloc[-1].value // 1_000_000)}
            for i, (tf, f) in enumerate(frames.items(), 1)}


def evidence(frames=None):
    frames = fixture() if frames is None else frames
    observed = producer.build_features(frames)
    data = bindings(frames)
    receipt = audit.audit_features(frames, observed, candidate_digest=CANDIDATE,
                                   source_sha=SOURCE, symbol="BTCUSDT", datasets=data)
    return frames, observed, data, receipt


def verify(receipt, data):
    audit.verify_audit(receipt, candidate_digest=CANDIDATE, source_sha=SOURCE,
                       symbol="BTCUSDT", datasets=data)


@pytest.mark.parametrize("seed", [3, 17, 83])
def test_independent_raw_equations_match_all_four_context_fields(seed):
    _, _, data, receipt = evidence(fixture(seed))
    verify(receipt, data)
    assert receipt["decision_grid"]["rows"] == 3072
    for tf, source in receipt["sources"].items():
        assert all("0" in mask and "1" in mask for mask in source["feature_masks"].values())
        assert len(receipt["asof_source_indices"][tf]) == 3072


def test_exact_hour_and_four_hour_close_and_initial_missing_source():
    _, observed, _, receipt = evidence()
    h1, h4 = (receipt["asof_source_indices"][tf] for tf in ("hour1", "hour4"))
    assert h1[:5] == [-1, -1, -1, 0, 0]
    assert h4[14:17] == [-1, 0, 0]
    assert observed.loc[:2, ["h1_compression", "h1_vol_ok"]].isna().all().all()
    assert observed.loc[3, "h1_vol_ok"] == 0  # source warmup is false, not missing


@pytest.mark.parametrize("field", FIELDS)
def test_corrupted_or_early_producer_context_is_rejected(field):
    frames, observed, data, _ = evidence()
    observed.loc[1000, field] = 1 - observed.loc[1000, field]
    with pytest.raises(audit.HigherTimeframeAuditError, match=field):
        audit.audit_features(frames, observed, candidate_digest=CANDIDATE,
                             source_sha=SOURCE, symbol="BTCUSDT", datasets=data)


def test_independent_join_does_not_inherit_a_producer_asof_bug(monkeypatch):
    frames = fixture()
    correct = producer._closed_asof
    def early(source, interval_ms, decision, fields, label):
        return correct(source, 0, decision, fields, label)
    monkeypatch.setattr(producer, "_closed_asof", early)
    with pytest.raises(audit.HigherTimeframeAuditError, match="mismatch"):
        audit.audit_features(frames, producer.build_features(frames), candidate_digest=CANDIDATE,
                             source_sha=SOURCE, symbol="BTCUSDT", datasets=bindings(frames))


def test_future_tail_and_unclosed_source_mutations_preserve_every_earlier_origin():
    frames, observed, _, before = evidence()
    cutoff = observed.decision_at.iloc[1500]
    changed = deepcopy(frames)
    for tf, frame in changed.items():
        interval = audit.STEP if tf == "minute15" else audit.INTERVALS[tf]
        future = frame.timestamp + pd.Timedelta(milliseconds=interval) > cutoff
        frame.loc[future, ["open", "high", "low", "close"]] *= 9
        frame.loc[future, "volume"] *= 7
    _, after, _, proof = evidence(changed)
    pd.testing.assert_frame_equal(observed.loc[:1500, FIELDS], after.loc[:1500, FIELDS])
    assert audit._joined(before["sources"], before["asof_source_indices"], 1501) == audit._joined(
        proof["sources"], proof["asof_source_indices"], 1501)
    for tf in audit.INTERVALS:
        indices = before["asof_source_indices"][tf][:1501]
        assert indices == proof["asof_source_indices"][tf][:1501]
        last = max(indices)
        assert before["sources"][tf]["prefix_sha256"][:last+1] == proof["sources"][tf]["prefix_sha256"][:last+1]


@pytest.mark.parametrize("mutation", ["early", "late", "missing_row", "boolean_index", "missing_source",
                                      "source_binding", "formula", "value_digest", "authority", "wrong_symbol"])
def test_resigned_but_invalid_receipts_fail_closed(mutation):
    _, _, data, receipt = evidence()
    if mutation == "early": receipt["asof_source_indices"]["hour1"][2] = 0
    elif mutation == "late": receipt["asof_source_indices"]["hour4"][15] = -1
    elif mutation == "missing_row": receipt["sources"]["hour1"]["prefix_sha256"].pop()
    elif mutation == "boolean_index": receipt["asof_source_indices"]["hour1"][3] = False
    elif mutation == "missing_source": receipt["sources"].pop("hour4")
    elif mutation == "source_binding": data["hour1"]["binding_sha256"] = "e" * 64
    elif mutation == "formula": receipt["formula_contract"] = {}
    elif mutation == "value_digest": receipt["observed_values_sha256"] = "e" * 64
    elif mutation == "authority": receipt["live_trading_authority"] = True
    elif mutation == "wrong_symbol": receipt["identity"]["symbol"] = "ETHUSDT"
    receipt["audit_digest"] = audit.digest({k: v for k, v in receipt.items() if k != "audit_digest"})
    with pytest.raises(audit.HigherTimeframeAuditError): verify(receipt, data)


def test_raw_dataset_metadata_and_utc_grid_are_independently_checked():
    frames, observed, data, _ = evidence()
    data["hour1"]["first_open_time_ms"] += 3_600_000
    with pytest.raises(audit.HigherTimeframeAuditError, match="binding"):
        audit.audit_features(frames, observed, candidate_digest=CANDIDATE,
                             source_sha=SOURCE, symbol="BTCUSDT", datasets=data)
    frames["hour4"].loc[5, "timestamp"] += pd.Timedelta(minutes=15)
    with pytest.raises(audit.HigherTimeframeAuditError, match="UTC grid"):
        audit.audit_features(frames, observed, candidate_digest=CANDIDATE,
                             source_sha=SOURCE, symbol="BTCUSDT", datasets=bindings(frames))


def test_reference_has_no_pandas_numpy_or_producer_imports():
    syntax = ast.parse(Path(audit.__file__).read_text())
    imports = [n.module for n in ast.walk(syntax) if isinstance(n, ast.ImportFrom)]
    imports += [alias.name for n in ast.walk(syntax) if isinstance(n, ast.Import) for alias in n.names]
    assert all(not x.startswith(("pandas", "numpy", "nexus_composite_strategy")) for x in imports)
