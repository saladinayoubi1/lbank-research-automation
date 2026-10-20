"""One allowlisted public ID-map probe; no quote/price/history/credentials."""
from pathlib import Path
from datetime import datetime, timezone
import argparse
import hashlib
import json
import sys
import urllib.request
import urllib.error

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from research.nexus_ctrend_intake_guard_v1 import preflight,check_response_metadata


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--report",type=Path,required=True)
    args=parser.parse_args()
    if args.report.exists():parser.error("Evidence path already exists")
    request=preflight("https://pro-api.coinmarketcap.com/public-api/v1/cryptocurrency/map?listing_status=active,inactive,untracked&sort=id&start=1&limit=5")
    report=dict(schema="nexus.ctrend-cmc-metadata-sample.v1",utc=datetime.now(timezone.utc).isoformat(),
        preflight=request,http_status=None,provider_error_code=None,source_authenticated=False,
        sample_received=False,complete_universe_certified=False,historical_vintage_certified=False,
        prices_requested=False,credentials_used=False,protected_future_data_read=False,
        financial_backtest=False,demo_admitted=False,live_enabled=False,real_orders=0)
    try:
        req=urllib.request.Request(request["canonical_url"],headers={"Accept":"application/json","User-Agent":"NEXUS-Metadata-Research/1.0"})
        with urllib.request.build_opener(NoRedirect()).open(req,timeout=20) as response:
            report["http_status"]=response.status;raw=response.read(1_000_001)
        if len(raw)>1_000_000:raise ValueError("Metadata sample exceeds bounded size")
        payload=json.loads(raw);check_response_metadata(payload)
        status=payload["status"]["error_code"];report["provider_error_code"]=status
        if type(status) is not int or status!=0:raise ValueError("Provider did not report success")
        rows=payload["data"]
        if not isinstance(rows,list) or len(rows)>5:raise ValueError("Unexpected sample shape")
        if any(not isinstance(row,dict) or type(row.get("id")) is not int or row["id"]<=0 for row in rows):
            raise ValueError("Invalid ID-map records")
        report.update(sample_received=True,raw_sha256=hashlib.sha256(raw).hexdigest(),raw_bytes=len(raw),
            sample=[{k:row.get(k) for k in ("id","name","symbol","is_active","first_historical_data","last_historical_data","platform")} for row in rows])
        # Record metadata bytes only after response inspection has passed.
        raw_path=args.report.with_suffix(".response.json")
        raw_path.parent.mkdir(parents=True,exist_ok=True)
        with raw_path.open("xb") as stream:stream.write(raw)
        report["raw_filename"]=raw_path.name
    except urllib.error.HTTPError as exc:
        report.update(http_status=exc.code,error="HTTP "+str(exc.code))
    except Exception as exc:
        report["error"]=type(exc).__name__+": "+str(exc)
    report["finished_at_utc"]=datetime.now(timezone.utc).isoformat()
    args.report.parent.mkdir(parents=True,exist_ok=True)
    with args.report.open("x",encoding="utf-8") as stream:json.dump(report,stream,indent=2);stream.write("\n")
    print(json.dumps(report))


if __name__=="__main__":main()
