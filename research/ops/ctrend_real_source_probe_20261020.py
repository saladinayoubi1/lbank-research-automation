"""Metadata-only source probe. No tickers, candles, returns, or exchange credentials."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,time,urllib.request,urllib.error,os
root=Path(r"E:\NEXUS-QA\ctrend-causal-full-20261020")
root.mkdir(parents=True,exist_ok=True)
url="https://api.bybit.com/v5/market/instruments-info?category=spot"
report={"schema":"nexus.ctrend-causal-real-source-probe.v1","scope":"current_instrument_metadata_only","url":url,"started_at_utc":datetime.now(timezone.utc).isoformat(),"protected_prices_requested":False,"market_prices_requested":False,"credentials_used":False,"historical_availability_proven":False}
try:
    request=urllib.request.Request(url,headers={"User-Agent":"NEXUS-Research-Metadata/1.0","Accept":"application/json"})
    with urllib.request.urlopen(request,timeout=20) as response:
        raw=response.read(8_000_001)
        report["http_status"]=response.status
    if len(raw)>8_000_000:raise ValueError("Metadata response exceeds bounded size")
    data=json.loads(raw)
    if data.get("retCode")!=0:raise ValueError("Nonzero Bybit retCode")
    rows=data["result"]["list"]
    forbidden={"lastPrice","markPrice","indexPrice","bid1Price","ask1Price","turnover24h","volume24h"}
    def clean(value):
        if isinstance(value,dict):
            if forbidden & set(value):raise ValueError("Unexpected market values in metadata endpoint")
            for item in value.values():clean(item)
        elif isinstance(value,list):
            for item in value:clean(item)
    clean(data)
    path=root/"bybit-current-instruments-spot.json"
    path.write_bytes(raw)
    filtered=[{"symbol":r["symbol"],"baseCoin":r["baseCoin"],"quoteCoin":r["quoteCoin"],"status":r["status"],"lotSizeFilter":r.get("lotSizeFilter"),"priceFilter":r.get("priceFilter"),"riskParameters":r.get("riskParameters")} for r in rows if r.get("quoteCoin")=="USDT" and r.get("status")=="Trading"]
    projection=root/"bybit-current-usdt-metadata.json"
    projection.write_text(json.dumps({"scope":"current_only_not_historical","observed_at_utc":datetime.now(timezone.utc).isoformat(),"rows":filtered},indent=2)+"\n",encoding="utf-8")
    report.update(status="CURRENT_METADATA_OBSERVED",raw_sha256=hashlib.sha256(raw).hexdigest(),raw_bytes=len(raw),instrument_count=len(rows),current_trading_usdt_count=len(filtered),server_time_ms=data.get("time"),raw_filename=path.name,projection_filename=projection.name)
except Exception as exc:
    report["status"]="SOURCE_METADATA_UNAVAILABLE"
    report["error"]=type(exc).__name__+": "+str(exc)
names={"close_cmc.csv","low_cmc.csv","high_cmc.csv","open_cmc.csv","market_cap_cmc.csv","volume_cmc.csv","MetaData.mat"}
matches=[]
for folder in (Path(r"E:\NEXUS-QA"),Path(r"F:\NEXUS-Tools\ChatCLI")):
    if not folder.is_dir():continue
    for current,dirs,files in os.walk(folder):
        dirs[:]=[d for d in dirs if d.lower() not in {"venv",".venv","node_modules","site-packages","lib","__pycache__", ".git"}]
        for name in files:
            if name in names:
                p=Path(current)/name
                matches.append({"path":str(p),"bytes":p.stat().st_size})
report["exact_raw_filenames_searched"]=sorted(names)
report["filename_inventory_only"]=matches
report["finished_at_utc"]=datetime.now(timezone.utc).isoformat()
(root/"real-source-probe.json").write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
print(json.dumps(report))
