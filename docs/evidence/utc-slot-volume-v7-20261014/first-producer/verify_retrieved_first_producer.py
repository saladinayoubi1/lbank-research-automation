"""Verify retained native producer bytes/contracts; performs no market replay or tests."""
import hashlib, json, math, sys
from pathlib import Path

SOURCE="7cab4f0368823ef3dd9dec79f572bd05721e2316"
DATASET="2455a725886d81adaec9d3478e8f3b2daaba6c0c9645a691e71737eb64f67422"
PRIOR="18675234ad8c981be8f8c5e348c1a39737a9c3fc4ca09ba0ae9532c8a59b567a"
FP="424c0a527aca815448719704c5aa714246e1b1e4c62532dcb782350b1c5090be"
EXPECTED_RAW={
("BTCUSDT","hour1"):"f8f2236785c036fe40808809397d47729b3add4c8f0b9e19c77d3b771f8e6847",
("BTCUSDT","hour4"):"e0d019a76882a02dc463a34d1d9375841f81d412b9a3310d9e21c2d7b2738dc6",
("BTCUSDT","minute15"):"c3afe92899dda8fe52937c955323cc8e04bf8f200a68eb8651e55d6020981226",
("ETHUSDT","hour1"):"ba0743588c5089e6a6b250b4ebb029a43fea57d0a020df5ab1316c34efdcd88a",
("ETHUSDT","hour4"):"292005e091d914fbb9d108c3d8d65e93785cc32b9c73e07ea02e0d44cf7da65b",
("ETHUSDT","minute15"):"ce603440650d0022b1a17a7922da743a3b6219ba9afd89ad4362b70fbe3bbfa1",
}
def sha(raw):
    return hashlib.sha256(raw).hexdigest()
def digest(obj):
    return sha(json.dumps(obj,sort_keys=True,separators=(",",":"),allow_nan=False).encode())
def check(value, reason):
    if not value:
        raise ValueError(reason)
