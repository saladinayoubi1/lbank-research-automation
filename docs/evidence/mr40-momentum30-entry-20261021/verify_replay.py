"""Verify exact frozen files and replay the single MR40 momentum30 experiment."""
from __future__ import annotations
import contextlib,hashlib,io,json,shutil,subprocess,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent
RESULT="959832aa111ba6bbab7a899547a7d4e031a0f3cd0a283de30397635f1ba5f118"
CODE="40b751d0b0466ef0ccc3ba4807a2e2ceeabbf147"
PREREG="df21c2657e8a8811035b55b463cf8e315bd3ab62"
def main():
    inventory=json.loads((ROOT/"INVENTORY.json").read_text(encoding="utf-8"))
    for item in inventory["files"]:
        raw=(ROOT/item["path"]).read_bytes()
        assert len(raw)==item["bytes"],item["path"]
        assert hashlib.sha256(raw).hexdigest()==item["sha256"],item["path"]
    test=subprocess.run([sys.executable,str(ROOT/"tests"/"test_nexus_mean_reversion_40_m2_momentum30_entry_v1.py"),"-v"],cwd=ROOT,capture_output=True,text=True)
    print(test.stdout,end="");print(test.stderr,end="")
    if test.returncode:raise RuntimeError("admission regression failure")
    sys.path.insert(0,str(ROOT/"research"))
    import nexus_mean_reversion_40_m2_momentum30_entry_v1 as study
    recorded=json.loads((ROOT/"recorded_results"/"results.json").read_text(encoding="utf-8"))
    assert recorded["result_digest"]==RESULT
    assert study.digest({k:v for k,v in recorded.items() if k!="result_digest"})==RESULT
    with tempfile.TemporaryDirectory(prefix="mr40-momentum30-") as directory:
        work=Path(directory);(work/"tests").mkdir()
        shutil.copyfile(ROOT/"study_contract.json",work/"study_contract.json")
        shutil.copyfile(ROOT/"tests"/"test_nexus_mean_reversion_40_m2_momentum30_entry_v1.py",work/"tests"/"test_nexus_mean_reversion_40_m2_momentum30_entry_v1.py")
        with contextlib.redirect_stdout(io.StringIO()):
            actual=study.run(work,ROOT/"baseline",CODE,PREREG)
        ignore={"executed_utc","physical_worker","result_digest"}
        assert {k:v for k,v in actual.items() if k not in ignore}=={k:v for k,v in recorded.items() if k not in ignore},"semantic replay mismatch"
        names=["summary.csv","fills.csv","closed_positions.csv","equity_curve.csv","monthly_attribution.csv","entry_admissions.csv"]
        for name in names:
            assert (work/"results"/name).read_bytes()==(ROOT/"recorded_results"/name).read_bytes(),name
    print(json.dumps({"inventory_members":len(inventory["files"]),"tests":14,"cases":24,"baseline_curve_replays":24,
                      "semantic_replay":"PASS","exact_csv_files":names,"recorded_digest":RESULT,"orders":0},sort_keys=True))
if __name__=="__main__":main()
