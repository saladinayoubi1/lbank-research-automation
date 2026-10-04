"""Read-only, hash-pinned projections of reviewed research artifacts."""
from __future__ import annotations

import hashlib
import json
import math
import stat
from pathlib import Path
from typing import Any


class ResearchReportError(ValueError):
    pass


CATALOG = (
    ("A7", "a7-range-failure-reversal-report.json",
     "nexus.a7-range-failure-reversal-research.v1",
     "25d4d71b75ea0a36db9f7722d36cc9c5c169e23dbdc032ab98a9f2374a80fd16",
     37182958720, "REJECTED_NO_POSITIVE_RECENT_STRESS_CELL"),
    ("A9", "perpetual-positioning-divergence-report.json",
     "nexus.perpetual-positioning-divergence-research.v2",
     "7d53abdbe6d580fca0aadabcd8c7090033f486ce99ba10bb0c6d3401a7050899",
     37182958757, "NOT_QUALIFIED_NO_PRISTINE_FUTURE_HOLDOUT"),
)
SOURCE_SHA = "9eda5b66869b1c9c578b18256e74ae8e661cb2f8"


def canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ResearchReportError("Non-canonical evidence") from exc


def reject_duplicate_keys(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ResearchReportError("Duplicate evidence key")
        value[key] = item
    return value


def safe_json(path: Path, *, limit: int = 262_144) -> dict:
    for candidate in (path, *path.parents):
        if not candidate.exists():
            continue
        mode = candidate.lstat()
        if stat.S_ISLNK(mode.st_mode) or getattr(mode, "st_file_attributes", 0) & 0x400:
            raise ResearchReportError("Evidence link/reparse point rejected")
    if not path.is_file() or not 2 <= path.stat().st_size <= limit:
        raise ResearchReportError("Evidence file missing or outside size bound")
    try:
        value = json.loads(path.read_text(encoding="utf-8"),
                           object_pairs_hook=reject_duplicate_keys)
    except (OSError, UnicodeError, ValueError) as exc:
        raise ResearchReportError("Unreadable evidence") from exc
    if not isinstance(value, dict):
        raise ResearchReportError("Evidence object required")
    canonical_bytes(value)
    return value


class ResearchReportStore:
    def __init__(self, ui_root: Path):
        self.root = ui_root / "research-reports"

    def snapshot(self) -> dict:
        reports, errors = [], []
        for label, name, schema, expected_sha, run, verdict in CATALOG:
            try:
                report = safe_json(self.root / name)
                core = {key: value for key, value in report.items() if key != "report_sha256"}
                actual = hashlib.sha256(canonical_bytes(core)).hexdigest()
                if actual != expected_sha or report.get("report_sha256") != expected_sha:
                    raise ResearchReportError("Reviewed report digest mismatch")
                if report.get("schema") != schema or report.get("source_sha") != SOURCE_SHA:
                    raise ResearchReportError("Reviewed schema/source mismatch")
                if (report.get("research_only") is not True or report.get("paper_only") is not True
                        or any(report.get(key) is not False for key in (
                            "automatic_strategy_promotion", "derivative_execution_authority",
                            "live_trading_authority"))):
                    raise ResearchReportError("Research authority mismatch")
                if report.get("conclusion", report.get("qualification")) != verdict:
                    raise ResearchReportError("Original research verdict changed")
                rows = report.get("rows")
                if not isinstance(rows, list) or len(rows) != (8 if label == "A7" else 12):
                    raise ResearchReportError("Research row coverage mismatch")
                for row in rows:
                    for field in ("net_return_pct", "max_drawdown_pct"):
                        n = row.get(field)
                        if isinstance(n, bool) or not isinstance(n, (float, int)) or not math.isfinite(n):
                            raise ResearchReportError("Invalid research metric")
                reports.append({
                    "id": label, "status": "verified", "provider": "Bybit",
                    "reference_capital_usdt": 10000, "report_sha256": actual,
                    "source_sha": SOURCE_SHA, "original_verdict": verdict,
                    "run_url": f"https://github.com/saladinayoubi1/lbank-research-automation/actions/runs/{run}",
                    "execution_eligible": False, "report": report,
                })
            except (OSError, ResearchReportError) as exc:
                errors.append({"id": label, "status": "rejected", "reason": str(exc)})
        return {"contract_version": "nexus.reviewed-research-view.v1", "read_only": True,
                "paper_only": True, "live_trading_authority": False,
                "report_count": len(reports), "reports": reports, "errors": errors}
