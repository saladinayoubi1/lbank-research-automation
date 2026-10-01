"""Create a privacy-minimized public proof from the private owner Paper checkpoint.

Only derived Research-gating evidence leaves the physical Paper job. Full Paper state,
positions, balances, journals, and credentials are never serialized by this module.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import json
import sys
from pathlib import Path
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from nexus_multipair_paper_boundary_discovery_feedback import (
    build_boundary_context,
    verify_boundary_context,
)
from nexus_multipair_persistent_paper_trading_loop import verify_loop_snapshot
from nexus_strategy_discovery_health_trigger import (
    build_health_trigger,
    verify_health_trigger,
)


MAX_EVIDENCE_BYTES = 64 * 1024


class PublicPaperBoundaryProofError(RuntimeError):
    pass
def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PublicPaperBoundaryProofError(f"evidence input is unavailable: {path}") from exc
    if not isinstance(value, dict):
        raise PublicPaperBoundaryProofError(f"evidence input is not an object: {path}")
    return value


def _write_object(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(dict(value), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    encoded = payload.encode("utf-8")
    if not 0 < len(encoded) <= MAX_EVIDENCE_BYTES:
        raise PublicPaperBoundaryProofError("public evidence exceeds the bounded surface")
    path.write_bytes(encoded)


def _validate_health(
    health: Mapping[str, Any], *, source_sha: str, run_id: str
) -> None:
    verification = verify_health_trigger(health)
    if verification.get("decision") != "pass":
        raise PublicPaperBoundaryProofError("health trigger failed independent verification")
    if (
        health.get("source_sha") != source_sha
        or str(health.get("run_id")) != run_id
        or health.get("research_only") is not True
        or health.get("paper_only") is not True
        or health.get("live_trading_authority") is not False
        or health.get("qualification_authority") is not False
        or health.get("automatic_strategy_promotion") is not False
    ):
        raise PublicPaperBoundaryProofError("health trigger exact-run or authority binding failed")


def _validate_context(
    context: Mapping[str, Any],
    health: Mapping[str, Any],
    *,
    source_sha: str,
    run_id: str,
) -> None:
    verification = verify_boundary_context(context)
    if verification.get("decision") != "pass":
        raise PublicPaperBoundaryProofError("boundary context failed independent verification")
    if (
        context.get("source_sha") != source_sha
        or str(context.get("paper_run_id")) != run_id
        or context.get("paper_loop_digest") != health.get("loop_digest")
    ):
        raise PublicPaperBoundaryProofError("boundary context exact-run binding failed")
    if (
        context.get("research_only") is not True
        or context.get("paper_only") is not True
        or context.get("live_trading_authority") is not False
        or context.get("private_credentials_used") is not False
        or context.get("real_exchange_orders") is not False
        or context.get("automatic_strategy_promotion") is not False
    ):
        raise PublicPaperBoundaryProofError("boundary context authority binding failed")


def validate_public_evidence(
    health: Mapping[str, Any],
    context: Mapping[str, Any] | None,
    *,
    source_sha: str,
    run_id: str,
    require_context: bool = False,
) -> None:
    _validate_health(health, source_sha=source_sha, run_id=run_id)
    if context is None:
        if require_context:
            raise PublicPaperBoundaryProofError("required boundary context is unavailable")
        return
    _validate_context(context, health, source_sha=source_sha, run_id=run_id)


def _encode_file(path: Path) -> str:
    raw = path.read_bytes()
    if not 0 < len(raw) <= MAX_EVIDENCE_BYTES:
        raise PublicPaperBoundaryProofError("public evidence exceeds the bounded surface")
    return base64.b64encode(raw).decode("ascii")
def _decode_value(value: str, label: str) -> dict[str, Any]:
    try:
        raw = base64.b64decode(value.encode("ascii"), validate=True)
    except (UnicodeEncodeError, binascii.Error, ValueError) as exc:
        raise PublicPaperBoundaryProofError(f"{label} encoding is invalid") from exc
    if not 0 < len(raw) <= MAX_EVIDENCE_BYTES:
        raise PublicPaperBoundaryProofError(f"{label} exceeds the bounded surface")
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PublicPaperBoundaryProofError(f"{label} JSON is invalid") from exc
    if not isinstance(decoded, dict):
        raise PublicPaperBoundaryProofError(f"{label} is not an object")
    return decoded


def export_evidence(args: argparse.Namespace) -> int:
    loop = _read_object(args.loop_snapshot)
    matrix = _read_object(args.matrix_state)
    if verify_loop_snapshot(loop).get("decision") != "pass":
        raise PublicPaperBoundaryProofError("Paper-loop snapshot failed independent verification")
    if loop.get("source_sha") != args.source_sha or str(loop.get("run_id")) != args.run_id:
        raise PublicPaperBoundaryProofError("Paper-loop snapshot exact-run binding failed")

    health = build_health_trigger(loop)
    context = build_boundary_context(loop, matrix) if health["should_dispatch"] else None
    validate_public_evidence(
        health, context, source_sha=args.source_sha, run_id=args.run_id
    )
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    health_path = output / "health-trigger.json"
    context_path = output / "boundary-context.json"
    _write_object(health_path, health)
    context_path.unlink(missing_ok=True)
    if context is not None:
        _write_object(context_path, context)

    with args.github_output.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(f"health_b64={_encode_file(health_path)}\n")
        handle.write(
            f"context_b64={_encode_file(context_path) if context is not None else ''}\n"
        )
    print(
        json.dumps(
            {
                "public_paper_boundary_proof": "PASS",
                "should_dispatch": health["should_dispatch"],
                "context_emitted": context is not None,
                "source_sha": args.source_sha,
                "run_id": args.run_id,
            },
            sort_keys=True,
        )
    )
    return 0


def restore_evidence(args: argparse.Namespace) -> int:
    health = _decode_value(args.health_b64, "health evidence")
    context = _decode_value(args.context_b64, "boundary context") if args.context_b64 else None
    validate_public_evidence(
        health,
        context,
        source_sha=args.source_sha,
        run_id=args.run_id,
        require_context=args.require_context,
    )
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    _write_object(output / "health-trigger.json", health)
    context_path = output / "boundary-context.json"
    context_path.unlink(missing_ok=True)
    if context is not None:
        _write_object(context_path, context)
    print(
        json.dumps(
            {
                "public_paper_boundary_restore": "PASS",
                "should_dispatch": health["should_dispatch"],
                "context_present": context is not None,
                "source_sha": args.source_sha,
                "run_id": args.run_id,
            },
            sort_keys=True,
        )
    )
    return 0


def verify_evidence(args: argparse.Namespace) -> int:
    root = args.root.resolve()
    health = _read_object(root / "health-trigger.json")
    context_path = root / "boundary-context.json"
    context = _read_object(context_path) if context_path.is_file() else None
    validate_public_evidence(
        health,
        context,
        source_sha=args.source_sha,
        run_id=args.run_id,
        require_context=args.require_context,
    )
    print(
        json.dumps(
            {
                "public_paper_boundary_verification": "PASS",
                "should_dispatch": health["should_dispatch"],
                "context_present": context is not None,
                "source_sha": args.source_sha,
                "run_id": args.run_id,
            },
            sort_keys=True,
        )
    )
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    export = commands.add_parser("export")
    export.add_argument("--loop-snapshot", type=Path, required=True)
    export.add_argument("--matrix-state", type=Path, required=True)
    export.add_argument("--output-dir", type=Path, required=True)
    export.add_argument("--github-output", type=Path, required=True)
    export.add_argument("--source-sha", required=True)
    export.add_argument("--run-id", required=True)
    export.set_defaults(func=export_evidence)
    restore = commands.add_parser("restore")
    restore.add_argument("--health-b64", required=True)
    restore.add_argument("--context-b64", default="")
    restore.add_argument("--output-dir", type=Path, required=True)
    restore.add_argument("--source-sha", required=True)
    restore.add_argument("--run-id", required=True)
    restore.add_argument("--require-context", action="store_true")
    restore.set_defaults(func=restore_evidence)

    verify = commands.add_parser("verify")
    verify.add_argument("--root", type=Path, required=True)
    verify.add_argument("--source-sha", required=True)
    verify.add_argument("--run-id", required=True)
    verify.add_argument("--require-context", action="store_true")
    verify.set_defaults(func=verify_evidence)
    return parser


def main() -> int:
    args = _parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())