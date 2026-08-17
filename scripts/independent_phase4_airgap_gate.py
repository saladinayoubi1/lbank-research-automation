from __future__ import annotations

import ast
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from automated_signal_pipeline import DECISION_KEYS
from deterministic_risk import POLICY_KEYS, SIGNAL_KEYS, STATE_KEYS
from paper_execution import COMMAND_KEYS
from paper_live_airgap import FORBIDDEN_EXACT_KEYS, FORBIDDEN_KEY_FRAGMENTS

CRITICAL_MODULES = (
    ROOT / "automated_signal_pipeline.py",
    ROOT / "deterministic_risk.py",
    ROOT / "paper_execution.py",
    ROOT / "paper_event_store.py",
)
FORBIDDEN_NETWORK_IMPORTS = {
    "ccxt",
    "requests",
    "socket",
    "http.client",
    "urllib.request",
    "websockets",
    "aiohttp",
}


def _normalized(value: str) -> str:
    return value.casefold().replace("-", "_").replace(" ", "_")


def _field_safe(field: str) -> bool:
    key = _normalized(field)
    if key in FORBIDDEN_EXACT_KEYS:
        return False
    return not any(fragment in key for fragment in FORBIDDEN_KEY_FRAGMENTS)


def verify_contract_keysets() -> None:
    contracts = {
        "automated_decision": DECISION_KEYS,
        "risk_signal": SIGNAL_KEYS,
        "risk_state": STATE_KEYS,
        "risk_policy": POLICY_KEYS,
        "paper_command": COMMAND_KEYS,
    }
    violations = {
        name: sorted(key for key in keys if not _field_safe(key))
        for name, keys in contracts.items()
    }
    violations = {name: keys for name, keys in violations.items() if keys}
    if violations:
        raise SystemExit(f"paper/live air-gap contract field violation: {violations}")


def verify_no_network_execution_imports() -> None:
    violations: list[str] = []
    for path in CRITICAL_MODULES:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.append(node.module)
            for module in modules:
                if any(module == denied or module.startswith(denied + ".") for denied in FORBIDDEN_NETWORK_IMPORTS):
                    violations.append(f"{path.name}:{module}")
    if violations:
        raise SystemExit(
            "paper/live air-gap network import violation: " + ", ".join(sorted(violations))
        )


def verify_security_boundary_document() -> None:
    text = (ROOT / "docs" / "architecture" / "PHASE4_SECURITY_BOUNDARY.md").read_text(encoding="utf-8")
    required = (
        "private exchange credentials",
        "real-order endpoints",
        "withdrawals",
        "production promotion/deployment",
        "signing authority",
        "billing changes",
        "live financial execution",
        "pre-egress classification/redaction",
        "independent/trusted control",
    )
    missing = [item for item in required if item not in text]
    if missing:
        raise SystemExit(f"security boundary lost required invariant text: {missing}")


def main() -> int:
    verify_contract_keysets()
    verify_no_network_execution_imports()
    verify_security_boundary_document()
    print("Phase 4 independent paper/live air-gap gate: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
