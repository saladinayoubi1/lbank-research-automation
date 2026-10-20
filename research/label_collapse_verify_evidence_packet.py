"""Validate native evidence bytes and full output identity, without replaying prices."""
import base64, hashlib, json, math, sys, zlib
from pathlib import Path
root=Path(sys.argv[1]);data=(root/"evidence-packet.json").read_bytes();packet=json.loads(data)
decoded={}
for name,item in packet["files"].items():
    raw=zlib.decompress(base64.b64decode(item["zlib_base64"],validate=True))
    assert len(raw)==item["bytes"] and hashlib.sha256(raw).hexdigest()==item["sha256"],name
    assert (root/name).read_bytes()==raw,name
    decoded[name]=raw
def obj(name):return json.loads(decoded[name])
def canonical_digest(x):
    return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()
f,r,q,s=obj("run/features.json"),obj("run/result.json"),obj("run/independent-qa.json"),obj("run/summary.json")
for value in (f,r):
    assert value["digest"]==canonical_digest({k:v for k,v in value.items() if k!="digest"})
assert f["raw_trade_rows"]==70815420 and f["verified_bars"]==948 and f["all_raw_decimal_checked"] is True
assert q["verified"] is True and q["reports_checked"]==21 and q["bars_checked"]==948
assert q["decision_gates"]==r["decision_gates"] and q["exploratory_pass"] is r["exploratory_pass"]
assert r["features_digest"]==f["digest"] and r["inputs"]==f["inputs"]==s["inputs"]
assert s["independent_financial_qa_ready"] is True and s["independent_qa"]==q
assert r["paper_eligible"] is False and r["live_enabled"] is False and type(r["orders"]) is int and r["orders"]==0
assert r["protected_prices_read"] is False and f["protected_prices_read"] is False and f["downloads"]==0
assert all(b["last_trade_ms"]<1792368000000 for rows in f["bars"].values() for b in rows)
mean_checked=0
for costs in r["books"].values():
    for report in costs.values():
        n=report["closed_trades"];mean=report["mean_net_pnl_per_closed_trade"]
        assert (mean is None if n==0 else math.isclose(mean,report["net_pnl_usdt"]/n,abs_tol=1e-9))
        assert math.isclose(sum(report["monthly_pnl_usdt"].values()),report["net_pnl_usdt"],abs_tol=1e-7)
        mean_checked+=1
native=obj("native-status.json")
assert native["phase"]=="completed_verified" and all(x["exit_code"]==0 for x in native["stages"])
for filename,expected in native["source_hashes"].items():
    raw=(root/filename).read_bytes()
    assert hashlib.sha256(raw).hexdigest()==expected["sha256"],filename
receipt={"schema":"nexus.label-collapse-evidence-packet-validation.v1","verified":True,
 "packet_bytes":len(data),"packet_sha256":hashlib.sha256(data).hexdigest(),
 "packet_git_blob":hashlib.sha1(b"blob "+str(len(data)).encode()+b"\0"+data).hexdigest(),
 "entries_checked":len(decoded),"raw_trade_rows":70815420,"verified_bars":948,"financial_reports":21,
 "close_marks_verified":21*474,"mean_pnl_reports_checked":mean_checked,
 "features_digest":f["digest"],"result_digest":r["digest"],
 "outcome":r["outcome"],"paper_eligible":False,"live_enabled":False,"orders":0,"protected_prices_read":False,
 "post_execution_source_hashes_match":True}
(root/"packet-validation.json").write_text(json.dumps(receipt,indent=2)+"\n",encoding="utf-8")
print(json.dumps(receipt))
