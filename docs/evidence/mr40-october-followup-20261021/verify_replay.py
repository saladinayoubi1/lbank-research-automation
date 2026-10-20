"""Offline verification of the frozen MR40 October historical follow-up."""
from __future__ import annotations
import contextlib,hashlib,io,json,shutil,subprocess,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent
CODE="5fec4eea4937d86ea38f92af413c49f25539ae86"
PROTOCOL="9372f82aa690232f42e7bc026799078e5f28e55d"
EXTENSION="17f3101579ebd301cda074174ed4154e772d15d6b2ef2e17513d73b1dc31798c"
RESULT="3209320f841a694f7711a365e93a0fd1e6777f31b1dd250c0c44f3ab630ca7ac"
def main():
    inventory=json.loads((ROOT/"INVENTORY.json").read_text(encoding="utf-8"))
    for item in inventory["files"]:
        raw=(ROOT/item["path"]).read_bytes()
        assert len(raw)==item["bytes"] and hashlib.sha256(raw).hexdigest()==item["sha256"],item["path"]
    test=subprocess.run([sys.executable,"-m","unittest","discover","-s",str(ROOT/"tests"),"-p","test_nexus_mr40_*.py","-v"],cwd=ROOT,capture_output=True,text=True)
    print(test.stdout,end="");print(test.stderr,end="")
    if test.returncode:raise RuntimeError("source/boundary regression failure")
    sys.path.insert(0,str(ROOT/"research"))
    import nexus_mr40_momentum30_october_followup_v1 as study
    old=json.loads((ROOT/"recorded_results"/"results.json").read_text(encoding="utf-8"))
    study.check_digest(old,"result_digest",RESULT)
    with tempfile.TemporaryDirectory(prefix="mr40-october-") as directory:
        work=Path(directory);(work/"scripts").mkdir()
        for name in ["study_contract.json","source_manifest.json","october_input_extension.json"]:
            shutil.copyfile(ROOT/name,work/name)
        name="nexus_mr40_october_followup_intake_v1.py"
        shutil.copyfile(ROOT/"scripts"/name,work/"scripts"/name)
        with contextlib.redirect_stdout(io.StringIO()):
            actual=study.run(work,ROOT/"frozen",CODE,PROTOCOL,EXTENSION)
        ignore={"created_utc","physical_worker","result_digest"}
        assert {k:v for k,v in actual.items() if k not in ignore}=={k:v for k,v in old.items() if k not in ignore},"semantic mismatch"
        names=["summary.csv","fills.csv","closed_positions.csv","equity_curve.csv","monthly_attribution.csv","entry_admissions.csv"]
        for name in names:
            assert (work/"results"/name).read_bytes()==(ROOT/"recorded_results"/name).read_bytes(),name
    print(json.dumps({"inventory_files":len(inventory["files"]),"new_tests":13,"calculations":16,"semantic_replay":"PASS",
                      "byte_equal_csv_files":names,"recorded_digest":RESULT,"orders":0},sort_keys=True))
if __name__=="__main__":main()
