"""Bounded native runner; explicit one-shot invocation, no scheduler or network."""
import base64, hashlib, json, platform, subprocess, sys, time, zlib
from datetime import datetime, timezone
from pathlib import Path
root=Path(sys.argv[1]);out=root/"run";out.mkdir(exist_ok=True)
expected={"contract.json":"c791070d28a135d170d0cd719e3c951c6432aa7a",
 "producer.py":"f167fa79edae4a5d5564948d0ec88b48bfbc6bd9",
 "independent_qa.py":"c4afdef5942b0220674144f55fcbc8e4c4c1b765",
 "crosscheck.py":"e7d1e130b5e29e549dbdf8dcd6d9121e533b16fb"}
previous=(root/"native-status.json").read_bytes()
status=json.loads(previous)
if status["phase"]!="checkpointed_source_pending" or status.get("bounded_continuations",0):
    raise RuntimeError("Only one exact-source checkpoint continuation is allowed")
(root/"native-pre-resume.json").write_bytes(previous)
status["bounded_continuations"]=1
status["resume_started_utc"]=datetime.now(timezone.utc).isoformat()
def save_status(phase):
    status["phase"]=phase;status["updated_utc"]=datetime.now(timezone.utc).isoformat()
    (root/"native-status.json").write_text(json.dumps(status,indent=2)+"\n",encoding="utf-8")
def stage(name,args,timeout):
    save_status(name);start=time.monotonic()
    with (root/(name+".stdout.log")).open("w",encoding="utf-8") as stdout,(root/(name+".stderr.log")).open("w",encoding="utf-8") as stderr:
        proc=subprocess.run([sys.executable,*map(str,args)],stdout=stdout,stderr=stderr,timeout=timeout)
    status["stages"].append({"name":name,"exit_code":proc.returncode,"elapsed_seconds":time.monotonic()-start})
    if proc.returncode:raise RuntimeError(name+" failed")
try:
    save_status("source_hash_check")
    for filename,gitblob in expected.items():
        data=(root/filename).read_bytes()
        actual=hashlib.sha1(b"blob "+str(len(data)).encode()+b"\0"+data).hexdigest()
        status["source_hashes"][filename]={"git_blob":actual,"sha256":hashlib.sha256(data).hexdigest()}
        if actual!=gitblob:raise RuntimeError("Git blob mismatch: "+filename)
    stage("features_resume",[root/"producer.py","--phase","features","--contract",root/"contract.json",
      "--capture-root",r"E:\NEXUS-QA\bybit-spot-warmup-20261019\capture-results",
      "--output",out,"--budget-seconds","180"],300)
    if not (out/"features.json").exists():
        save_status("checkpointed_source_pending");sys.exit(0)
    stage("economic_replay",[root/"producer.py","--phase","replay","--contract",root/"contract.json","--output",out],45)
    stage("independent_financial_qa",[root/"independent_qa.py",root/"contract.json",out/"features.json",out/"result.json",out/"independent-qa.json"],90)
    result=json.loads((out/"result.json").read_text(encoding="utf-8"))
    qa=json.loads((out/"independent-qa.json").read_text(encoding="utf-8"))
    if qa["verified"] is not True:raise RuntimeError("QA not verified")
    stats=("net_pnl_usdt","fees_usdt","max_close_drawdown_fraction","closed_trades","mean_net_pnl_per_closed_trade","monthly_pnl_usdt")
    summary={k:v for k,v in result.items() if k not in ("books","passive")}
    summary["independent_financial_qa_ready"]=True
    summary["books"]={k:{c:{n:r[n] for n in stats if n in r} for c,r in v.items()} for k,v in result["books"].items()}
    summary["passive"]={c:{k:{n:r[n] for n in stats if n in r} for k,r in v.items()} for c,v in result["passive"].items()}
    summary["independent_qa"]=qa
    (out/"summary.json").write_text(json.dumps(summary,indent=2)+"\n",encoding="utf-8")
    save_status("completed_verified")
    names=["contract.json","synthetic-verification.json","native-status.json","unit_test.stdout.log","unit_test.stderr.log",
      "synthetic_crosscheck.stdout.log","synthetic_crosscheck.stderr.log","features.stdout.log","features.stderr.log",
      "economic_replay.stdout.log","economic_replay.stderr.log","independent_financial_qa.stdout.log","independent_financial_qa.stderr.log",
      "native-pre-resume.json","features_resume.stdout.log","features_resume.stderr.log","run/features.json","run/result.json","run/summary.json","run/independent-qa.json"]
    files={}
    for name in names:
        raw=(root/name).read_bytes()
        files[name]={"sha256":hashlib.sha256(raw).hexdigest(),"bytes":len(raw),"zlib_base64":base64.b64encode(zlib.compress(raw,9)).decode()}
    packet={"schema":"nexus.label-collapse-native-evidence-packet.v1","source_commit":status["source_commit"],
      "content_encoding":"Each files[name].zlib_base64 is zlib-compressed original bytes. Decode and verify sha256 before use.",
      "files":files}
    (root/"evidence-packet.json").write_text(json.dumps(packet,separators=(",",":"))+"\n",encoding="utf-8")
except BaseException as exc:
    if not isinstance(exc,SystemExit):
        status["error"]=str(exc);save_status("failed");raise
    raise
