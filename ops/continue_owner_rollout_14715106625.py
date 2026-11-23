"""One bounded continuation of the existing verified Windows release protocol.

Never manufacture runner context, reset an account, or admit a strategy. Only
an actual successful physical GitHub stage permits the frozen owner protocol.
"""
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import time
import urllib.parse

ROOT = Path(r"E:\NEXUS\NEXUS_OWNER_PAPER_PRIVATE")
SOURCE = "3c3461c4e39801232b64f1016cc48edc0ae6b0c5"
REPO = "saladinayoubi1/lbank-research-automation"
ARTIFACT = 14715106625
BUILD_RUN = 44924381327
TOTAL = 266113158
OUTER = "14fa846d65266c36f100d2fc1ae991b10767c4d5b25f117b64ae5adf50ed8f67"
INNER = "c777deafe75154f163ef0eed19e1526c051e40d6a3817cdf007d39305a2b478d"
WORKFLOW = "nexus-install-app-fastpath.yml"
GH = r"C:\Program Files\GitHub CLI\gh.exe"
RECEIPT = ROOT / "continue-owner-3c3461c4-20261123.json"
DOWNLOAD_RECEIPT = ROOT / "original-artifact-14715106625-resume.json"
ZIP = ROOT / "original-artifact-14715106625-resumed.zip"
DRIVER = ROOT / "ops_rollout_3c3461c4.ps1"
DRIVER_SHA = "2d9133af5319decb1dbb00f9ec936c933ca6b9db76352ca09671b720ca7e49d9"
JOURNAL = Path(r"E:\NEXUS-Applications\profiles\lbank-research-e3f11c53\product-data\product_runtime\paper-events.jsonl")
JOURNAL_SHA = "d7b5f4ffefa7ac14d21f51755c42659de72f8f3c0046c97e3a8b999e48310a98"


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(4 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def plain(path):
    if path.is_symlink() or path.is_junction():
        raise RuntimeError("Release path cannot be a reparse point")


def main():
    if os.name != "nt" or platform.node() != "DESKTOP-1R1081M":
        raise RuntimeError("Wrong physical owner host")
    import ctypes
    import msvcrt
    sid = ctypes.c_ulong()
    ctypes.windll.kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(sid))
    if sid.value <= 0 or ctypes.windll.shell32.IsUserAnAdmin():
        raise RuntimeError("Release continuation requires normal interactive owner")
    for path in (ROOT, RECEIPT, DRIVER, JOURNAL):
        plain(path)
    lock_path = RECEIPT.with_suffix(".lock")
    plain(lock_path)
    lock = lock_path.open("a+b")
    if lock.tell() == 0:
        lock.write(b"0")
        lock.flush()
    lock.seek(0)
    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    if RECEIPT.exists():
        raise RuntimeError("Existing continuation receipt: inspect postconditions; never redispatch blindly")
    env = os.environ.copy()
    env.pop("GH_DEBUG", None)
    env["GODEBUG"] = "http2client=0"
    state = {"source_sha": SOURCE, "artifact_id": ARTIFACT, "controller_pid": os.getpid(),
             "financial_writer_added": False, "live_trading_authority": False,
             "owner_activation_requested": False, "stage_run_id": None}

    def save(status, error=""):
        payload = dict(state, status=status, error=error,
                       updated_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        temp = RECEIPT.with_suffix(".json.tmp")
        plain(temp)
        with temp.open("w", encoding="utf-8") as f:
            json.dump(payload, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, RECEIPT)
        print(json.dumps({"phase": status, "stage_run_id": state["stage_run_id"]}), flush=True)

    def api(route):
        p = subprocess.run([GH, "api", route], capture_output=True, timeout=45, env=env)
        if p.returncode:
            raise RuntimeError("Bounded GitHub release metadata request failed")
        return json.loads(p.stdout)

    def exact_main():
        if api(f"repos/{REPO}/branches/main")["commit"]["sha"] != SOURCE:
            raise RuntimeError("Default source changed; frozen release remains closed")

    def runs():
        return api(f"repos/{REPO}/actions/workflows/{WORKFLOW}/runs?branch=main&event=workflow_dispatch&per_page=30")["workflow_runs"]

    try:
        save("WAITING_FOR_VERIFIED_DOWNLOAD")
        end = time.monotonic() + 1800
        while time.monotonic() < end:
            receipt = json.loads(DOWNLOAD_RECEIPT.read_text())
            if receipt.get("status") == "FAILED":
                raise RuntimeError("Artifact transfer failed; completed bytes retained")
            if receipt.get("status") == "VERIFIED":
                break
            time.sleep(10)
        else:
            raise RuntimeError("Bounded artifact wait expired; owner app preserved")
        if not (receipt["artifact_id"] == ARTIFACT and receipt["source_sha"] == SOURCE
                and receipt["expected_sha256"] == OUTER and receipt["expected_bytes"] == TOTAL
                and receipt["file"] == str(ZIP) and ZIP.stat().st_size == TOTAL
                and digest(ZIP) == OUTER):
            raise RuntimeError("Completed official artifact failed binding/byte validation")
        exact_main()
        build = api(f"repos/{REPO}/actions/runs/{BUILD_RUN}")
        if not (build["head_sha"] == SOURCE and build["status"] == "completed" and build["conclusion"] == "success"):
            raise RuntimeError("Official exact-source build is not successful")
        meta = api(f"repos/{REPO}/actions/artifacts/{ARTIFACT}")
        if not (meta["digest"] == "sha256:"+OUTER and meta["size_in_bytes"] == TOTAL
                and not meta["expired"] and meta["workflow_run"]["id"] == BUILD_RUN
                and meta["workflow_run"]["head_sha"] == SOURCE):
            raise RuntimeError("Current artifact metadata no longer matches frozen build")
        cache_root = Path(os.environ["LOCALAPPDATA"]) / "NEXUS" / "verified-outer-artifacts"
        plain(cache_root)
        cache_root.mkdir(exist_ok=True)
        cache = cache_root / f"nexus-artifact-{ARTIFACT}.zip"
        plain(cache)
        if cache.exists():
            if cache.stat().st_size != TOTAL or digest(cache) != OUTER:
                raise RuntimeError("Existing owner artifact cache does not match; preserved")
        else:
            if shutil.disk_usage(cache_root).free < 2_000_000_000:
                raise RuntimeError("Insufficient verified stage free space")
            incoming = cache.with_suffix(".incoming-20261123")
            plain(incoming)
            with incoming.open("xb") as dst, ZIP.open("rb") as src:
                shutil.copyfileobj(src, dst, 1024 * 1024)
                dst.flush()
                os.fsync(dst.fileno())
            if incoming.stat().st_size != TOTAL or digest(incoming) != OUTER:
                raise RuntimeError("Private cache copy failed exact bytes/SHA-256")
            os.rename(incoming, cache)  # Windows refuses to replace an existing cache.
        state["verified_outer_cache_published"] = True
        save("VERIFIED_CACHE_PUBLISHED")

        before = runs()
        active = [r for r in before if r["head_sha"] == SOURCE and r["status"] != "completed"]
        if len(active) > 1:
            raise RuntimeError("Multiple physical stages already pending; preserved")
        if active:
            run_id = active[0]["id"]
        else:
            previous_ids = {r["id"] for r in before}
            save("PHYSICAL_STAGE_DISPATCH_INTENDED")
            payload = {"ref": "main", "inputs": {"source_sha": SOURCE,
                "artifact_run_id": str(BUILD_RUN), "artifact_id": str(ARTIFACT),
                "archive_sha256": OUTER, "archive_bytes": str(TOTAL), "inner_sha256": INNER}}
            post = subprocess.run([GH, "api", "--method", "POST",
                f"repos/{REPO}/actions/workflows/{WORKFLOW}/dispatches", "--input", "-"],
                input=json.dumps(payload).encode(), capture_output=True, timeout=45, env=env)
            # Even a failed response can have dispatched. Never repeat this POST.
            candidates = []
            for _ in range(8):
                candidates = [r for r in runs() if r["id"] not in previous_ids and r["head_sha"] == SOURCE]
                if candidates:
                    break
                time.sleep(5)
            if len(candidates) != 1:
                raise RuntimeError("Physical stage dispatch unconfirmed; inspect GitHub before any new dispatch")
            run_id = candidates[0]["id"]
        state["stage_run_id"] = run_id
        save("WAITING_FOR_ACTUAL_PHYSICAL_STAGE")
        end = time.monotonic() + 3600
        while time.monotonic() < end:
            run = api(f"repos/{REPO}/actions/runs/{run_id}")
            if not (run["head_sha"] == SOURCE and run["path"] == ".github/workflows/"+WORKFLOW
                    and run["event"] == "workflow_dispatch"):
                raise RuntimeError("Observed stage has wrong actual source/workflow")
            if run["status"] == "completed":
                break
            time.sleep(20)
        else:
            raise RuntimeError("Actual Windows stage still pending; owner app unchanged")
        jobs = api(f"repos/{REPO}/actions/runs/{run_id}/jobs?per_page=100")["jobs"]
        installs = [j for j in jobs if j["name"] == "install"]
        if not (run["conclusion"] == "success" and len(installs) == 1
                and installs[0]["conclusion"] == "success"
                and installs[0]["runner_name"] == "NEXUS-LOCAL-RUNNER"):
            raise RuntimeError("Actual physical GitHub stage did not pass; owner app preserved")
        state["successful_physical_job_id"] = installs[0]["id"]
        exact_main()
        if digest(JOURNAL) != JOURNAL_SHA or digest(DRIVER) != DRIVER_SHA:
            raise RuntimeError("Original journal or frozen rollout driver changed; no activation")
        if (ROOT / "rollout-3c3461c4-status.json").exists():
            raise RuntimeError("Existing frozen rollout receipt requires inspection")
        save("ACTUAL_PHYSICAL_STAGE_PASSED")
        # The frozen protocol performs the full clone, current-main binding,
        # candidate rehearsal, read-only preflight and non-destructive cutover.
        state["owner_activation_requested"] = True
        save("RUNNING_FROZEN_OWNER_PROTOCOL")
        with (ROOT / "continuation-frozen-protocol-20261123.log").open("xb") as log:
            result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive",
                "-ExecutionPolicy", "Bypass", "-File", str(DRIVER)],
                stdout=log, stderr=subprocess.STDOUT, env=env)
        outcome = json.loads((ROOT / "rollout-3c3461c4-status.json").read_text())
        state["original_financial_journal_unchanged"] = digest(JOURNAL) == JOURNAL_SHA
        if not (result.returncode == 0 and outcome["status"] == "ACTIVATED_PENDING_VISUAL_CHECKS"
                and state["original_financial_journal_unchanged"]):
            raise RuntimeError("Frozen owner protocol failed closed; inspect its recovery receipt")
        save("ACTIVATED_PENDING_VISUAL_CHECKS")
    except Exception as e:
        save("FAILED_CLOSED", str(e) if isinstance(e, RuntimeError) else type(e).__name__)
        raise SystemExit(1) from None
    finally:
        lock.close()


if __name__ == "__main__":
    main()