def verify(root):
    raw=lambda name:(root/name).read_bytes()
    load=lambda name:json.loads(raw(name))
    manifest=load("native-byte-manifest.json")
    check(manifest["host"]=="DESKTOP-F4SA4VL","Wrong native host")
    check(len(manifest["files"])==13,"Missing native proof files")
    file_map={}
    for item in manifest["files"]:
        data=raw(item["path"])
        check(len(data)==item["bytes"] and sha(data)==item["sha256"],
              "Native byte mismatch: "+item["path"])
        file_map[item["path"]]=item["sha256"]
    check(len(file_map)==13,"Duplicate native proof files")
    fixture=manifest["reference_terminal_fixture"]
    old_raw=raw(fixture["path"])
    check(sha(old_raw)==fixture["sha256"]==
          "061f09f5797c76ab110c99beddb7dab87459bdf08bd9e17b1677c8aeeb1088c1",
          "Reference terminal fixture bytes differ")
    check(hashlib.sha1(b"blob "+str(len(old_raw)).encode()+b"\0"+old_raw).hexdigest()
          ==fixture["git_blob_sha1"]=="9d3f376bc4be787db7b0fa0cd5ee793197b55e70",
          "Reference Git blob differs")
    previous=json.loads(old_raw)
    receipt=load("producer-receipt.json")
    report=load("producer/research-report.json")
    ledger=load("producer/novelty-ledger.json")
    binding=load("producer-input-binding.json")
    summary=load("producer-result-summary.json")
    status=load("producer-status.json")
    command=load("producer-command.json")
    for obj,key in ((receipt,"receipt_digest"),(report,"report_digest"),
                    (ledger,"ledger_digest"),(previous,"ledger_digest")):
        check(digest({k:v for k,v in obj.items() if k!=key})==obj[key],
              "Canonical digest differs: "+key)
    check(previous["ledger_digest"]==binding["previous_ledger_digest"]==PRIOR,
          "Wrong predecessor")
    check(sha(old_raw.replace(b"\r\n",b"\n").replace(b"\n",b"\r\n"))==
          binding["previous_ledger_file_sha256"]==
          "937741211cfccbbcd2a278f7b501679cb82c1caae10801fd419127dcb10c395f",
          "Native predecessor CRLF byte binding differs")
    links={"report_file_sha256":"producer/research-report.json",
           "ledger_file_sha256":"producer/novelty-ledger.json",
           "input_binding_sha256":"producer-input-binding.json",
           "result_summary_sha256":"producer-result-summary.json",
           "command_file_sha256":"producer-command.json",
           "wrapper_sha256":"run-v7-first-producer.py",
           "stdout_sha256":"producer.stdout.log",
           "stderr_sha256":"producer.stderr.log"}
    for key,name in links.items():
        check(receipt[key]==file_map[name],"Receipt link differs: "+key)
    check(command["wrapper_sha256"]==receipt["wrapper_sha256"] and
          command["precheck_sha256"]==file_map["V7_PRODUCER_PRECHECK.md"],
          "Command/precheck binding differs")
    check(status["receipt_sha256"]==file_map["producer-receipt.json"],
          "Terminal status receipt link differs")
    check(status["status"]=="COMPLETE_RESEARCH_NOT_QUALIFIED" and
          status["child_exit_code"]==receipt["true_child_exit_code"]==0 and
          raw("producer-exit.txt")==b"0","True native exit/status differs")
    check(receipt["diagnostic_rows"]==12 and receipt["training_screen_cells"]==4
          and receipt["parameter_configurations"]==1,"Wrong bounded cell count")
    for obj in (receipt,report,summary,status):
        check(obj["source_sha"]==SOURCE and obj["research_only"] is True
              and obj["live_enabled"] is False and obj["auto_demo_promotion"] is False,
              "Source or authority differs")
    check(report["historical_test_pristine"] is False and
          receipt["independent_strategy_qa_complete"] is False and
          receipt["owner_demo_admission"] is False,"Unexpected qualification")
    check(report["archive_sha256"]==binding["archive_semantic_sha256"]==DATASET,
          "Semantic archive identity differs")
    check(binding["delivery_zip_byte_sha256"]==
          "d284a49f1b6e8951763cf225992a52a620289b2baf10815247d8626045763cec",
          "Representation-sensitive ZIP identity differs")
    check({(r["symbol"],r["timeframe"]):r["raw_file_sha256"]
           for r in binding["raw_inputs"]}==EXPECTED_RAW,
          "Six raw input bindings differ")
    check(report["selected"]==binding["candidate_config"] and
          report["selected"]["fingerprint"]==FP,"Frozen config differs")
    candidate=report["selected"]["mechanism"]
    check(candidate=="factory_utc_slot_volume_breakout","Wrong mechanism")
    screen=report["frontier_screening"]
    check(screen["candidate_count"]==1 and screen["selected_mechanism"]==candidate
          and screen["screened_mechanisms"]==[candidate] and
          screen["validation_used_for_selection"] is False and
          screen["historically_inspected_test_used_for_selection"] is False,
          "Training-only routing differs")
    check(ledger["config_fingerprints_evaluated"]==
          previous["config_fingerprints_evaluated"]+[FP],"Predecessor configs reset")
    check(ledger["mechanisms_evaluated"]==
          sorted(set(previous["mechanisms_evaluated"]+[candidate])),
          "Predecessor evaluated mechanisms changed")
    check(ledger["frontier_screened_mechanisms"]==
          sorted(set(previous["frontier_screened_mechanisms"]+[candidate])),
          "Predecessor screened mechanisms changed")
    check(receipt["ledger_digest"]==report["ledger_digest"]==ledger["ledger_digest"],
          "Ledger digest links differ")
    check(receipt["report_digest"]==summary["report_digest"]==report["report_digest"],
          "Report digest links differ")
    required={(s,p,c) for s in ("BTCUSDT","ETHUSDT")
              for p in ("train","validation","historically_inspected_test")
              for c in ("conservative","stress")}
    rows=report["rows"]
    check(len(rows)==12 and {(r["symbol"],r["part"],r["profile"]) for r in rows}==required,
          "Fixed diagnostic grid differs")
    for row in rows:
        check((row["fee_bps"],row["slippage_bps"])==
              ((10.0,5.0) if row["profile"]=="conservative" else (25.0,15.0)),
              "Frozen cost assumptions differ")
        check(row["config_fingerprint"]==FP and row["risk_variant"]==0,
              "Diagnostic config changed")
        check(math.isfinite(row["net_pnl_usdt"]) and math.isfinite(row["net_return_pct"]),
              "Nonfinite diagnostic PNL")
        derived=next(r for r in summary["rows"] if
                     (r["symbol"],r["part"],r["profile"])==
                     (row["symbol"],row["part"],row["profile"]))
        check(derived["net_pnl_usdt"]==row["net_pnl_usdt"] and
              derived["closed_round_trips"]==row["closed_round_trips"],
              "Summary cell differs")
        mean=round(row["net_pnl_usdt"]/row["closed_round_trips"],8) \
             if row["closed_round_trips"] else None
        check(mean==derived["mean_closed_trade_pnl_usdt"],"Summary mean differs")
    cells=screen["ranking"][0]["cells"]
    check(len(cells)==4,"Wrong Training-screen count")
    for cell in cells:
        row=next(r for r in rows if r["part"]=="train" and
                 r["symbol"]==cell["symbol"] and r["profile"]==cell["profile"])
        for metric in ("bars","closed_round_trips","net_return_pct","max_drawdown_pct",
                       "profit_factor","win_rate_pct"):
            check(row[metric]==cell[metric],"Repeated Training metric differs")
    compile(raw("run-v7-first-producer.py"),"native-run-v7-first-producer.py","exec")
    result=dict(schema="nexus.v7-first-producer-retrieved-proof-verification.v1",
                passed=True,source_sha=SOURCE,native_file_count=13,
                native_receipt_sha256=file_map["producer-receipt.json"],
                report_digest=report["report_digest"],ledger_digest=ledger["ledger_digest"],
                diagnostic_rows=12,training_screen_cells=4,
                diagnostic_positive_cells=sum(r["net_return_pct"]>0 for r in rows),
                all_diagnostic_cells_negative=all(r["net_return_pct"]<0 for r in rows),
                native_exit_code=receipt["true_child_exit_code"],
                byte_digests_and_schema_only=True,
                market_backtests_rerun=0,unit_tests_rerun=0,
                independent_numeric_or_decimal_qa=False,
                owner_demo_admission=False,research_only=True,live_enabled=False)
    return result

if __name__=="__main__":
    root=Path(sys.argv[1]) if len(sys.argv)>1 else Path(__file__).resolve().parent
    result=verify(root)
    (root/"retrieved-proof-verification.json").write_text(
        json.dumps(result,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(result,sort_keys=True))
