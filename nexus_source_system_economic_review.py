"""Import one committed, finished economic study through the existing Manager.

This is evidence review, not a second market replay or economic qualification.
The original numerical QA remains separately identified and byte pinned.
Coordinator, producer and verifier need only the standard library.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, Mapping

from nexus_complete_strategy_system import digest

ROOT = Path(__file__).resolve().parent
DIRECTORY = "research/source_system_economic_reviews"
PREFIX = "ECON-REVIEW-"
SCHEMA = "nexus.source-system-economic-review.v1"
TASK_SCHEMA = "nexus.source-system-economic-review-task.v1"
RECEIPT_SCHEMA = "nexus.source-system-economic-review-receipt.v1"
CODE = ("nexus_source_system_economic_review.py", "nexus_complete_strategy_system.py")
PARTITIONS = ("training", "validation_already_inspected", "historical_test_already_inspected")
COSTS = ("conservative", "stress")
BOUNDARIES = {"research_only": True, "evidence_ingestion_only": True,
              "market_replay_performed": False, "economic_edge_established": False,
              "paper_eligible": False, "demo_eligible": False, "live_enabled": False,
              "automatic_strategy_promotion": False, "qualification_authority": False,
              "registry_mutation_authority": False}
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
HEX40 = re.compile(r"[0-9a-f]{40}\Z")


class EconomicReviewError(ValueError):
    pass


def is_review(task: Mapping[str, Any]) -> bool:
    return isinstance(task.get("id"), str) and task["id"].startswith(PREFIX)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _raw(root: Path, relative: str, pattern: str, limit: int = 200_000) -> bytes:
    if type(relative) is not str or not re.fullmatch(pattern, relative):
        raise EconomicReviewError("unsupported economic evidence path")
    path = root / relative
    if (any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file()
        or not 0 < path.stat().st_size <= limit):
        raise EconomicReviewError("economic evidence is missing, linked or oversized")
    return path.read_bytes()


def _object(raw: bytes) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise EconomicReviewError("duplicate economic evidence field")
            result[key] = value
        return result
    try:
        value = json.loads(raw.decode("utf8"), object_pairs_hook=pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, UnicodeError) as exc:
        raise EconomicReviewError("invalid economic evidence JSON") from exc
    if type(value) is not dict:
        raise EconomicReviewError("economic evidence must be an object")
    return value


def _number(value: Any) -> float:
    if type(value) not in (int, float) or not math.isfinite(value):
        raise EconomicReviewError("economic metric must be a finite number")
    return float(value)


def _equal(a: Any, b: Any) -> None:
    # Published monetary fields are rounded to eight decimals; summing separately
    # rounded trade components may differ in the last decimal places.
    if not math.isclose(_number(a), _number(b), rel_tol=0., abs_tol=0.000001):
        raise EconomicReviewError("economic ledger arithmetic disagrees")


def disposition(rows: list[dict]) -> str:
    if all(r["trades"] == 0 for r in rows):
        return "NO_EXECUTION_EVIDENCE"
    if any(r["net_pnl_usdt"] < 0 for r in rows):
        return "HISTORICAL_NEGATIVE_DO_NOT_RETUNE"
    if any(r["trades"] == 0 for r in rows):
        return "MIXED_ACTIVITY_NO_EXECUTION_EVIDENCE_IN_SOME_PARTITIONS"
    return "HISTORICAL_POSITIVE_ONLY_FUTURE_EVIDENCE_REQUIRED"


def load_evidence(relative: str, root: Path | None = None) -> tuple[dict, bytes, dict]:
    root = root or ROOT
    raw = _raw(root, relative, re.escape(DIRECTORY) + r"/[a-z0-9_]+\.json")
    manifest = _object(raw)
    keys = {"schema", "economic_task_id", "economic_request_path", "economic_request_sha256",
            "producer_result_sha256", "producer_result_digest", "numerical_qa_sha256",
            "numerical_qa_receipt_digest", "execution_source_sha", "workflow_run_id", "selection_basis"}
    if (set(manifest) != keys or manifest.get("schema") != SCHEMA
        or manifest.get("selection_basis") != "one_finished_study_no_market_replay"
        or type(manifest.get("workflow_run_id")) is not str
        or not re.fullmatch(r"[1-9][0-9]{0,19}", manifest["workflow_run_id"])
        or type(manifest.get("execution_source_sha")) is not str
        or not HEX40.fullmatch(manifest["execution_source_sha"])
        or any(type(manifest.get(k)) is not str or not HEX64.fullmatch(manifest[k])
               for k in keys if k.endswith("sha256") or k.endswith("digest"))):
        raise EconomicReviewError("invalid finished-study manifest")
    request_raw = _raw(root, manifest["economic_request_path"],
                       r"research/source_system_economic_requests/[a-z0-9_]+\.json")
    task = "SYSTEM-ECON-" + _sha(request_raw)[:24]
    if _sha(request_raw) != manifest["economic_request_sha256"] or manifest["economic_task_id"] != task:
        raise EconomicReviewError("original economic task identity changed")
    request = _object(request_raw)
    system_raw = _raw(root, request["system_specification_path"], r"research/complete_systems/[a-z0-9_]+\.json")
    worker_raw = _raw(root, "scripts/nexus_source_system_economic_execution.py",
                      r"scripts/nexus_source_system_economic_execution\.py")
    if (_sha(system_raw) != request["system_specification_sha256"]
        or _sha(worker_raw) != request["worker_source_sha256"]):
        raise EconomicReviewError("original complete system or economic worker changed")
    result_path = "research/source_system_economic_results/" + task
    producer_raw = _raw(root, result_path + ".json", re.escape(result_path + ".json"))
    qa_raw = _raw(root, result_path + ".qa.json", re.escape(result_path + ".qa.json"))
    if (_sha(producer_raw) != manifest["producer_result_sha256"]
        or _sha(qa_raw) != manifest["numerical_qa_sha256"]):
        raise EconomicReviewError("original economic result or numerical QA bytes changed")
    producer, qa, system = _object(producer_raw), _object(qa_raw), _object(system_raw)
    identity = producer.get("economic_task", {})
    if (producer.get("result_digest") != manifest["producer_result_digest"]
        or digest({k: v for k, v in producer.items() if k != "result_digest"}) != producer["result_digest"]
        or qa.get("receipt_digest") != manifest["numerical_qa_receipt_digest"]
        or digest({k: v for k, v in qa.items() if k != "receipt_digest"}) != qa["receipt_digest"]
        or qa.get("producer_result_digest") != producer["result_digest"]
        or identity != {"task_id": task, "producer": "research-agent", "lane": "github-cloud",
                        "source_sha": manifest["execution_source_sha"], "workflow_run_id": manifest["workflow_run_id"]}
        or qa.get("task_id") != task or qa.get("verifier_source_sha") != manifest["execution_source_sha"]
        or qa.get("status") != "DONE_NUMERICAL_QA" or qa.get("verifier") != "qa-verifier-agent"
        or qa.get("independent_signal_equations_verified") is not True
        or qa.get("independent_execution_arithmetic_verified") is not True
        or qa.get("feature_engine_shared_with_producer") is not True
        or producer.get("complete_system_digest") != digest(system)
        or producer.get("execution_contract") != system.get("execution_contract")
        or producer.get("historical_source_already_inspected") is not True
        or producer.get("independent_untouched_future_holdout") is not False
        or qa.get("prospective_holdout") is not False
        or producer.get("all_params_fixed_no_tuning") is not True):
        raise EconomicReviewError("economic producer and original numerical QA do not bind")
    for value in (producer, qa):
        if (any(value.get(k) is not False for k in ("paper_eligible", "demo_eligible", "live_enabled"))
            or type(value.get("orders")) is not int or value["orders"] != 0):
            raise EconomicReviewError("economic evidence claims execution authority")
    if (producer.get("qualified") is not False or type(producer.get("real_exchange_orders")) is not int
        or producer["real_exchange_orders"] != 0
        or qa.get("economic_edge_established") is not False):
        raise EconomicReviewError("historical evidence is not economic admission")
    rows = []
    if set(producer["partitions"]) != set(PARTITIONS) or set(qa["partitions"]) != set(PARTITIONS):
        raise EconomicReviewError("economic partitions are missing")
    fields = ("gross_price_pnl_usdt", "total_friction_usdt", "net_pnl_usdt",
              "ending_shared_cash_usdt", "max_drawdown_pct")
    for part in PARTITIONS:
        if set(producer["partitions"][part]) != set(COSTS) or set(qa["partitions"][part]) != set(COSTS):
            raise EconomicReviewError("economic cost scenarios are missing")
        for cost in COSTS:
            p, q = producer["partitions"][part][cost], qa["partitions"][part][cost]
            ledger, count = p["ledger"], p["trades"]
            if type(ledger) is not list or type(count) is not int or not 0 <= count == len(ledger) <= 1000 or q["trades"] != count:
                raise EconomicReviewError("closed-position count disagrees")
            for key in fields:
                _equal(p[key], q[key])
            _equal(p["initial_shared_cash_usdt"], 500.)
            _equal(p["ending_shared_cash_usdt"], 500. + p["net_pnl_usdt"])
            _equal(p["gross_price_pnl_usdt"] - p["total_friction_usdt"], p["net_pnl_usdt"])
            _equal(p["fees_paid_usdt"] + p["slippage_usdt"], p["total_friction_usdt"])
            _equal(sum(_number(t["pnl_usdt"]) for t in ledger), p["net_pnl_usdt"])
            _equal(sum(_number(t["gross_price_pnl_usdt"]) for t in ledger), p["gross_price_pnl_usdt"])
            _equal(sum(_number(t["entry_fee_usdt"]) + _number(t["exit_fee_usdt"]) for t in ledger), p["fees_paid_usdt"])
            _equal(sum(_number(t["slippage_usdt"]) for t in ledger), p["slippage_usdt"])
            if count:
                _equal(p["mean_pnl_usdt"], p["net_pnl_usdt"] / count)
                _equal(p["mean_pnl_usdt"], q["mean_pnl_usdt"])
            elif p["mean_pnl_usdt"] is not None or q["mean_pnl_usdt"] is not None:
                raise EconomicReviewError("zero activity has no mean closed-position PNL")
            rows.append({"partition": part, "cost_profile": cost, "trades": count,
                         **{k: p[k] for k in (*fields, "fees_paid_usdt", "slippage_usdt", "mean_pnl_usdt")}})
    status = disposition(rows)
    if qa.get("disposition") != status:
        raise EconomicReviewError("economic disposition disagrees with preserved numbers")
    summary = {"economic_task_id": task, "execution_source_sha": manifest["execution_source_sha"],
               "workflow_run_id": manifest["workflow_run_id"], "producer_result_digest": producer["result_digest"],
               "numerical_qa_receipt_digest": qa["receipt_digest"], "disposition": status, "partitions": rows,
               "shared_initial_cash_usdt": 500., "cash_reset_per_partition": True,
               "historical_source_already_inspected": True, "untouched_future_evidence": False,
               "original_numerical_qa_reused": True, "replay_authorized": False,
               "promotion_authorized": False, **BOUNDARIES}
    return manifest, raw, summary


def task_binding(relative: str, root: Path | None = None) -> dict:
    root = root or ROOT
    manifest, raw, _ = load_evidence(relative, root)
    core = {"schema": TASK_SCHEMA, "manifest_path": relative, "manifest_sha256": _sha(raw),
            "economic_task_id": manifest["economic_task_id"],
            "review_source_sha256": {p: _sha(_raw(root, p, re.escape(p))) for p in CODE}}
    return dict(core, id=PREFIX + digest(core)[:32])


def validate_binding(binding: Any) -> None:
    if (type(binding) is not dict or set(binding) != {"schema", "manifest_path", "manifest_sha256",
                                                    "economic_task_id", "review_source_sha256", "id"}
        or binding.get("schema") != TASK_SCHEMA
        or type(binding.get("manifest_path")) is not str
        or not re.fullmatch(re.escape(DIRECTORY) + r"/[a-z0-9_]+\.json", binding["manifest_path"])
        or type(binding.get("manifest_sha256")) is not str or not HEX64.fullmatch(binding["manifest_sha256"])
        or type(binding.get("economic_task_id")) is not str
        or not re.fullmatch(r"SYSTEM-ECON-[0-9a-f]{24}", binding["economic_task_id"])
        or type(binding.get("review_source_sha256")) is not dict or set(binding["review_source_sha256"]) != set(CODE)
        or any(type(v) is not str or not HEX64.fullmatch(v) for v in binding["review_source_sha256"].values())
        or binding.get("id") != PREFIX + digest({k: v for k, v in binding.items() if k != "id"})[:32]):
        raise EconomicReviewError("economic review binding is invalid")


def materialize_reviews(definition: Mapping[str, Any], root: Path | None = None) -> dict:
    root = root or ROOT
    result = deepcopy(dict(definition))
    directory = root / DIRECTORY
    if not directory.exists():
        return result
    if directory.is_symlink() or not directory.is_dir():
        raise EconomicReviewError("economic review directory is unsafe")
    paths = sorted(directory.iterdir())
    if len(paths) > 16:
        raise EconomicReviewError("economic review batch exceeds bound")
    for path in paths:
        relative = path.relative_to(root).as_posix()
        try:
            binding = task_binding(relative, root)
            task = {"id": binding["id"], "title": "Review completed source-system economics: " + path.stem,
                    "phase": 7, "gate": 17, "status": "READY", "priority": 95, "dependencies": [],
                    "required_capabilities": ["data_validation", "diagnostics"],
                    "required_resources": ["github-cloud"], "preferred_resources": ["github-cloud"], "authority": 2,
                    "acceptance": ["Import the exact completed economic result and original numerical QA",
                                   "Separate evidence QA binds the Research import lease and preserved outcome",
                                   "DONE means evidence ingestion, not profitability or a new market replay"],
                    "source_system_economic_review_task": binding}
        except (ValueError, OSError, KeyError, TypeError) as exc:
            task = {"id": "ECON-EVIDENCE-BLOCKED-" + digest({"path": relative})[:32],
                    "title": "Correct incomplete completed-study evidence: " + path.stem,
                    "phase": 7, "gate": 17, "status": "BLOCKED", "priority": 95, "dependencies": [],
                    "required_capabilities": [], "required_resources": ["github-cloud"], "authority": 2,
                    "acceptance": ["Restore exact committed finished-study identities; never replay as recovery"],
                    "blocked_reason": str(exc)[:600], "failure_class": "invalid_economic_review_evidence"}
        prior = [t for t in result["tasks"] if t.get("id") == task["id"]]
        if prior and prior != [task]:
            raise EconomicReviewError("economic review task collides with definition")
        if not prior:
            result["tasks"].append(task)
    return result


def verify_receipt(receipt: Any, binding: dict, *, lease_id: str, role: str,
                   original: dict | None = None, root: Path | None = None) -> None:
    root = root or ROOT
    validate_binding(binding)
    keys = {"schema", "task_id", "binding_digest", "source_sha", "lease_id", "worker_id", "role",
            "summary", "summary_digest", "producer_receipt_digest", "producer_lease_id",
            "independent_evidence_import_qa_complete", "receipt_digest", *BOUNDARIES}
    if (role not in {"producer", "independent-qa"} or type(receipt) is not dict or set(receipt) != keys
        or receipt.get("schema") != RECEIPT_SCHEMA or receipt.get("task_id") != binding["id"]
        or receipt.get("binding_digest") != digest(binding) or receipt.get("role") != role
        or type(lease_id) is not str or not 1 <= len(lease_id) <= 160 or receipt.get("lease_id") != lease_id
        or receipt.get("worker_id") != ("research-agent" if role == "producer" else "qa-verifier-agent")
        or type(receipt.get("source_sha")) is not str or not HEX40.fullmatch(receipt["source_sha"])
        or any(receipt.get(k) is not v for k, v in BOUNDARIES.items())
        or receipt.get("independent_evidence_import_qa_complete") is not (role == "independent-qa")
        or receipt.get("receipt_digest") != digest({k: v for k, v in receipt.items() if k != "receipt_digest"})
        or task_binding(binding["manifest_path"], root) != binding):
        raise EconomicReviewError("economic review receipt or imported code identity is invalid")
    _, _, expected = load_evidence(binding["manifest_path"], root)
    if receipt["summary"] != expected or receipt["summary_digest"] != digest(expected):
        raise EconomicReviewError("review does not preserve the exact economic result")
    if role == "producer":
        if receipt["producer_receipt_digest"] is not None or receipt["producer_lease_id"] is not None:
            raise EconomicReviewError("Research import cannot claim prior independent verification")
    elif isinstance(original, dict):
        verify_receipt(original, binding, lease_id=original.get("lease_id"), role="producer", root=root)
        if (original["lease_id"] == lease_id or receipt["producer_lease_id"] != original["lease_id"]
            or receipt["producer_receipt_digest"] != original["receipt_digest"]
            or receipt["summary_digest"] != original["summary_digest"]):
            raise EconomicReviewError("economic review QA must bind a distinct exact Research lease")
    else:
        raise EconomicReviewError("economic review QA requires the original Research import")


def run_review(payload: Mapping[str, Any], *, source_sha: str, root: Path | None = None) -> dict:
    root = root or ROOT
    binding = payload["source_system_economic_review_task"]
    validate_binding(binding)
    role = "independent-qa" if payload.get("worker_id") == "qa-verifier-agent" else "producer"
    if (payload.get("task_id") != binding["id"] or payload.get("phase") != 7
        or payload.get("gate") != 17 or payload.get("authority") != 2
        or payload.get("transport") != "github-cloud"
        or payload.get("worker_id") not in {"research-agent", "qa-verifier-agent"}
        or type(source_sha) is not str or not HEX40.fullmatch(source_sha)):
        raise EconomicReviewError("economic review worker or authority route is invalid")
    _, _, summary = load_evidence(binding["manifest_path"], root)
    original = payload.get("source_system_economic_review_producer")
    if role == "producer" and original is not None:
        raise EconomicReviewError("Research import cannot carry QA evidence")
    receipt = {"schema": RECEIPT_SCHEMA, "task_id": binding["id"], "binding_digest": digest(binding),
               "source_sha": source_sha, "lease_id": payload["lease_id"], "worker_id": payload["worker_id"],
               "role": role, "summary": summary, "summary_digest": digest(summary),
               "producer_receipt_digest": original.get("receipt_digest") if isinstance(original, dict) else None,
               "producer_lease_id": original.get("lease_id") if isinstance(original, dict) else None,
               "independent_evidence_import_qa_complete": role == "independent-qa", **BOUNDARIES}
    receipt["receipt_digest"] = digest(receipt)
    verify_receipt(receipt, binding, lease_id=payload["lease_id"], role=role, original=original, root=root)
    return receipt


def summarize_reviews(tasks: list[dict]) -> dict:
    completed = []
    for task in tasks:
        if is_review(task) and task.get("status") == "DONE":
            producer, qa = task.get("result_evidence"), task.get("verification_evidence")
            if (task.get("producer") != "research-agent" or task.get("verifier") != "qa-verifier-agent"
                or not isinstance(qa, dict)):
                raise EconomicReviewError("DONE economic review lacks separate worker evidence")
            verify_receipt(qa, task["source_system_economic_review_task"], lease_id=task["lease_id"],
                           role="independent-qa", original=producer)
            completed.append({"review_task_id": task["id"], "verified_at": task.get("verified_at"),
                              **qa["summary"]})
    completed.sort(key=lambda row: (str(row["verified_at"]), row["review_task_id"]), reverse=True)
    return {"scope": "completed_study_evidence_ingestion_not_economic_qualification",
            "completed": len(completed), "latest": completed[0] if completed else None,
            "market_replay_performed": False, "economic_edge_established": False,
            "paper_eligible": False, "live_enabled": False}
