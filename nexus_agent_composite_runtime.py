"""Real, bounded NEXUS Research Agent composite-backtest lease.

This module is a *workload*, not a strategy authorizer. The caller must stage
the already-verified immutable replay-v2 dataset and previous digest-bound
novelty ledger; missing inputs fail closed. A separate process can recompute
the numerical report as independent QA. No owner profile, exchange credentials,
Demo promotion, Live execution, or arbitrary trade-count ceiling is involved.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
from pathlib import Path
from typing import Any

import nexus_composite_strategy_research as research

SCHEMA = "nexus.agent-composite-execution.v1"
QA_SCHEMA = "nexus.agent-composite-independent-qa.v1"
SHA = re.compile(r"^[0-9a-f]{40}$")
LEASE = re.compile(r"^[a-zA-Z0-9_-]{1,160}$")


class RealResearchError(ValueError):
    pass


def _hash_file(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise RealResearchError("required immutable input or evidence is not a regular file")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _require_identity(source_sha: str, lease_id: str) -> None:
    if not SHA.fullmatch(source_sha):
        raise RealResearchError("source SHA must be exact and lowercase")
    if not LEASE.fullmatch(lease_id):
        raise RealResearchError("lease identity is invalid")


def _read_json(path: Path) -> dict[str, Any]:
    _hash_file(path)
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RealResearchError("evidence is unreadable") from exc
    if not isinstance(obj, dict):
        raise RealResearchError("evidence must be an object")
    return obj


def _checked_ledger(path: Path) -> dict[str, Any]:
    # Passing None silently restarts the first mechanism. A real Agent lease
    # must inherit and validate previous frontier state, never reset novelty.
    _hash_file(path)
    return research.load_ledger(path)


def _validate_report(
    report: dict[str, Any], ledger: dict[str, Any], previous: dict[str, Any],
    source_sha: str,
) -> None:
    claim = report.get("report_digest")
    core = {k: v for k, v in report.items() if k != "report_digest"}
    if (
        claim != research.digest(core)
        or report.get("schema") != research.SCHEMA
        or report.get("source_sha") != source_sha
        or report.get("archive_sha256") != research.ARCHIVE_SHA256
        or report.get("status") != "EVALUATED_RESEARCH_ONLY"
        or report.get("historical_test_pristine") is not False
        or report.get("independent_future_data_required") is not True
        or report.get("research_only") is not True
        or report.get("auto_demo_promotion") is not False
        or report.get("live_enabled") is not False
        or report.get("qualification") != "NOT_QUALIFIED_NO_PRISTINE_FUTURE_HOLDOUT"
        or report.get("ledger_digest") != ledger.get("ledger_digest")
    ):
        raise RealResearchError("research report provenance, digest, or authority rejected")
    chosen = report.get("selected")
    if not isinstance(chosen, dict):
        raise RealResearchError("missing executed mechanism")
    if (
        chosen.get("mechanism") not in research.MECHANISMS
        or chosen.get("fingerprint") in previous["config_fingerprints_evaluated"]
        or chosen.get("fingerprint") not in ledger["config_fingerprints_evaluated"]
        or len(ledger["config_fingerprints_evaluated"])
           != len(previous["config_fingerprints_evaluated"]) + 1
    ):
        raise RealResearchError("new mechanism fingerprint is duplicate or unbound")
    # Complete two-symbol, three-fold, two-cost actual numerical evidence.
    rows = report.get("rows")
    if not isinstance(rows, list) or len(rows) != 12:
        raise RealResearchError("expected real two-symbol/six-profile backtests")
    cells = {(x.get("symbol"), x.get("part"), x.get("profile")) for x in rows if isinstance(x, dict)}
    expected = {
        (s, p, k)
        for s in research.SYMBOLS
        for p in ("train", "validation", "historically_inspected_test")
        for k in ("conservative", "stress")
    }
    if cells != expected:
        raise RealResearchError("backtest grid missing or duplicated")
    for row in rows:
        if (
            row.get("mechanism") != chosen["mechanism"]
            or row.get("config_fingerprint") != chosen["fingerprint"]
            or row.get("trade_count_limit") is not None
            or not isinstance(row.get("closed_round_trips"), int)
            or row["closed_round_trips"] < 0
            or not isinstance(row.get("net_return_pct"), (int, float))
            or not isinstance(row.get("max_drawdown_pct"), (int, float))
        ):
            raise RealResearchError("incomplete or capped backtest numeric evidence")


def _summary(report: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            k: row.get(k)
            for k in (
                "symbol", "timeframe", "mechanism", "profile", "closed_round_trips",
                "net_return_pct", "max_drawdown_pct", "win_rate_pct", "profit_factor",
                "fee_bps", "slippage_bps", "bars", "first_closed_utc", "last_closed_utc",
            )
        }
        for row in report["rows"] if row["part"] == "validation"
    ]


def run_lease(
    *, archive_root: Path, previous_ledger: Path, source_sha: str,
    lease_id: str, output_dir: Path,
) -> dict[str, Any]:
    _require_identity(source_sha, lease_id)
    previous = _checked_ledger(previous_ledger)
    output_dir.mkdir(parents=True, exist_ok=True)
    if (output_dir / "research-report.json").exists():
        raise RealResearchError("lease output already exists; do not overwrite evidence")
    report = research.run(archive_root, output_dir, source_sha, previous_ledger)
    ledger = _checked_ledger(output_dir / "novelty-ledger.json")
    _validate_report(report, ledger, previous, source_sha)
    core = {
        "schema": SCHEMA,
        "lease_id": lease_id,
        "source_sha": source_sha,
        "archive_sha256": research.ARCHIVE_SHA256,
        "prior_ledger_digest": previous["ledger_digest"],
        "ledger_digest": ledger["ledger_digest"],
        "report_digest": report["report_digest"],
        "report_file_sha256": _hash_file(output_dir / "research-report.json"),
        "ledger_file_sha256": _hash_file(output_dir / "novelty-ledger.json"),
        "mechanism": report["selected"]["mechanism"],
        "config_fingerprint": report["selected"]["fingerprint"],
        "validation": _summary(report),
        "research_only": True,
        "auto_demo_promotion": False,
        "live_enabled": False,
        "independent_qa_complete": False,
    }
    receipt = {**core, "receipt_digest": research.digest(core)}
    research.safe_write(output_dir / "agent-receipt.json", receipt)
    return receipt


def verify_independently(
    *, archive_root: Path, previous_ledger: Path, source_sha: str,
    lease_id: str, result_dir: Path, output: Path,
) -> dict[str, Any]:
    """On a DIFFERENT worker, re-run the backtest rather than trust its digest."""
    _require_identity(source_sha, lease_id)
    previous = _checked_ledger(previous_ledger)
    receipt = _read_json(result_dir / "agent-receipt.json")
    receipt_core = {k: v for k, v in receipt.items() if k != "receipt_digest"}
    report = _read_json(result_dir / "research-report.json")
    ledger = _checked_ledger(result_dir / "novelty-ledger.json")
    if (
        receipt.get("receipt_digest") != research.digest(receipt_core)
        or receipt.get("schema") != SCHEMA
        or receipt.get("source_sha") != source_sha
        or receipt.get("lease_id") != lease_id
        or receipt.get("prior_ledger_digest") != previous["ledger_digest"]
        or receipt.get("research_only") is not True
        or receipt.get("auto_demo_promotion") is not False
        or receipt.get("live_enabled") is not False
        or receipt.get("independent_qa_complete") is not False
        or receipt.get("report_file_sha256") != _hash_file(result_dir / "research-report.json")
        or receipt.get("ledger_file_sha256") != _hash_file(result_dir / "novelty-ledger.json")
    ):
        raise RealResearchError("producer lease receipt or input binding rejected")
    _validate_report(report, ledger, previous, source_sha)
    with tempfile.TemporaryDirectory(prefix="nexus-independent-qa-") as temp:
        independent = research.run(archive_root, Path(temp), source_sha, previous_ledger)
        independent_ledger = _checked_ledger(Path(temp) / "novelty-ledger.json")
        _validate_report(independent, independent_ledger, previous, source_sha)
        if independent != report or independent_ledger != ledger:
            raise RealResearchError("independent numerical replay differs from producer")
    core = {
        "schema": QA_SCHEMA,
        "lease_id": lease_id,
        "source_sha": source_sha,
        "archive_sha256": research.ARCHIVE_SHA256,
        "producer_receipt_digest": receipt["receipt_digest"],
        "producer_report_digest": receipt["report_digest"],
        "independent_replay_matches": True,
        "research_only": True,
        "auto_demo_promotion": False,
        "live_enabled": False,
    }
    evidence = {**core, "qa_digest": research.digest(core)}
    research.safe_write(output, evidence)
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("run", "verify"))
    parser.add_argument("--archive-root", type=Path, required=True)
    parser.add_argument("--previous-ledger", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--lease-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.mode == "run":
        receipt = run_lease(
            archive_root=args.archive_root, previous_ledger=args.previous_ledger,
            source_sha=args.source_sha, lease_id=args.lease_id, output_dir=args.output,
        )
        print(json.dumps({k: v for k, v in receipt.items() if k != "validation"}, sort_keys=True))
    else:
        proof = verify_independently(
            archive_root=args.archive_root, previous_ledger=args.previous_ledger,
            source_sha=args.source_sha, lease_id=args.lease_id,
            result_dir=args.output, output=args.output / "qa-evidence.json",
        )
        print(json.dumps(proof, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
