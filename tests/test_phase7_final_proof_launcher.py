from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PS = ROOT / "scripts" / "phase7_final_proof.ps1"
CMD = ROOT / "NEXUS_PHASE7_FINAL_PROOF.cmd"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_final_proof_launcher_reuses_canonical_offline_helper_and_has_no_daemon_or_watchdog():
    text = read(PS)
    for marker in (
        "phase7_offline_laptop.ps1",
        "PrepareOnline",
        "ExecuteOffline",
        "SubmitReturn",
        "NEXUS_PHASE7_FINAL_PROOF=SUCCESS",
        "DISCONNECT_INTERNET_AND_REBOOT",
        "RECONNECT_INTERNET",
    ):
        assert marker in text
    lowered = text.lower()
    assert "register-scheduledtask" not in lowered
    assert "new-scheduledtask" not in lowered
    assert "create service" not in lowered
    assert "self-heal" not in lowered
    assert "runner registration" not in lowered


def test_final_proof_launcher_fast_forwards_clean_main_without_destructive_reset():
    text = read(PS)
    for marker in (
        "status','--porcelain=v1','--untracked-files=no'",
        "fetch','origin','main','--quiet'",
        "merge-base','--is-ancestor'",
        "merge','--ff-only','origin/main'",
        "managed repository has tracked local changes; nothing was overwritten",
    ):
        assert marker in text
    assert "reset','--hard" not in text
    assert "git clean" not in text.lower()


def test_final_proof_launcher_avoids_broken_cim_for_boot_time_only():
    text = read(PS)
    assert "GetTickCount64" in text
    assert "NexusPhase7Kernel32" in text
    assert "function global:Get-CimInstance" in text
    assert "Win32_OperatingSystem" in text
    assert "CIM compatibility shim only permits Win32_OperatingSystem" in text
    assert "Remove-Item Function:\\Get-CimInstance" in text


def test_final_proof_launcher_preserves_offline_acceptance_sequence():
    text = read(PS)
    prepare_pos = text.index("Invoke-Helper 'PrepareOnline'")
    reboot_pos = text.index("DISCONNECT_INTERNET_AND_REBOOT")
    execute_pos = text.index("Invoke-ExecuteOfflineCimIndependent")
    reconnect_pos = text.index("RECONNECT_INTERNET")
    submit_pos = text.index("Invoke-Helper 'SubmitReturn'")
    assert prepare_pos < reboot_pos
    assert execute_pos < reconnect_pos
    assert submit_pos > reconnect_pos
    assert "Test-TcpTarget 'api.github.com' 443" in text
    assert "Test-TcpTarget '1.1.1.1' 443" in text


def test_root_cmd_runs_same_next_step_launcher_without_installing_background_components():
    text = read(CMD)
    assert 'scripts\\phase7_final_proof.ps1" -Mode Next' in text
    assert "run this same file again" in text
    assert "No watchdog, service, runner registration" in text
    lowered = text.lower()
    assert "schtasks" not in lowered
    assert "sc.exe" not in lowered
