"""Offline integrity check and exact replay of the single MR40 cap40 diagnostic."""
from __future__ import annotations
import contextlib,hashlib,io,json,shutil,subprocess,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent
EXPECTED_RESULT="c3fd7abbd94ed7a5e938fcbf001f9be144da10f0322c23437f7b43b4e3948a4e"
CODE="0bd7a1ede39aec7e7ef64b65b96cf4ba02b37555"
PREREG="7cd60d917f0bfbc1e0121ef35aa08f10c8da988f"
def main():
    inventory=json.loads((ROOT/"INVENTORY.json").read_text(encoding="utf-8"))
    for item in inventory["files"]:
        path=ROOT/item["path"];raw=path.read_bytes()
        assert len(raw)==item["bytes"],item["path"]
        assert hashlib.sha256(raw).hexdigest()==item["sha256"],item["path"]
    test=subprocess.run([sys.executable,str(ROOT/"tests"/"test_nexus_mean_reversion_40_m2_time_cap_v1.py"),"-v"],
                        cwd=ROOT,capture_output=True,text=True)
    print(test.stdout,end="");print(test.stderr,end="")
    if test.returncode:raise RuntimeError("regression failure")
    sys.path.insert(0,str(ROOT/"research"))
    import nexus_mean_reversion_40_m2_time_cap_v1 as candidate
    recorded=json.loads((ROOT/"recorded_results"/"results.json").read_text(encoding="utf-8"))
    assert recorded["result_digest"]==EXPECTED_RESULT
    assert candidate.digest({k:v for k,v in recorded.items() if k!="result_digest"})==EXPECTED_RESULT
    with tempfile.TemporaryDirectory(prefix="mr40-cap40-replay-") as directory:
        work=Path(directory);(work/"tests").mkdir()
        shutil.copyfile(ROOT/"study_contract.json",work/"study_contract.json")
        shutil.copyfile(ROOT/"tests"/"test_nexus_mean_reversion_40_m2_time_cap_v1.py",work/"tests"/"test_nexus_mean_reversion_40_m2_time_cap_v1.py")
        with contextlib.redirect_stdout(io.StringIO()):
            actual=candidate.run(work,ROOT/"baseline",CODE,PREREG)
        ignore={"executed_utc","physical_worker","result_digest"}
        assert {k:v for k,v in actual.items() if k not in ignore}=={k:v for k,v in recorded.items() if k not in ignore},"semantic result mismatch"
        names=["summary.csv","fills.csv","closed_positions.csv","equity_curve.csv","monthly_attribution.csv"]
        for name in names:
            assert (work/"results"/name).read_bytes()==(ROOT/"recorded_results"/name).read_bytes(),name
    result={"integrity_members":len(inventory["files"]),"cap_regressions":11,"replayed_cases":24,
            "semantic_results":"PASS","csv_byte_equality":names,"recorded_result_digest":EXPECTED_RESULT,
            "ignored_replay_metadata":sorted(ignore),"research_only":True,"orders":0}
    print(json.dumps(result,sort_keys=True))
if __name__=="__main__":main()
