"""Preserve the genuine physical proof before cleanup, then use the owner protocol."""
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import threading
import time
from datetime import datetime, timezone

ROOT = Path(r"E:\NEXUS\NEXUS_OWNER_PAPER_PRIVATE")
REPO = "saladinayoubi1/lbank-research-automation"
SOURCE = "3c3461c4e39801232b64f1016cc48edc0ae6b0c5"
RUN = 45183878518
ATTEMPT = 2
ARTIFACT = 14715106625
BUILD = 44924381327
INNER = "c777deafe75154f163ef0eed19e1526c051e40d6a3817cdf007d39305a2b478d"
GH = r"C:\Program Files\GitHub CLI\gh.exe"
DRIVER = ROOT / "ops_rollout_3c3461c4_fixed_20261123.ps1"
DRIVER_SHA = "23cf1117011e91ad045c346046b09ce7c3bf3f4c701ded70f067147fc2dc7e4b"
RECEIPT = ROOT / "continue-owner-3c3461c4-20261123-v2.json"
STAGE = Path(r"C:\Users\afaq\AppData\Local\NEXUS\actions-runner\_work\lbank-research-automation\lbank-research-automation\build\windows-app-install\evidence.json")
JOURNAL = Path(r"E:\NEXUS-Applications\profiles\lbank-research-e3f11c53\product-data\product_runtime\paper-events.jsonl")
JOURNAL_SHA = "d7b5f4ffefa7ac14d21f51755c42659de72f8f3c0046c97e3a8b999e48310a98"
HELPER_SHA = "26c35eed16d56ecd93f67664c7412ab18f36a0adb434008e1bd434fdb1007086"


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(4*1024*1024), b""):
            h.update(chunk)
    return h.hexdigest()


def plain(path):
    if path.is_symlink() or path.is_junction():
        raise RuntimeError("Reparse point cannot provide release evidence")


def stage_valid(a, not_before):
    """Accept only actual, fresh, successful stage-only evidence; never synthesize it."""
    try:
        generated = datetime.fromisoformat(a["generated_at"].replace("Z", "+00:00"))
        return (generated.tzinfo is not None and generated >= not_before
            and a["decision"] == "PASS" and a["source_sha"] == SOURCE
            and a["repository"] == REPO and a["artifact_id"] == ARTIFACT
            and a["artifact_run_id"] == BUILD and a["package"]["unpacked_sha256"] == INNER
            and a["package"]["checksum_manifest_verified"] is True
            and a["target"]["computer_name"] == "DESKTOP-1R1081M"
            and a["target"]["runner_name"] == "NEXUS-LOCAL-RUNNER"
            and a["target"]["owner_user_context"] is True
            and a["target"]["interactive_desktop"] is True and a["target"]["elevated"] is False
            and a["smoke"]["visible_window_observed"] is True
            and a["smoke"]["supervisor_healthy"] is True
            and a["smoke"]["live_trading_authority"] is False
            and a["smoke"]["live_orders_allowed"] is False
            and a["final_launch"]["activation_requested"] is False
            and a["final_launch"]["status"] == "STAGED_ONLY_OWNER_PRESERVED")
    except (KeyError, TypeError, ValueError):
        return False


