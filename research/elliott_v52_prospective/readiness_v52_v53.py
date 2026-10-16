"""V52/V53 real checkout readiness and historical source embargo receipt.

Runs once and exits. Does NOT schedule tasks, fetch public trades or call
Bybit APIs, create positions, mutate Demo or assert future data availability.
"""
import json,hashlib,sys
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path(r"E:\NEXUS-QA\elliott-v52-frozen-prospective-20261016")
REPO=Path(r"E:\NEXUS-QA\elliott-v14-quality-20261015")
for piece in ("",r"research\elliott_v40_nested_proof",r"research\elliott_v49_fixed_child",
             r"research\elliott_v50_fixed_degree",r"research\elliott_v52_prospective",
             r"research\elliott_v53_prospective_scan"):
    sys.path.insert(0,str(REPO/piece))
from prospective_v52 import (
    read_frozen_protocol,validate_scoring_event_time,
    verify_official_day_source,ProspectiveGateError,PROTOCOL_SHA256,
    SCORE_START,SOURCE_START,
)
from scan_verified_v53 import scan_verified_complete_days
from prospective_v52 import VerifiedDay

now=datetime.now(timezone.utc)
spec=read_frozen_protocol()
legacy=json.loads(Path(r"E:\NEXUS-QA\elliott-v33-oct01-14-v2-20261016\OFFICIAL_SOURCE_MANIFEST.json").read_text(encoding="utf8"))
btc=next(x for x in legacy["sources"] if x["date_utc"]=="2026-10-08" and x["symbol"]=="BTCUSDT")
prior=json.loads(Path(r"E:\NEXUS-QA\elliott-v45-source1m-oct08-12-20261016\PROVENANCE_RECEIPT.json").read_text(encoding="utf8"))
oldone=next(x for x in prior["pairs"] if x["symbol"]=="BTCUSDT")
denials={}
try:
    verify_official_day_source("BTCUSDT","2026-10-08T00:00:00Z",btc["path"],
       btc["sha256"],oldone["parquet_path"],oldone["parquet_sha256"])
except ProspectiveGateError as e:denials["oct08_historical_official_source"]=str(e)
else:raise RuntimeError("Historical market leakage allowed")
try:
    validate_scoring_event_time("2026-10-16T12:00:00Z",
      first_parent_confirmed_close_utc="2026-10-16T11:45:00Z")
except ProspectiveGateError as e:denials["oct16_unscored_market_event"]=str(e)
else:raise RuntimeError("Unscored warmup event admitted")
old_proof=VerifiedDay("BTCUSDT","2026-10-08",4472750,7200,3150,7200,
                     btc["sha256"],oldone["parquet_sha256"])
try:
    scan_verified_complete_days("BTCUSDT",((old_proof,Path(oldone["parquet_path"])),),
                                decision_close_utc="2026-10-18T00:00:00Z")
except ProspectiveGateError as e:denials["oct08_old_minute_archive_in_future_scanner"]=str(e)
else:raise RuntimeError("Historical 1m leaked into future scanner")
status="FIRST_COMPLETE_ARCHIVE_DATE_NOT_REACHED" if now<datetime(2026,10,17,tzinfo=timezone.utc) else "NO_CURRENT_SOURCE_AUDITED_BY_THIS_RUN"
receipt={"schema":"nexus.elliott-v52-v53-readiness.v1",
 "evaluated_utc":now.isoformat(),
 "frozen_protocol_sha256":PROTOCOL_SHA256,
 "registered_score_start_utc":SCORE_START.isoformat(),
 "source_capture_start_utc":SOURCE_START.isoformat(),
 "legacy_source_denials":denials,
 "physical_prospective_source_days_verified_this_run":0,
 "scored_prospective_wave_candidates_this_run":0,
 "new_realized_pnl":None,"research_only":True,"paper_eligible":False,"live_enabled":False,
 "entry_signal":False,"state":status}
out=ROOT/"V52_V53_READINESS_20261016.json"
if out.exists():raise RuntimeError("do not overwrite prior audit receipt")
out.write_text(json.dumps(receipt,indent=2,ensure_ascii=False)+"\n",encoding="utf8")
print(json.dumps(receipt,indent=2,ensure_ascii=False),flush=True)
print("RECEIPT_SHA256 "+hashlib.sha256(out.read_bytes()).hexdigest(),flush=True)
