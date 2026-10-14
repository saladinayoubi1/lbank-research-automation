import hashlib, importlib.util, json, os
from pathlib import Path
root=Path(__file__).resolve().parent
source=root/"scripts/repair_nexus_rdc_batch_return.py"
spec=importlib.util.spec_from_file_location("rdc_repair",source)
repair=importlib.util.module_from_spec(spec); spec.loader.exec_module(repair)
backup=Path(r"E:\NEXUS-QA\rdc-return-20261014T004546233872Z\remote-supervisor.cmd.before")
saved_receipt=json.loads((backup.parent/"receipt.json").read_text(encoding="utf-8"))
launcher=Path(r"C:\Users\afaq\AppData\Local\NEXUS-Research\remote-supervisor.cmd")
startup=Path(r"C:\Users\afaq\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\NEXUS-Remote-Autostart.cmd")
before=backup.read_bytes(); after=launcher.read_bytes()
checks={
    "physical_host":os.environ.get("COMPUTERNAME")=="DESKTOP-F4SA4VL",
    "helper_byte_binding":repair.digest(source.read_bytes())=="3f79acdc3ea2f4140f6bd167b17e0385215945b14c6d552b1fa8a47f0b426b27",
    "source_receipt_binding":saved_receipt["source_sha"]=="98112d355f6de5e2da3ef472a7eb8395e5813019",
    "original_backup_sha256":repair.digest(before)=="64ea0262d57f43d2c55ddc995c0d492f0edef8380f8e2c7fbcf5c6d770bf3c03",
    "patched_launcher_sha256":repair.digest(after)=="8e09cb51022e86fe672920a4e5c5b960fa83966f37c6872c4685a98acf2bfa12",
    "only_call_added":repair.corrected_bytes(before)==after,
    "patched_idempotent":repair.corrected_bytes(after)==after,
    "startup_unchanged":repair.digest(startup.read_bytes())=="0a4030bfc1fbbe7e8027850001f9498342278ec796a042d6ce82da3b298bafac",
    "receipt_matches_bytes":saved_receipt["before_sha256"]==repair.digest(before) and saved_receipt["after_sha256"]==repair.digest(after),
}
result={"schema":"nexus.rdc-return-native-readback.v1","source_sha":saved_receipt["source_sha"],"host":os.environ.get("COMPUTERNAME"),"checks":checks,"all_checks_pass":all(checks.values()),"backup":str(backup),"receipt":str(backup.parent/"receipt.json"),"launcher_lines":after.decode("ascii").splitlines(),"active_client_adopted":False,"applies_to_future_launcher_invocations":True}
(root/"NATIVE_VERIFICATION.json").write_bytes((json.dumps(result,sort_keys=True,indent=2)+"\n").encode())
print(json.dumps(result,sort_keys=True))
raise SystemExit(0 if result["all_checks_pass"] else 1)
