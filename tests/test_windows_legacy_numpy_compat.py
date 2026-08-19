from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _runtime_pins() -> dict[str, str]:
    pins: dict[str, str] = {}
    for raw in (ROOT / "requirements.lock").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "==" not in line:
            continue
        name, version = line.split("==", 1)
        pins[name.casefold()] = version
    return pins


def test_windows_product_keeps_numpy_before_x86_64_v2_baseline_raise() -> None:
    """NEXUS must remain runnable on the owner's older Windows laptop.

    NumPy 2.4 raised the default x86 baseline to x86-64-v2.  The physical
    Phase 7 laptop reported a frozen `_multiarray_umath` DLL initialization
    failure with NumPy 2.5.1.  Keep the redistributable runtime on the final
    2.3.x line unless a real hardware acceptance run proves a newer baseline.
    """

    pins = _runtime_pins()
    assert pins["numpy"] == "2.3.5"
    assert pins["pandas"] == "2.3.3"
