"""Actual producer integration, signal coverage, causal clocks and legacy reads."""
from copy import deepcopy
import json
import base64
import hashlib
import io
import zipfile

import numpy as np
import pandas as pd
import pytest

import nexus_composite_signal_trace as trace
import nexus_composite_fill_oracle as oracle
import nexus_composite_runtime_requalification as rq
import nexus_composite_strategy_research as producer

SOURCE = "a" * 40
CANDIDATE = {"candidate_digest": "b" * 64, "mechanism": "structural_pullback",
             "strategy_config": {"mechanism": "structural_pullback", "risk_variant": 0}}


def frame(n=70):
    return pd.DataFrame({
        "decision_at": pd.date_range(end="2026-01-02T00:00Z", periods=n, freq="15min"),
        "open": np.full(n, 100.), "high": np.full(n, 100.1),
        "low": np.full(n, 99.9), "close": np.full(n, 100.), "atr": np.ones(n),
        "optional_warmup_feature": np.full(n, np.nan),
    })


def datasets(f):
    last = int(f.decision_at.iloc[-1].value // 1_000_000)
    return {tf: {"timeframe": tf, "binding_sha256": str(j) * 64, "row_count": len(f),
                 "first_open_time_ms": last - len(f) * step,
                 "last_open_time_ms": last - step}
            for j, (tf, step) in enumerate(rq.TIMEFRAME_STEP_MS.items(), 1)}


def captured(f, mask, **kwargs):
    return trace.capture_signals(f, mask, candidate=kwargs.get("candidate", CANDIDATE),
                                source_sha=kwargs.get("source_sha", SOURCE), symbol=kwargs.get("symbol", "BTCUSDT"),
                                datasets=datasets(f), peer_binding=None)


def evidence(f=None, mask=None):
    f = frame() if f is None else f
    if mask is None:
        mask = np.zeros(len(f), dtype=bool)
        mask[[0, 1, -1]] = True
        f.loc[1, ["high", "low"]] = [110., 95.]
    cap = captured(f, mask)
    profiles, audits = [], {}
    for name, fee, slip in (("conservative", 10, 5), ("stress", 25, 15)):
        observed = producer.backtest(f, mask, fee_bps=fee, slip_bps=slip, risk_variant=0)
        profiles.append({"profile": name, **observed})
        audits[name] = oracle.verify_fills(f, mask, fee_bps=fee, slip_bps=slip,
                                          risk_variant=0, observed=observed, include_trace=True)
    return trace.bind_fill_audits(cap, audits), profiles, f


def verify(value, profiles, f):
    trace.verify_trace(value, candidate=CANDIDATE, source_sha=SOURCE, symbol="BTCUSDT",
                       datasets=datasets(f), peer_binding=None, profiles=profiles)


def resign(value):
    cap = value["capture"]
    for event in cap["events"]:
        event["event_id"] = trace.digest({k: v for k, v in event.items() if k != "event_id"})
    cap["capture_digest"] = trace.digest({k: v for k, v in cap.items() if k != "capture_digest"})
    value["trace_digest"] = trace.digest({k: v for k, v in value.items() if k != "trace_digest"})


def test_records_filled_suppressed_and_terminal_signals_with_shared_ids():
    value, profiles, f = evidence()
    verify(value, profiles, f)
    for audit in value["independent_fill_audits"].values():
        assert [r["outcome"] for r in audit["decisions"]] == [
            "ENTRY_FILLED", "ENTRY_BAR_REARM_SUPPRESSED", "TERMINAL_NO_NEXT_OPEN"]
        assert audit["fills"][0]["bar"] == 1
        assert audit["fills"][0]["event_id"] == audit["fills"][1]["event_id"]
    assert value["financial_producer_emitted_fills_available"] is False
    assert value["batch_replay_not_prospective_capture"] is True


def test_future_price_and_feature_changes_preserve_prior_emitted_id():
    f = frame()
    mask = np.zeros(len(f), dtype=bool)
    mask[[3, 40]] = True
    before = captured(f, mask)
    f.loc[20:, "high"] *= 2
    f.loc[20:, "optional_warmup_feature"] = 999
    after = captured(f, mask)
    assert before["events"][0] == after["events"][0]
    assert before["events"][1]["event_id"] != after["events"][1]["event_id"]


@pytest.mark.parametrize("change", ["source_sha", "candidate", "symbol", "prefix"])
def test_identity_or_available_prefix_changes_event_id(change):
    f = frame()
    mask = np.zeros(len(f), dtype=bool)
    mask[3] = True
    before = captured(f, mask)
    options = {}
    if change == "prefix":
        f.loc[2, "optional_warmup_feature"] = 0
    else:
        options[change] = {"source_sha": "c" * 40, "symbol": "ETHUSDT",
                           "candidate": {**CANDIDATE, "candidate_digest": "d" * 64}}[change]
    assert before["events"][0]["event_id"] != captured(f, mask, **options)["events"][0]["event_id"]


@pytest.mark.parametrize("mutation", ["missing_event", "duplicate_event", "early_clock", "foreign_source",
                                     "missing_disposition", "invented_outcome", "early_fill", "missing_exit",
                                     "pnl", "fee", "exit_quantity", "missing_cost", "authority"])
def test_redigested_corruption_never_passes(mutation):
    value, profiles, f = evidence()
    cap = value["capture"]
    audit = value["independent_fill_audits"]["conservative"]
    if mutation == "missing_event": cap["events"].pop()
    elif mutation == "duplicate_event": cap["events"][1] = deepcopy(cap["events"][0])
    elif mutation == "early_clock": cap["events"][0]["available_at_ms"] -= trace.STEP_MS
    elif mutation == "foreign_source": cap["datasets_digest"] = "0" * 64
    elif mutation == "missing_disposition": audit["decisions"].pop()
    elif mutation == "invented_outcome": audit["decisions"][0]["outcome"] = "PROFIT_CERTIFIED"
    elif mutation == "early_fill": audit["fills"][0]["bar"] = 0
    elif mutation == "missing_exit": audit["fills"].pop()
    elif mutation == "pnl": audit["fills"][1]["pnl"] = "999"
    elif mutation == "fee": audit["fills"][0]["fee"] = "0"
    elif mutation == "exit_quantity": audit["fills"][1]["quantity"] = "0.1"
    elif mutation == "missing_cost": value["independent_fill_audits"].pop("stress")
    elif mutation == "authority": value["live_trading_authority"] = True
    resign(value)
    with pytest.raises(trace.SignalTraceError):
        verify(value, profiles, f)


def test_zero_signal_mask_is_complete_without_fabricated_trades():
    f = frame()
    value, profiles, _ = evidence(f, np.zeros(len(f), dtype=bool))
    verify(value, profiles, f)
    assert value["capture"]["events"] == []
    assert all(p["closed_round_trips"] == 0 for p in profiles)


def test_nonboolean_and_noncontiguous_decisions_are_rejected():
    f = frame()
    with pytest.raises(trace.SignalTraceError, match="boolean"):
        captured(f, np.zeros(len(f), dtype=int))
    f.loc[3, "decision_at"] += pd.Timedelta(minutes=15)
    with pytest.raises(trace.SignalTraceError, match="noncontiguous"):
        captured(f, np.zeros(len(f), dtype=bool))


def test_default_val40_producer_captures_before_either_financial_profile(monkeypatch, tmp_path):
    import canonical_backtest as canonical
    import nexus_canonical_paged_history as history
    import product_research_runtime as product
    f = frame(3072)
    f.loc[1, "high"] = 110
    f["timestamp"] = f["decision_at"] - pd.Timedelta(minutes=15)
    f["volume"] = 1.
    info = datasets(f)
    raw_frames = {}
    for tf, step in rq.TIMEFRAME_STEP_MS.items():
        raw = f.copy()
        raw["timestamp"] = pd.to_datetime(
            [info[tf]["first_open_time_ms"] + i * step for i in range(len(f))], unit="ms", utc=True)
        raw_frames[tf] = raw
    contexts = producer.build_features(raw_frames)
    for field in ("h1_compression", "h1_vol_ok", "h4_up", "h4_range"):
        f[field] = contexts[field]
    def artifact(symbol, tf):
        d = info[tf]
        step = rq.TIMEFRAME_STEP_MS[tf]
        return {**d, "tf": tf, "rows": [{"open_time_ms": d["first_open_time_ms"] + i * step}
                               for i in range(len(f))]}
    class Runtime:
        def __init__(self, *args, **kwargs): pass
        def fetch_dataset(self, *, symbol, timeframe, limit): return artifact(symbol, timeframe)
    monkeypatch.setattr(product, "ProductResearchRuntime", Runtime)
    monkeypatch.setattr(history, "fetch_verified_15m_window", lambda runtime, *, symbol, limit: artifact(symbol, "minute15"))
    monkeypatch.setattr(canonical, "canonical_ohlcv_frame", lambda a: (a, raw_frames[a["tf"]]))
    monkeypatch.setattr(producer, "build_features", lambda *a, **kw: f)
    mask = np.zeros(len(f), dtype=bool)
    mask[[0, -1]] = True
    monkeypatch.setattr(producer, "signal_for", lambda *a: mask)
    capture_impl, backtest_impl, order = trace.capture_signals, producer.backtest, []
    def capture(*args, **kwargs):
        order.append("capture")
        return capture_impl(*args, **kwargs)
    def backtest(*args, **kwargs):
        assert order[-1] in {"capture", "backtest"}
        order.append("backtest")
        return backtest_impl(*args, **kwargs)
    monkeypatch.setattr(trace, "capture_signals", capture)
    monkeypatch.setattr(producer, "backtest", backtest)
    rows = rq._default_evaluator(CANDIDATE, SOURCE, 1_767_312_060_000, tmp_path)
    assert order == ["capture", "backtest", "backtest", "backtest", "backtest"] * 2
    for row in rows:
        trace.verify_trace(row["emitted_signal_trace"], candidate=CANDIDATE, source_sha=SOURCE,
                           symbol=row["symbol"], datasets=row["datasets"], peer_binding=None,
                           profiles=row["profiles"])
    # The exact existing producer -> verifier -> QA-task/receipt path consumes
    # v3. Candidate validation itself is covered by its separate contract suite.
    import nexus_composite_runtime_independent_qa as qa
    candidate = {**CANDIDATE, "source_sha": "c" * 40, "archive_sha256": "d" * 64,
                 "timeframe": "minute15_with_completed_1h_4h", "config_fingerprint": "e" * 64}
    monkeypatch.setattr(rq, "_validated_candidate", lambda *args: deepcopy(candidate))
    now = int(f.decision_at.iloc[-1].value // 1_000_000) + 60_000
    result = rq.build_requalification(candidate, {}, source_sha=SOURCE, now_ms=now,
                                      state_root=tmp_path, evaluator=lambda *args: rows)
    assert result["schema_version"] == rq.ASOF_SCHEMA
    assert rq.verify_requalification(result)["decision"] == "pass"
    task = qa.build_task(result, rq.verify_requalification(result), producer_workflow_run_id=123)
    receipt = qa.run_independent_qa(task, lease_id="separate-qa-lease", execution_source_sha=SOURCE,
                                   state_root=tmp_path, replay=lambda *args: deepcopy(result))
    assert qa.verify_receipt(receipt, task, lease_id="separate-qa-lease", execution_source_sha=SOURCE)
    broken = deepcopy(result)
    broken["evaluations"][0].pop("emitted_signal_trace")
    broken["evaluations_digest"] = rq.digest(broken["evaluations"])
    broken["requalification_digest"] = rq.digest({k: v for k, v in broken.items() if k != "requalification_digest"})
    assert rq.verify_requalification(broken)["decision"] == "reject"
    broken = deepcopy(result)
    for row in broken["evaluations"]:
        row.pop("higher_timeframe_feature_audit")
    broken["schema_version"] = rq.TRACE_SCHEMA
    broken["evaluations_digest"] = rq.digest(broken["evaluations"])
    broken["requalification_digest"] = rq.digest({k: v for k, v in broken.items() if k != "requalification_digest"})
    assert rq.verify_requalification(broken)["decision"] == "pass"  # historical v2 remains readable
    broken = deepcopy(result)
    broken["evaluations"][0].pop("higher_timeframe_feature_audit")
    broken["evaluations_digest"] = rq.digest(broken["evaluations"])
    broken["requalification_digest"] = rq.digest({k: v for k, v in broken.items() if k != "requalification_digest"})
    assert rq.verify_requalification(broken)["decision"] == "reject"
    broken = deepcopy(result)
    broken["schema_version"] = rq.SCHEMA
    broken["requalification_digest"] = rq.digest({k: v for k, v in broken.items() if k != "requalification_digest"})
    assert rq.verify_requalification(broken)["decision"] == "reject"
    # A detected context discrepancy must stop before signal/fill generation.
    import nexus_composite_higher_timeframe_audit as higher
    def failed_audit(*args, **kwargs):
        raise higher.HigherTimeframeAuditError("synthetic early-source mutation")
    monkeypatch.setattr(higher, "audit_features", failed_audit)
    order.clear()
    with pytest.raises(rq.CompositeRuntimeRequalificationError, match="higher-timeframe"):
        rq._default_evaluator(CANDIDATE, SOURCE, now, tmp_path)
    assert order == []


def test_full_3072_bar_high_activity_trace_fits_bounded_transport(tmp_path):
    import nexus_composite_runtime_qa_transport as transport
    f = frame(3072)
    f["high"] = 110
    f["timestamp"] = f["decision_at"] - pd.Timedelta(minutes=15)
    f["volume"] = 1.
    data = datasets(f)
    raw_frames = {}
    for tf, step in rq.TIMEFRAME_STEP_MS.items():
        raw = f.copy()
        raw["timestamp"] = pd.to_datetime(
            [data[tf]["first_open_time_ms"] + i * step for i in range(len(f))], unit="ms", utc=True)
        raw_frames[tf] = raw
    features = producer.build_features(raw_frames)
    for field in ("h1_compression", "h1_vol_ok", "h4_up", "h4_range"):
        f[field] = features[field]
    import nexus_composite_higher_timeframe_audit as higher
    htf = higher.audit_features(raw_frames, f, candidate_digest=CANDIDATE["candidate_digest"],
                                source_sha=SOURCE, symbol="BTCUSDT", datasets=data)
    value, _, _ = evidence(f, np.ones(len(f), dtype=bool))
    producer_result = {"schema_version": rq.ASOF_SCHEMA,
                "evaluations": [{"emitted_signal_trace": value, "higher_timeframe_feature_audit": htf},
                                {"emitted_signal_trace": value, "higher_timeframe_feature_audit": htf}]}
    path = tmp_path / "producer.json"
    rq._atomic_json(path, producer_result)
    raw = path.read_bytes()
    assert len(raw) < transport.MAX_JSON_BYTES
    verification = {"decision": "pass"}
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("runtime-requalification.json", raw)
        z.writestr("verification.json", json.dumps(verification))
    blob = output.getvalue()
    assert 500_000 < len(blob) < transport.MAX_LOG_EVIDENCE_BYTES
    encoded = base64.b64encode(blob).decode()
    chunks = [encoded[i:i+48000] for i in range(0, len(encoded), 48000)]
    log = "\n".join(["NEXUS_COMPOSITE_VAL40_EVIDENCE_TRANSPORT=bounded-job-log-v2",
                     "NEXUS_COMPOSITE_VAL40_EVIDENCE_SHA256=" + hashlib.sha256(blob).hexdigest(),
                     "NEXUS_COMPOSITE_VAL40_EVIDENCE_SIZE=" + str(len(blob)),
                     "NEXUS_COMPOSITE_VAL40_EVIDENCE_CHUNK_COUNT=" + str(len(chunks)),
                     *[f"NEXUS_COMPOSITE_VAL40_EVIDENCE_CHUNK_{i:03d}={chunk}"
                       for i, chunk in enumerate(chunks)]]) + "\n"
    recovered = transport.parse_job_log_evidence(log.encode())
    assert recovered == blob
    parsed, _ = transport.parse_artifact(recovered, verifier=lambda p: verification)
    assert parsed == producer_result
