"""Persist exact QA -> QUAL-42 -> REG-50 research reviews from Agent Manager.

This is bounded evidence transport in the existing coordinator cache/artifact,
not a second runtime registry or a Paper writer. It never activates a record.
"""
from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping
from pathlib import Path
import sys
import tempfile
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nexus_strategy_qualification_gate import evaluate_qualification, verify_qualification
from strategy_registry import build_qualified_strategy_record, verify_qualified_strategy_record

SUPPORTED_TASKS = frozenset({
    "nexus.strategy-review-qa-task.v1", "nexus.composite-runtime-qa-task.v1",
})
MAX_BYTES = 16_000_000
MAX_QA_TASKS = 256


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, ensure_ascii=False,
                       allow_nan=False, indent=2) + "\n").encode("utf-8")


def _read(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise ValueError("admission evidence input is missing, linked, or oversized")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("admission evidence must be an object")
    return value


def build_reviews(runtime: Mapping[str, Any]) -> list[dict[str, Any]]:
    if runtime.get("schema_version") != 1 or not isinstance(runtime.get("tasks"), list):
        raise ValueError("Agent Manager runtime schema mismatch")
    tasks = [task for task in runtime["tasks"] if isinstance(task, Mapping)
             and (task.get("qa_verifier_only") is True or "qa_handoff_task" in task)]
    if len(tasks) > MAX_QA_TASKS:
        raise ValueError("unbounded QA admission batch")
    reviews, seen = [], set()
    for task in tasks:
        handoff = task.get("qa_handoff_task")
        if not isinstance(handoff, Mapping) or handoff.get("schema_version") not in SUPPORTED_TASKS:
            raise ValueError("unsupported QA task cannot be silently omitted from admission")
        qualification = evaluate_qualification(task)
        verification = verify_qualification(qualification)
        if verification["decision"] != "pass":
            raise ValueError("computed QUAL-42 review failed verification")
        ident = qualification["strategy_qa_task_id"]
        if ident in seen:
            raise ValueError("duplicate QA task identity in admission batch")
        seen.add(ident)
        record, record_verification = None, None
        if qualification["registry_admission_allowed"] is True:
            record = build_qualified_strategy_record(qualification, verification)
            record_verification = verify_qualified_strategy_record(record)
            if record_verification["decision"] != "pass":
                raise ValueError("computed REG-50 record failed verification")
        reviews.append({
            "schema_version": "nexus.strategy-admission-review.v1",
            "qualification": qualification,
            "qualification_verification": verification,
            "registry_record": record,
            "registry_record_verification": record_verification,
            "runtime_activation_performed": False,
            "paper_execution_performed": False,
            "live_trading_authority": False,
        })
    return sorted(reviews, key=lambda row: row["qualification"]["strategy_qa_task_id"])


def persist_reviews(runtime: Mapping[str, Any], store: Path) -> dict[str, Any]:
    # Validate the WHOLE bounded batch before any evidence is written.
    reviews = build_reviews(runtime)
    if store.is_symlink() or (store.exists() and not store.is_dir()):
        raise ValueError("admission evidence store is invalid")
    store.mkdir(parents=True, exist_ok=True)
    pending = []
    for review in reviews:
        qualification = review["qualification"]
        path = store / (qualification["qualification_digest"] + ".json")
        if path.exists() or path.is_symlink():
            if _read(path) != review:
                raise ValueError("immutable admission review conflicts with existing evidence")
        else:
            pending.append((path, review))
    written = 0
    for path, review in pending:
        # Publish complete immutable bytes atomically. A restart can never see
        # a half-written target; a concurrent writer cannot replace a receipt.
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=store, suffix=".tmp", delete=False) as output:
                temporary = Path(output.name)
                output.write(_json_bytes(review))
                output.flush()
                os.fsync(output.fileno())
            try:
                os.link(temporary, path)
                written += 1
            except FileExistsError:
                if _read(path) != review:
                    raise ValueError("concurrent immutable admission review conflict")
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    return {
        "schema_version": "nexus.strategy-admission-review-summary.v1",
        "status": "QA_REVIEWS_EVALUATED" if reviews else "NO_QA_TASKS",
        "evaluated_qa_tasks": len(reviews),
        "new_evidence_files": written,
        "registry_candidate_records": sum(row["registry_record"] is not None for row in reviews),
        "tasks": [{
            "id": row["qualification"]["strategy_qa_task_id"],
            "decision": row["qualification"]["decision"],
            "reason_codes": row["qualification"]["reason_codes"],
            "qualification_digest": row["qualification"]["qualification_digest"],
            "record_digest": row["registry_record"]["record_digest"] if row["registry_record"] else None,
        } for row in reviews],
        "runtime_activation_performed": False,
        "paper_execution_performed": False,
        "live_trading_authority": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args()
    error = None
    try:
        result = persist_reviews(_read(args.runtime), args.store)
    except (ValueError, TypeError, KeyError, OSError) as exc:
        error = exc
        result = {
            "schema_version": "nexus.strategy-admission-review-summary.v1",
            "status": "ADMISSION_REVIEW_FAILED",
            "reason": str(exc)[:600],
            "runtime_activation_performed": False,
            "paper_execution_performed": False,
            "live_trading_authority": False,
        }
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.summary.with_suffix(".tmp")
    temporary.write_bytes(_json_bytes(result))
    os.replace(temporary, args.summary)
    print(json.dumps(result, sort_keys=True))
    if error is not None:
        raise error
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
