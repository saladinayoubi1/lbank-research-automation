"""Close-confirmed MR40 entry-veto tests; no private exchange calls."""
from __future__ import annotations
import importlib.util
import json
from pathlib import Path

def engine():
    file=Path(__file__).resolve().parents[1]/"research"/"nexus_mr40_entry_quality_v1.py"
    spec=importlib.util.spec_from_file_location("mr40_entry_quality",file)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    return m

def synthetic():
    m=engine()
    rows=[[i*m.Decimal(14400000),m.Decimal(100),m.Decimal(105),m.Decimal(96),m.Decimal(100),m.Decimal(0)] for i in range(220)]
    # j=185 is the only legitimate first positive signal for this episode.
    signals=[0]*220
    signals[185:191]=[1]*6
    rows[185][1]=m.Decimal(102);rows[185][4]=m.Decimal(99)   # red down-bar
    rows[186][1]=m.Decimal(99);rows[186][4]=m.Decimal(104)  # strong following green
    return m,rows,signals

def test_veto_is_whole_episode_not_late_reentry():
    m,rows,signals=synthetic()
    out,decisions=m.filtered_signals(rows,signals,181,220,{"id":"green_reversal"})
    assert len(decisions)==1 and decisions[0]["allowed"] is False
    assert out[185:191]==[0]*6
    assert signals[185:191]==[1]*6

def test_green_accepts_only_first_closed_signal():
    m,rows,signals=synthetic()
    rows[185][1]=m.Decimal(98)
    rows[185][4]=m.Decimal(103)
    out,decisions=m.filtered_signals(rows,signals,181,220,{"id":"green_reversal"})
    assert decisions[0]["allowed"] is True
    assert out[185:191]==[1]*6

def test_prefix_invariance_future_bars_irrelevant():
    m,rows,signals=synthetic()
    case={"id":"range_quiet_14"}
    a=m.filtered_signals(rows,signals,181,190,case)[0][:190]
    rows[191][1]=m.Decimal(1000);rows[191][4]=m.Decimal(5)
    b=m.filtered_signals(rows,signals,181,220,case)[0][:190]
    assert a==b

def test_registered_filters_and_policy_paper_off():
    m,rows,signals=synthetic()
    cfg=json.loads((Path(__file__).resolve().parents[1]/"research"/"mr40_entry_quality_v1.json").read_bytes())
    assert cfg["schema"]=="mr40.entry-quality-v1"
    assert len(cfg["candidate_filters"])==6
    assert "Paper 500 USDT on Laptop2 untouched" in cfg["restriction"]
    for case in cfg["candidate_filters"]:
        m.filtered_signals(rows,signals,181,220,case)

def test_frozen_entry_quality_evidence():
    """Check the 144 existing trade-acceptance outcomes without rerunning prices."""
    import gzip,hashlib
    root=Path(__file__).resolve().parents[1]
    d=root/"docs"/"evidence"/"mr40-entry-quality-20261022"
    a=d/"results.json.gz";b=d/"ledger.jsonl.gz"
    assert hashlib.sha256(a.read_bytes()).hexdigest()=="b6ca802e3142f2121b0bfcb639a669359955b88c8137302fbe461eec4d3febf0"
    assert hashlib.sha256(b.read_bytes()).hexdigest()=="2c7115bac4ae81cc5c21b9bfc96319d5bee79baa746074c92c998125a834331e"
    with gzip.open(a,"rt",encoding="utf-8") as f:
        data=json.load(f)
    logical=data.pop("digest")
    c=json.dumps(data,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()
    assert hashlib.sha256(c).hexdigest()==logical=="b19bb3302aebbadfff9ddea84429bfba2c047454f93ff93e9388de98db8933c5"
    assert data["runs"]==len(data["rows"])==144
    assert len(data["base_parity"])==24
    assert data["selection"]=={"qualified_train":[],"chosen":"baseline","evaluation_pass":False}
    assert all(v is False for v in data["candidate_evaluation_gates"].values())
    assert data["paper_changed"] is False and data["future_blind"] is False
    with gzip.open(b,"rt",encoding="utf-8") as f:
        entries=[json.loads(line) for line in f]
    assert len(entries)==144
    assert all(x["decisions"] for x in entries)
    assert all(x["key"]["case"]=="baseline" or x["key"]["case"] in data["candidate_evaluation_gates"] for x in entries)

def test_descriptive_entry_feature_audit_provenance():
    """The trade-level observed labels must agree with frozen entry conditions."""
    import hashlib
    source=Path(__file__).resolve().parents[1]/"docs"/"evidence"/"mr40-entry-quality-20261022"/"entry_conditions_audit.json"
    data=json.loads(source.read_bytes())
    original=data.pop("digest")
    check=json.dumps(data,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()
    assert hashlib.sha256(check).hexdigest()==original=="f9576b4033ebe15d3485cd3fc65d3c0ada4f1a8bb676a9808105b467b374d614"
    train=data["windows"]["train"];eval_group=data["windows"]["evaluation"]
    assert len(train["entries"])==25 and len(eval_group["entries"])==22
    assert train["groups"]["winners"]["count"]==19 and train["groups"]["losers"]["count"]==6
    assert eval_group["groups"]["winners"]["count"]==18 and eval_group["groups"]["losers"]["count"]==4
    assert data["limitation"].startswith("Labels realized from future holding outcomes")

def test_early_excursion_audit_is_frozen_and_descriptive():
    """Read pinned ORIGINAL trade outcomes, never use outcome labels as signals."""
    import hashlib
    evidence=Path(__file__).resolve().parents[1]/"docs"/"evidence"/"mr40-entry-quality-20261022"/"excursion_audit.json"
    data=json.loads(evidence.read_bytes())
    expected=data.pop("digest")
    canonical=json.dumps(data,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()
    assert hashlib.sha256(canonical).hexdigest()==expected=="7668ccee045daf90da0b2b267298c24b681a1867d4f97e1c789cacba6f638bd2"
    assert data["limitation"].startswith("Future outcome labels")
    assert data["evidence"]["quality_ledger_sha256"]=="2c7115bac4ae81cc5c21b9bfc96319d5bee79baa746074c92c998125a834331e"
    assert data["evidence"]["entry_stop_ledger_sha256"]=="138beb278daf2d0f83f015e06b9be80eac406f590b28a0581d3341e8dc2f52e3"
    train=data["windows"]["train"]
    evaluate=data["windows"]["evaluation"]
    assert len(train["positions"])==25 and len(evaluate["positions"])==22
    assert evaluate["groups"]["baseline_winners"]["positions"]==18
    assert evaluate["groups"]["baseline_losers"]["positions"]==4
    assert evaluate["groups"]["baseline_losers"]["recorded_stop4_exits"]==2
    assert evaluate["groups"]["baseline_winners"]["recorded_stop4_exits"]==1
    assert evaluate["groups"]["baseline_losers"]["plus2_usable_to_protect"]==0
    crash=next(x for x in evaluate["positions"] if x["entry_utc"].startswith("2025-10-10T16:00:00"))
    assert crash["max_adverse_low_pct"]>14
    assert crash["reached_plus2_closed"] is False
    assert crash["observed_entry4_stop_hit"] is True
