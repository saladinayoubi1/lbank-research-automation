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
    ("A6", "a6-signed-flow-price-response-report.json",
     "nexus.signed-flow-price-response-research.v1",
     "d15e0fdbea439833394d21316022f46f964b6c56dfd88c7aa4c9dee852a8c8b8",
     None, "NOT_QUALIFIED_NO_PRISTINE_FUTURE_HOLDOUT"),
)
SOURCE_SHA = "9eda5b66869b1c9c578b18256e74ae8e661cb2f8"
A6_SOURCE_SHA = "b8de92430d236dbc47a05d4b6b6a21dc47398a7c"
A6_PROOF_SHA = "348512f0dc1753d9cf56daa8123a137a3992e6e27a4f315861e0d1756f6c195c"
A6_QA_SHA = "6839d5bf6966e549d14856a79eeca01614a6392f949aaddcad0b3aa181119182"
A6_EVIDENCE_URL = "https://github.com/saladinayoubi1/lbank-research-automation/issues/2008#issuecomment-6078926439"


def verified_a6_data(root: Path, report: dict) -> dict:
    proof = safe_json(root / "a6-signed-trade-flow-proof.json")
    qa = safe_json(root / "a6-full-independent-numeric-qa.json")
    for value, field, expected in ((proof, "proof_sha256", A6_PROOF_SHA),
                                   (qa, "report_digest", A6_QA_SHA)):
        core = {k: v for k, v in value.items() if k != field}
        if value.get(field) != expected or hashlib.sha256(canonical_bytes(core)).hexdigest() != expected:
            raise ResearchReportError("A6 data/QA digest mismatch")
    if (proof.get("schema") != "nexus.verified-signed-trade-flow-proof.v1"
            or proof.get("capability") != "verified_signed_trade_flow"
            or proof.get("market") != "spot"
            or proof.get("rows") != 5760 or len(proof.get("sources", [])) != 60
            or report.get("signed_flow_proof_sha256") != A6_PROOF_SHA
            or report.get("signed_flow_dataset_sha256") != proof.get("dataset_semantic_sha256")
            or qa.get("canonical_proof_sha256") != A6_PROOF_SHA
            or qa.get("schema") != "nexus.a6-independent-full-numeric-qa.v1"
            or qa.get("execution_kind") != "physical_local_independent_numeric_qa"
            or qa.get("passed") is not True or qa.get("prior_inputs_unchanged") is not True
            or qa.get("verified_archives") != 60 or qa.get("verified_bars") != 5760
            or qa.get("verified_trade_rows") != 21662587
            or qa.get("paper_authority") is not False
            or qa.get("pristine_future_holdout") is not False
            or qa.get("side_semantics_live_api_crossvalidated") is not False):
        raise ResearchReportError("A6 coverage, scope or authority mismatch")
    for value in (proof, qa):
        if (value.get("research_only") is not True or value.get("live_trading_authority") is not False
                or value.get("automatic_strategy_promotion") is not False):
            raise ResearchReportError("A6 input authority mismatch")
    sources = {(s["symbol"], s["audit_date"], s["sha256"]) for s in proof["sources"]}
    checked = {(s["symbol"], s["day"], s["sha256"]) for s in qa["files"] if s.get("passed") is True}
    if (len(sources) != 60 or sources != checked
            or {s[0] for s in sources} != {"BTCUSDT", "ETHUSDT"}
            or proof.get("start_date") != "2026-07-03" or proof.get("end_date") != "2026-08-01"):
        raise ResearchReportError("A6 source coverage mismatch")
    return {
        "capability": "verified_signed_trade_flow", "status": "verified_historical_data",
        "market": "spot", "symbols": ["BTCUSDT", "ETHUSDT"], "timeframe": "minute15",
        "start_date": proof["start_date"], "end_date": proof["end_date"],
        "dataset_semantic_sha256": proof["dataset_semantic_sha256"],
        "proof_sha256": A6_PROOF_SHA, "independent_numeric_qa_sha256": A6_QA_SHA,
        "archives": 60, "bars": 5760, "raw_trade_rows": 21662587,
        "side_semantics_live_api_crossvalidated": False, "pristine_future_holdout": False,
        "strategy_result": "rejected_no_promotion", "execution_eligible": False,
    }


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
                source_sha = A6_SOURCE_SHA if label == "A6" else SOURCE_SHA
                if report.get("schema") != schema or report.get("source_sha") != source_sha:
                    raise ResearchReportError("Reviewed schema/source mismatch")
                if (report.get("research_only") is not True or report.get("paper_only") is not True
                        or any(report.get(key) is not False for key in (
                            "automatic_strategy_promotion",
                            "live_trading_authority"))):
                    raise ResearchReportError("Research authority mismatch")
                if label != "A6" and report.get("derivative_execution_authority") is not False:
                    raise ResearchReportError("Research derivative authority mismatch")
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
                data = verified_a6_data(self.root, report) if label == "A6" else None
                reports.append({
                    "id": label, "status": "verified", "provider": "Bybit",
                    "reference_capital_usdt": 10000, "report_sha256": actual,
                    "source_sha": source_sha, "original_verdict": verdict,
                    "run_url": None if run is None else f"https://github.com/saladinayoubi1/lbank-research-automation/actions/runs/{run}",
                    "evidence_url": A6_EVIDENCE_URL if label == "A6" else None,
                    "evidence_kind": "physical_local_research" if label == "A6" else "github_actions",
                    "verified_data": data,
                    "execution_eligible": False, "report": report,
                })
            except (OSError, KeyError, TypeError, ResearchReportError) as exc:
                errors.append({"id": label, "status": "rejected", "reason": str(exc)})
        return {"contract_version": "nexus.reviewed-research-view.v1", "read_only": True,
                "paper_only": True, "live_trading_authority": False,
                "report_count": len(reports), "reports": reports, "errors": errors}

