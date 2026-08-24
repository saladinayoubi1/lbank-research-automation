"""Static fail-closed verifier for the NEXUS AI Room authority boundary."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent
AI_ROOM = ROOT / "ai_room.py"

FORBIDDEN_MODULES = {
    "agent_manager",
    "automated_signal_pipeline",
    "deterministic_risk",
    "paper_event_store",
    "paper_execution",
    "product_runtime",
    "strategy_lifecycle",
}
ALLOWED_ROUTES = {"paper-signal-proposal", "mission-runner"}


class AIRoomBoundaryError(ValueError):
    pass


def _imports(tree: ast.AST) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module.split(".", 1)[0])
    return modules


def validate_ai_room_boundary(path: Path = AI_ROOM) -> dict[str, object]:
    if not path.is_file() or path.is_symlink():
        raise AIRoomBoundaryError("AI Room implementation must be a regular non-symlink file")
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, UnicodeError, SyntaxError) as exc:
        raise AIRoomBoundaryError(f"AI Room implementation is unreadable: {exc}") from exc
    forbidden = sorted(_imports(tree) & FORBIDDEN_MODULES)
    if forbidden:
        raise AIRoomBoundaryError(f"AI Room imports state-mutating owner modules: {forbidden}")

    # Importing the module is safe only after the static mutation boundary passes.
    from ai_room import POLICY, TOOL_REGISTRY

    if set(TOOL_REGISTRY) != ALLOWED_ROUTES:
        raise AIRoomBoundaryError("AI Room tool registry contains an unapproved route")
    for route, definition in TOOL_REGISTRY.items():
        if definition.get("reversible") is not True:
            raise AIRoomBoundaryError(f"AI Room route {route!r} is not reversible")
    if set(POLICY.get("autonomous_authority_levels", [])) != {0, 1, 2, 3}:
        raise AIRoomBoundaryError("AI Room autonomous authority levels changed")
    if not {"production_deploy", "billing_change", "sign_release"} <= set(
        POLICY.get("human_required_actions", [])
    ):
        raise AIRoomBoundaryError("AI Room owner-required action boundary is incomplete")
    return {
        "ok": True,
        "authority": "proposal_review_route_only",
        "allowed_routes": sorted(ALLOWED_ROUTES),
        "forbidden_mutator_imports": forbidden,
        "live_trading_authority": False,
    }


if __name__ == "__main__":
    print(validate_ai_room_boundary())