def main():
    if os.name != "nt" or platform.node() != "DESKTOP-1R1081M":
        raise RuntimeError("Wrong physical owner host")
    import ctypes
    import msvcrt
    sid = ctypes.c_ulong()
    ctypes.windll.kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(sid))
    if sid.value <= 0 or ctypes.windll.shell32.IsUserAnAdmin():
        raise RuntimeError("Normal interactive owner required")
    for path in (ROOT, RECEIPT, DRIVER, JOURNAL, STAGE):
        plain(path)
    lock_path = RECEIPT.with_suffix(".lock")
    plain(lock_path)
    lock = lock_path.open("a+b")
    if lock.tell() == 0:
        lock.write(b"0"); lock.flush()
    lock.seek(0)
    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    if RECEIPT.exists():
        raise RuntimeError("Existing v2 receipt requires postcondition review; no repeated rerun")
    env = os.environ.copy()
    env.pop("GH_DEBUG", None)
    env["GODEBUG"] = "http2client=0"
    state = {"source_sha": SOURCE, "stage_run_id": RUN, "expected_attempt": ATTEMPT,
             "controller_pid": os.getpid(), "owner_activation_requested": False,
             "financial_writer_added": False, "live_trading_authority": False}
    stop = threading.Event()
    actual_attempt_running = threading.Event()
    captured = {}
    capture_lock = threading.Lock()

    def save(status, error=""):
        payload = dict(state, status=status, error=error, updated_utc=datetime.now(timezone.utc).isoformat())
        temp = RECEIPT.with_suffix(".json.tmp")
        plain(temp)
        with temp.open("w", encoding="utf-8") as f:
            json.dump(payload, f); f.flush(); os.fsync(f.fileno())
        os.replace(temp, RECEIPT)
        print(json.dumps({"phase": status, "run_id": RUN, "attempt": ATTEMPT}), flush=True)

    def api(route):
        for attempt in range(2):
            try:
                r = subprocess.run([GH, "api", route], capture_output=True, timeout=45, env=env)
                if r.returncode == 0:
                    return json.loads(r.stdout)
            except subprocess.TimeoutExpired:
                pass
            if attempt == 0:
                time.sleep(2)
        raise RuntimeError("GitHub evidence metadata request failed after one read retry")

    def exact_main():
        if api(f"repos/{REPO}/branches/main")["commit"]["sha"] != SOURCE:
            raise RuntimeError("Default source changed; no old-source activation")

    thread = None
    try:
        old = json.loads((ROOT / "continue-owner-3c3461c4-20261123.json").read_text())
        if old["status"] != "FAILED_CLOSED" or old["stage_run_id"] != RUN:
            raise RuntimeError("Prior continuation is not in the inspected failed state")
        if any((ROOT/name).exists() for name in ("rollout-3c3461c4-status.json", "rollout-3c3461c4-fixed-20261123-status.json")):
            raise RuntimeError("An owner-protocol receipt already exists; inspect before retry")
        preflight = json.loads((ROOT / "preflight-fixed-driver-20261123.json").read_text())
        if not (preflight["decision"] == "PASS_NATIVE_HASH_FUNCTION_AND_PARSE"
                and preflight["driver_sha256"] == DRIVER_SHA and digest(DRIVER) == DRIVER_SHA
                and digest(JOURNAL) == JOURNAL_SHA
                and digest(ROOT / "activation-helper-26c35eed.ps1") == HELPER_SHA):
            raise RuntimeError("Actual native hash/parse or frozen owner pins failed")
        exact_main()
        before = api(f"repos/{REPO}/actions/runs/{RUN}")
        if not (before["run_attempt"] == 1 and before["status"] == "completed"
                and before["conclusion"] == "success" and before["head_sha"] == SOURCE):
            raise RuntimeError("A later physical attempt already exists; never rerun blindly")
        not_before = datetime.now(timezone.utc)

        def capture():
            while not stop.is_set():
                try:
                    if actual_attempt_running.is_set() and STAGE.exists() and STAGE.stat().st_size < 2_000_000:
                        plain(STAGE)
                        raw = STAGE.read_bytes()
                        a = json.loads(raw.decode("utf-8-sig"))
                        if stage_valid(a, not_before):
                            sha = hashlib.sha256(raw).hexdigest()
                            target = ROOT / f"captured-stage-3c3461c4-{RUN}-attempt{ATTEMPT}-{sha}.json"
                            plain(target)
                            if not target.exists():
                                with target.open("xb") as f:
                                    f.write(raw); f.flush(); os.fsync(f.fileno())
                            if digest(target) != sha:
                                raise RuntimeError("Durable stage evidence changed")
                            with capture_lock:
                                captured.update(path=str(target), sha256=sha, generated_at=a["generated_at"])
                except (OSError, ValueError, RuntimeError):
                    pass  # A transient/incomplete file is never turned into a PASS.
                stop.wait(1)

        thread = threading.Thread(target=capture, daemon=True)
        thread.start()
        save("DURABLE_STAGE_CAPTURE_ARMED")
        state["rerun_requested"] = True
        save("PHYSICAL_ATTEMPT_2_REQUESTED")
        # Exactly one POST; a failed response still requires checking actual state.
        try:
            response = subprocess.run([GH, "api", "--method", "POST", f"repos/{REPO}/actions/runs/{RUN}/rerun"],
                           capture_output=True, timeout=45, env=env)
            state["rerun_response_exit_code"] = response.returncode
        except subprocess.TimeoutExpired:
            state["rerun_response_unconfirmed"] = True
        end = time.monotonic() + 3600
        confirm_end = time.monotonic() + 90
        observed_attempt = False
        while time.monotonic() < end:
            run = api(f"repos/{REPO}/actions/runs/{RUN}")
            if run["head_sha"] != SOURCE or run["run_attempt"] > ATTEMPT:
                raise RuntimeError("Actual rerun source/attempt changed unexpectedly")
            observed_attempt = observed_attempt or run["run_attempt"] == ATTEMPT
            if observed_attempt and run["status"] == "in_progress":
                actual_attempt_running.set()
            if not observed_attempt and time.monotonic() >= confirm_end:
                raise RuntimeError("Second stage attempt is unconfirmed; inspect before any new POST")
            if observed_attempt and run["status"] == "completed":
                break
            with capture_lock:
                state["captured_stage_proof"] = dict(captured) or None
            save("WAITING_FOR_ACTUAL_ATTEMPT_2")
            stop.wait(15)
        else:
            raise RuntimeError("Bounded physical-stage wait expired; old owner preserved")
        jobs = api(f"repos/{REPO}/actions/runs/{RUN}/attempts/{ATTEMPT}/jobs?per_page=100")["jobs"]
        install = [j for j in jobs if j["name"] == "install"]
        if not (run["conclusion"] == "success" and len(install) == 1
                and install[0]["conclusion"] == "success" and install[0]["runner_name"] == "NEXUS-LOCAL-RUNNER"):
            raise RuntimeError("Actual second Windows stage did not pass")
        with capture_lock:
            proof = dict(captured)
        if not proof or digest(Path(proof["path"])) != proof["sha256"]:
            raise RuntimeError("No original durable physical proof; no owner activation")
        if not stage_valid(json.loads(Path(proof["path"]).read_text(encoding="utf-8-sig")), not_before):
            raise RuntimeError("Captured physical proof binding failed")
        stop.set(); thread.join(timeout=3)
        exact_main()
        if digest(JOURNAL) != JOURNAL_SHA or digest(DRIVER) != DRIVER_SHA:
            raise RuntimeError("Owner journal or corrected wrapper changed")
        state.update(successful_physical_job_id=install[0]["id"], captured_stage_proof=proof)
        save("ACTUAL_ATTEMPT_2_PASSED_WITH_ORIGINAL_PROOF")
        state["owner_activation_requested"] = True
        save("RUNNING_EXISTING_OWNER_PROTOCOL_WITH_CORRECTED_WRAPPER")
        powershell = str(Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe")
        with (ROOT / "continuation-corrected-protocol-20261123.log").open("xb") as log:
            result = subprocess.run([powershell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                "-File", str(DRIVER), "-InputStageProof", proof["path"],
                "-ExpectedInputStageProofSha256", proof["sha256"]], stdout=log, stderr=subprocess.STDOUT, env=env)
        state["owner_protocol_exit_code"] = result.returncode
        outcome_path = ROOT / "rollout-3c3461c4-fixed-20261123-status.json"
        outcome = json.loads(outcome_path.read_text()) if outcome_path.exists() else {}
        state["original_financial_journal_unchanged"] = digest(JOURNAL) == JOURNAL_SHA
        if not (result.returncode == 0 and outcome.get("status") == "ACTIVATED_PENDING_VISUAL_CHECKS"
                and state["original_financial_journal_unchanged"]):
            raise RuntimeError("Owner protocol stopped; inspect corrected status and recovery log")
        save("ACTIVATED_PENDING_VISUAL_CHECKS")
    except Exception as e:
        save("FAILED_CLOSED", str(e) if isinstance(e, RuntimeError) else type(e).__name__)
        raise SystemExit(1) from None
    finally:
        stop.set()
        if thread:
            thread.join(timeout=3)
        lock.close()


if __name__ == "__main__":
    main()
