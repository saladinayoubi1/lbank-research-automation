from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
WINDOWS_RUNS_ON = re.compile(r"^\s*runs-on:\s*\[(?=[^\]]*self-hosted)(?=[^\]]*Windows)[^\]]+\]\s*$", re.MULTILINE)

EXPECTED_ROUTES = {
    "nexus-bybit-wsl-fix-validation.yml": "nexus-local",
    "nexus-bybit-wsl-runner-diagnostics.yml": "nexus-local",
    "nexus-bybit-wsl-runner-wake.yml": "nexus-local",
    "nexus-bybit-wsl1-fallback.yml": "nexus-local",
    "nexus-continuous-phase3.yml": "nexus-local",
    "nexus-local-runner.yml": "nexus-local",
    "nexus-runtime-worker.yml": "nexus-local",
    "nexus-windows-dr-bootstrap.yml": "nexus-local",
    "nexus-windows-dr-persistence.yml": "nexus-remote-rescue",
    "nexus-wsl-virtualization-preflight.yml": "nexus-local",
    "nexus_local_autonomy.yml": "nexus-local",
    "nexus_phase3_resource_activation.yml": "nexus-local",
    "windows-dr-keyless.yml": "nexus-remote-rescue",
}


def _windows_routes(path: Path) -> list[str]:
    return WINDOWS_RUNS_ON.findall(path.read_text(encoding="utf-8"))


def test_all_windows_self_hosted_jobs_have_role_label():
    offenders = []
    for path in sorted(WORKFLOWS.glob("*.y*ml")):
        for line in _windows_routes(path):
            if "nexus-local" not in line and "nexus-remote-rescue" not in line:
                offenders.append(f"{path.name}: {line.strip()}")
    assert not offenders, "ambiguous Windows self-hosted routing: " + "; ".join(offenders)


def test_expected_windows_runner_roles_are_locked():
    for name, label in EXPECTED_ROUTES.items():
        routes = _windows_routes(WORKFLOWS / name)
        assert routes, f"missing Windows self-hosted route in {name}"
        assert all(label in route for route in routes), f"{name} must route through {label}: {routes}"


def test_local_runner_listener_detection_avoids_cim_dependency():
    script = (ROOT / "scripts" / "nexus_github_runner_autostart.ps1").read_text(encoding="utf-8")
    start = script.index("function Get-ListenerProcess")
    end = script.index("function Start-InteractiveRunner", start)
    block = script[start:end]
    assert "Get-CimInstance Win32_Process" not in block
    assert "Get-Process -Id $pidValue" in block
