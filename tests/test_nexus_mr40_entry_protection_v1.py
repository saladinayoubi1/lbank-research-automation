"""Synthetic tests of MR40 stop arming on entry and stop priority."""
from pathlib import Path
import importlib.util
import json

def _load():
    engine=Path(__file__).resolve().parents[1]/"research"/"nexus_mr40_entry_protection_v1.py"
    spec=importlib.util.spec_from_file_location("mr40_entry_stop_engine",engine)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def _case(engine,variant,bar_overrides=None,signals=None):
    p=[[100,103,97,100]]*13
    p=[x.copy() for x in p]
    for i,v in (bar_overrides or {}).items():p[i]=v
    rows=[[i*engine.STEP,*r,1] for i,r in enumerate(p)]
    sig=signals or ([0]+[1]*10+[0]*2)
    data={"episode":[int(bool(x)) for x in sig],"close":[r[4] for r in rows]}
    return engine.simulate(rows,data,sig,variant,1,len(rows),
             {"id":"normal","fee_bps":10,"slippage_bps":5,"lag_bars":1},10000)

def test_first_candle_entry_low_hits_preplaced_stop():
    e=_load()
    o=_case(e,{"id":"initial4","initial_stop":.04,"arm2":False},
         {2:[100,102,95,99]})
    exits=[f for f in o["fills"] if f["reason"]=="stop_hit"]
    assert len(exits)==1
    assert exits[0]["bar_index"]==2
    assert exits[0]["fill_ms"]==2*e.STEP
    assert exits[0]["reference"]=="96.0480000000"
    assert o["metrics"]["stops"]==1

def test_initial_stop_ignores_high_without_close_trigger():
    e=_load()
    o=_case(e,{"id":"combo4","initial_stop":.04,"arm2":True},
        {2:[100,140,98,100],3:[100,140,98,100]})
    assert o["metrics"]["ratchets"]==0

def test_open_gap_is_executed_at_open_not_stop():
    e=_load()
    o=_case(e,{"id":"initial4","initial_stop":.04,"arm2":False},
         {2:[100,103,99,100],3:[90,100,88,98]})
    stop=next(f for f in o["fills"] if f["reason"]=="stop_gap")
    assert stop["bar_index"]==3
    assert float(stop["reference"])==90
    assert float(stop["price"])<90

def test_baseline_never_enters_protective_exit():
    e=_load()
    o=_case(e,{"id":"baseline","initial_stop":None,"arm2":False},
         {2:[100,102,90,92]})
    assert not any(x["reason"].startswith("stop_") for x in o["fills"])
    assert o["metrics"]["stops"]==0

def test_frozen_protocol_and_no_live_imports():
    cfg=json.loads((Path(__file__).resolve().parents[1]/"research"/"mr40_entry_protection_v1.json").read_text())
    assert cfg["schema"]=="mr40.entry_protection.v1"
    assert len(cfg["cases"])==8
    assert cfg["constraints"]=={"paper_change":False,"real_orders":False,"live":False,"auto_merge":False}

def test_192_frozen_entry_stop_evidence_integrity():
    from pathlib import Path
    import gzip, hashlib
    root=Path(__file__).resolve().parents[1]
    bundle=root/"docs"/"evidence"/"mr40-entry-stop-20261022"
    result=bundle/"results.json.gz"
    ledger=bundle/"ledger.jsonl.gz"
    assert hashlib.sha256(result.read_bytes()).hexdigest()=="93eb5afbab9e94dddfc236a304df1f067a8d69d66d5c4edec081c3cfcb7b394b"
    assert hashlib.sha256(ledger.read_bytes()).hexdigest()=="138beb278daf2d0f83f015e06b9be80eac406f590b28a0581d3341e8dc2f52e3"
    with gzip.open(result,"rt",encoding="utf8") as f:
        data=json.load(f)
    logical_digest=data.pop("digest")
    c=json.dumps(data,sort_keys=True,ensure_ascii=False,separators=(",",":"),allow_nan=False).encode()
    assert hashlib.sha256(c).hexdigest()==logical_digest=="8420f3a6f9135469f433020ee61e99606733dead0e5bcfa90065adbaa6f535d3"
    assert data["runs"]==len(data["rows"])==192
    assert len(data["control_parity"])==24
    assert data["evaluation_success"]=={"profit":False,"efficiency":False}
    assert data["paper_changed"] is False
    with gzip.open(ledger,"rt",encoding="utf8") as f:
        assert sum(1 for line in f)==192
