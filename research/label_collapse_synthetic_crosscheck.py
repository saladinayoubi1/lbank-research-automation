"""Synthetic integration/corruption checks; never reads market files."""
import copy, importlib.util, json, sys
from pathlib import Path

def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    obj=importlib.util.module_from_spec(spec);spec.loader.exec_module(obj);return obj

p=module("label_producer",sys.argv[1]);q=module("label_qa",sys.argv[2])
contract=json.loads(Path(sys.argv[3]).read_text(encoding="utf-8-sig"))
out=Path(sys.argv[4]);checks=[]
def make(bars):
    for rows in bars.values():
        for b in rows:
            I=b["imbalance"];buy=(1+I)*100;sell=(1-I)*100
            b.update(volume=2.,trades=1,buy_quote=buy,sell_quote=sell,
                 buy_quote_decimal=str(buy),sell_quote_decimal=str(sell),source_raw_sha256="0"*64)
    return {"bars":bars}
def reports(f):
    bars=f["bars"]
    books={name:{c:p.run_book(bars,c,flow) for c in p.PROFILES}
           for name,flow in (("candidate",True),("price_only",False))}
    passive={c:{k:p.passive(bars,c,k) for k in (*p.SYMBOLS,"full_50_50","capped_50_50","cash")} for c in p.PROFILES}
    a=books["candidate"];control=books["price_only"]["stress"];b=passive["stress"]["capped_50_50"]
    gates={"all_three_costs_positive":all(a[c]["net_pnl_usdt"]>0 for c in p.PROFILES),
      "stress_beats_no_flow":a["stress"]["net_pnl_usdt"]>control["net_pnl_usdt"],
      "stress_beats_capped_passive":a["stress"]["net_pnl_usdt"]>b["net_pnl_usdt"],
      "stress_dd_no_worse_capped_passive":a["stress"]["max_close_drawdown_fraction"]<=b["max_close_drawdown_fraction"]}
    passed=all(gates.values())
    return {"books":books,"passive":passive,"decision_gates":gates,"exploratory_pass":passed,
      "outcome":"exploratory_lead_only" if passed else "terminal_negative_no_retune",
      "paper_eligible":False,"live_enabled":False,"orders":0}
for scenario in ("time","both_hit","stop_gap","target_gap","terminal","last_bar_entry"):
    bars=p.fixture(474)
    if scenario=="both_hit":bars["BTCUSDT"][2].update(high=110.,low=98.)
    elif scenario=="stop_gap":bars["BTCUSDT"][3].update(open=95.,high=96.,low=94.,close=95.)
    elif scenario=="target_gap":bars["BTCUSDT"][3].update(open=110.,high=112.,low=109.,close=111.)
    elif scenario in ("terminal","last_bar_entry"):
        # Shift original event/response to the end; leave the rest flat.
        e,t=copy.deepcopy(bars["BTCUSDT"][0]),copy.deepcopy(bars["BTCUSDT"][1])
        for rows in bars.values():
            for j in (0,1):rows[j].update(open=101.,high=101.5,low=100.5,close=101.,imbalance=0.)
            event_index=469 if scenario=="terminal" else 471
            for j,source in ((event_index,e),(event_index+1,t)):
                for key in ("open","high","low","close","imbalance"):rows[j][key]=source[key]
    features=make(bars);result=reports(features)
    assert q.verify(features,result,contract)["verified"]
    checks.append({"case":scenario,"accepted":True})
features=make(p.fixture(474));original=reports(features)
mutations=[
    ("fill_cash",lambda r:r["books"]["candidate"]["conservative"]["fills"][0].__setitem__("cash_after",0)),
    ("fill_quantity_bool",lambda r:r["books"]["candidate"]["stress"]["fills"][0].__setitem__("quantity",True)),
    ("missing_cost",lambda r:r["books"]["candidate"].pop("severe")),
    ("passive_mark",lambda r:r["passive"]["stress"]["capped_50_50"]["marks"][0].__setitem__("equity",100)),
    ("entry_time",lambda r:r["books"]["candidate"]["conservative"]["fills"][0].__setitem__("execution_time_ms",0)),
    ("invented_month",lambda r:r["books"]["price_only"]["stress"]["monthly_pnl_usdt"].__setitem__("2030-01",1)),
    ("false_gate",lambda r:r.__setitem__("exploratory_pass",not r["exploratory_pass"])),
]
for name,alter in mutations:
    bad=copy.deepcopy(original);alter(bad)
    try:q.verify(features,bad,contract)
    except (ValueError,KeyError,AssertionError):checks.append({"case":name,"rejected":True})
    else:raise AssertionError("Independent QA accepted corruption: "+name)
swapped=copy.deepcopy(features)
for rows in swapped["bars"].values():
    for b in rows:
        for suffix in ("","_decimal"):
            a,z="buy_quote"+suffix,"sell_quote"+suffix;b[a],b[z]=b[z],b[a]
assert q.verify(swapped,original,contract)["verified"]
checks.append({"case":"global_side_swap","accepted":True})
receipt={"synthetic_only":True,"checks":checks,"count":len(checks),"passed":True,
 "producer_sha256":p.sha(sys.argv[1]),"independent_qa_sha256":p.sha(sys.argv[2]),
 "contract_sha256":p.sha(sys.argv[3]),"market_prices_read":False,"economic_backtest":False}
p.save(out,receipt);print(json.dumps(receipt))
