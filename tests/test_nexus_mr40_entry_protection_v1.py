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
