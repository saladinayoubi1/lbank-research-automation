"""Bounded Developer implementation of committed, explicit research systems.

The coordinator uses only stdlib. Numerical imports are confined to the worker.
This compiler implements supplied rules; it cannot interpret an incomplete web
article, approve a market replay, or attest economic/semantic independence.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import re
import tempfile
from typing import Any, Mapping

from nexus_complete_strategy_system import BINDINGS, EXECUTOR_FILES, ROOTS, _read, digest

ROOT = Path(__file__).resolve().parent
REQUEST_DIR = "research/system_development_requests"
SCHEMA = "nexus.source-system-development-request.v1"
TASK_SCHEMA = "nexus.source-system-development-task.v1"
RECEIPT_SCHEMA = "nexus.source-system-development-receipt.v1"
PREFIX = "SYSTEM-DEV-"
IMPLEMENTATION_FILES = (*EXECUTOR_FILES, "nexus_complete_strategy_system.py",
                        "nexus_source_system_development.py", "research/mechanism_factory_v1.json",
                        "requirements.lock", "requirements-dev.lock")
BOUNDARIES = {"research_only": True, "paper_eligible": False, "live_enabled": False,
              "automatic_strategy_promotion": False}
UNPROVEN = {"economic_edge_established": False, "semantic_overlap_review_complete": False,
            "external_source_interpretation_attested": False, "market_replay_performed": False,
            "research_execution_approved": False}
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
HEX40 = re.compile(r"[0-9a-f]{40}\Z")
IDENT = re.compile(r"[a-z][a-z0-9_]{2,72}\Z")


class SystemDevelopmentError(ValueError):
    pass


def is_development(task: Mapping[str, Any]) -> bool:
    return isinstance(task.get("id"), str) and task["id"].startswith(PREFIX)


def _raw(root: Path, relative: str, pattern: str, limit: int = 100_000) -> bytes:
    if not isinstance(relative, str) or not re.fullmatch(pattern, relative):
        raise SystemDevelopmentError("unsupported committed implementation input path")
    path = root / relative
    if any(p.is_symlink() for p in (root, path, *path.parents)):
        raise SystemDevelopmentError("linked implementation input is forbidden")
    if not path.is_file() or not 0 < path.stat().st_size <= limit:
        raise SystemDevelopmentError("missing or oversized implementation input")
    return path.read_bytes()


def _object(raw: bytes) -> dict[str, Any]:
    def pairs(items):
        obj = {}
        for key, val in items:
            if key in obj:
                raise SystemDevelopmentError("duplicate implementation JSON field")
            obj[key] = val
        return obj
    try:
        obj = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                         parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, UnicodeError) as exc:
        raise SystemDevelopmentError("invalid implementation JSON") from exc
    if type(obj) is not dict:
        raise SystemDevelopmentError("implementation input must be an object")
    return obj


def _hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def source_identity(root: Path) -> dict[str, str]:
    return {p: _hash(_raw(root, p, re.escape(p), 2_000_000)) for p in IMPLEMENTATION_FILES}


def load_request(root: Path, relative: str) -> tuple[dict[str, Any], bytes]:
    raw = _raw(root, relative, re.escape(REQUEST_DIR) + r"/[a-z0-9_]+\.json")
    obj = _object(raw)
    expected = {"schema", "id", "implementation", "candidate_path", "candidate_sha256",
                "source_notes", "rule_bindings", "execution_contract", "study_window",
                "selection_basis", *BOUNDARIES}
    if (set(obj) != expected or obj.get("schema") != SCHEMA
        or not isinstance(obj.get("id"), str) or not IDENT.fullmatch(obj["id"])
        or obj.get("implementation") != "existing_factory_shared_cash_v1"
        or any(obj.get(k) is not v for k, v in BOUNDARIES.items())
        or obj.get("selection_basis") != "one_frozen_hypothesis_no_posthoc_tournament"):
        raise SystemDevelopmentError("incomplete implementation request or changed authority")
    candidate = _raw(root, obj["candidate_path"], r"research/intake_candidates/[a-z0-9_-]+\.json")
    if _hash(candidate) != obj["candidate_sha256"]:
        raise SystemDevelopmentError("implementation candidate SHA is stale")
    notes = obj["source_notes"]
    if type(notes) is not list or not 1 <= len(notes) <= 8:
        raise SystemDevelopmentError("bounded implementation source notes required")
    ids = set()
    for note in notes:
        if (type(note) is not dict or set(note) != {"id", "path", "sha256", "url"}
            or not isinstance(note["id"], str) or not IDENT.fullmatch(note["id"])
            or note["id"] in ids):
            raise SystemDevelopmentError("invalid implementation source binding")
        body, sha = _read(root, note["path"], "source")
        if sha != note["sha256"] or body.get("source_url") != note["url"]:
            raise SystemDevelopmentError("implementation source note changed")
        ids.add(note["id"])
    rules = obj["rule_bindings"]
    if type(rules) is not dict or set(rules) != set(BINDINGS):
        raise SystemDevelopmentError("all five explicit trading-system components required")
    for name, binding in BINDINGS.items():
        rule = rules[name]
        if (type(rule) is not dict or set(rule) != {"implementation", "origin", "source_ids", "summary"}
            or rule.get("implementation") != binding
            or type(rule.get("origin")) is not str
            or rule.get("origin") not in ("source", "research_extension")
            or type(rule.get("source_ids")) is not list
            or any(type(x) is not str or x not in ids for x in rule["source_ids"])
            or type(rule.get("summary")) is not str or not 40 <= len(rule["summary"]) <= 2000):
            raise SystemDevelopmentError("unsupported or unspecified implementation rule")
    window = obj["study_window"]
    if type(window) is not dict or set(window) != {"warmup_utc", "start_utc", "end_exclusive_utc"}:
        raise SystemDevelopmentError("frozen implementation study window required")
    try:
        warm, start, end = (datetime.fromisoformat(window[k].replace("Z", "+00:00"))
                            for k in ("warmup_utc", "start_utc", "end_exclusive_utc"))
        if (any(t.utcoffset() != timedelta(0) or t.timestamp() % 900 for t in (warm, start, end))
            or not warm < start < end or start - warm < timedelta(days=25)
            or end - start < timedelta(days=30) or end - warm > timedelta(days=150)):
            raise ValueError()
    except (ValueError, TypeError, AttributeError, OverflowError) as exc:
        raise SystemDevelopmentError("unsupported frozen implementation study window") from exc
    if type(obj["execution_contract"]) is not dict:
        raise SystemDevelopmentError("explicit execution profile required")
    return obj, raw


def task_binding(root: Path, relative: str) -> dict[str, Any]:
    obj, raw = load_request(root, relative)
    binding = {"schema": TASK_SCHEMA, "request_path": relative, "request_sha256": _hash(raw),
               "implementation_source_sha256": source_identity(root),
               "candidate_sha256": obj["candidate_sha256"],
               "source_note_sha256": {n["path"]: n["sha256"] for n in obj["source_notes"]}}
    return dict(binding, id=PREFIX + digest(binding)[:32])


def validate_binding(binding: Mapping[str, Any]) -> None:
    if type(binding) is not dict or set(binding) != {
        "schema", "request_path", "request_sha256", "implementation_source_sha256",
        "candidate_sha256", "source_note_sha256", "id",
    }:
        raise SystemDevelopmentError("implementation task binding schema mismatch")
    core = {k: v for k, v in binding.items() if k != "id"}
    if binding.get("schema") != TASK_SCHEMA or binding.get("id") != PREFIX + digest(core)[:32]:
        raise SystemDevelopmentError("implementation task identity mismatch")
    if (not isinstance(binding["request_path"], str)
        or not re.fullmatch(re.escape(REQUEST_DIR) + r"/[a-z0-9_]+\.json", binding["request_path"])
        or any(not isinstance(binding[k], str) or not HEX64.fullmatch(binding[k])
               for k in ("request_sha256", "candidate_sha256"))):
        raise SystemDevelopmentError("invalid implementation task path or SHA")
    sources, notes = binding["implementation_source_sha256"], binding["source_note_sha256"]
    if (type(sources) is not dict or set(sources) != set(IMPLEMENTATION_FILES)
        or type(notes) is not dict or not 1 <= len(notes) <= 8
        or any(not re.fullmatch(r"research/source_notes/[a-z0-9_-]+\.json", k) for k in notes)
        or any(not isinstance(v, str) or not HEX64.fullmatch(v) for v in (*sources.values(), *notes.values()))):
        raise SystemDevelopmentError("incomplete implementation code/source identities")


def materialize_development_tasks(definition: Mapping[str, Any], root: Path = ROOT) -> dict[str, Any]:
    result = deepcopy(dict(definition))
    directory = root / REQUEST_DIR
    if not directory.exists():
        return result
    if directory.is_symlink() or not directory.is_dir():
        raise SystemDevelopmentError("implementation request directory is unsafe")
    paths = sorted(directory.iterdir())
    if len(paths) > 16:
        raise SystemDevelopmentError("implementation request batch exceeds bound")
    for path in paths:
        relative = path.relative_to(root).as_posix()
        try:
            binding = task_binding(root, relative)
        except (ValueError, OSError) as exc:
            # An incomplete source proposal blocks only its own work. Other
            # Research/QA tasks must continue through the existing coordinator.
            raw = _hash(path.read_bytes()) if (
                not path.is_symlink() and path.is_file() and path.stat().st_size <= 100_000
            ) else None
            blocked = {
                "id": "SYSTEM-SPEC-BLOCKED-" + digest({"path": relative, "sha256": raw})[:32],
                "title": "Complete implementation specification required for " + path.stem,
                "phase": 7, "gate": 17, "status": "BLOCKED", "priority": 94,
                "dependencies": [], "required_capabilities": [],
                "required_resources": ["github-cloud"], "authority": 2,
                "acceptance": ["A corrected committed complete-system request is required"],
                "blocked_reason": str(exc)[:600], "failure_class": "incomplete_system_development_request",
            }
            prior = [t for t in result["tasks"] if t.get("id") == blocked["id"]]
            if prior and prior != [blocked]:
                raise SystemDevelopmentError("blocked implementation task collides with definition")
            if not prior:
                result["tasks"].append(blocked)
            continue
        task = {
            "id": binding["id"], "title": "Implement complete source-linked research system " + path.stem,
            "phase": 7, "gate": 17, "status": "READY", "priority": 94, "dependencies": [],
            "required_capabilities": ["unit_tests", "diagnostics"],
            "required_resources": ["github-cloud"], "preferred_resources": ["github-cloud"],
            "authority": 2,
            "acceptance": ["Produce actual complete-system JSON and unchanged executable candidate bytes",
                           "Separate QA reproduces the exact committed-input implementation artifact",
                           "Market replay, semantic review, qualification and Demo remain separate"],
            "source_system_development_task": binding,
        }
        prior = [t for t in result["tasks"] if t.get("id") == task["id"]]
        if prior and prior != [task]:
            raise SystemDevelopmentError("implementation task collides with existing definition")
        if not prior:
            result["tasks"].append(task)
    return result


def compile_system(binding: dict[str, Any], root: Path = ROOT) -> dict[str, Any]:
    """Generate real reviewable executor inputs, without opening market files."""
    validate_binding(binding)
    if task_binding(root, binding["request_path"]) != binding or source_identity(ROOT) != source_identity(root):
        raise SystemDevelopmentError("implementation inputs differ from the actual imported code")
    obj, _ = load_request(root, binding["request_path"])
    from research.strategy_finder_shared_cash_physical import execution_contract
    from scripts.nexus_strategy_finder_executable_intake import inspect_candidate, _load_json_strict, DEFAULT_ALLOWLIST
    from nexus_complete_strategy_system import SCHEMA as COMPLETE_SCHEMA, implementation_hashes, validate_system
    if obj["execution_contract"] != execution_contract():
        raise SystemDevelopmentError("unsupported requested execution requires actual code implementation")
    # Reading the existing review registry cannot grant this compiler approval.
    readiness = inspect_candidate(root, obj["candidate_path"], _load_json_strict(root / DEFAULT_ALLOWLIST, 200_000))
    if readiness["status"].startswith("REJECT_"):
        raise SystemDevelopmentError("candidate rejected by existing intake: " + readiness["status"])
    candidate = {k: readiness[k] for k in ("candidate_id", "candidate_path", "candidate_sha256",
                                           "original_factory_contract_digest")}
    system = {"schema": COMPLETE_SCHEMA, "candidate": candidate,
              **{k: obj[k] for k in ("source_notes", "rule_bindings", "execution_contract", "study_window",
                                     "selection_basis", *BOUNDARIES)},
              "execution_source_sha256": implementation_hashes(ROOT)}
    relative = ROOTS["system"] + "/" + obj["id"] + ".json"
    files = {obj["candidate_path"]: (root / obj["candidate_path"]).read_text(encoding="utf-8"),
             relative: json.dumps(system, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n"}
    # Validate the emitted bytes through the actual existing complete-system gate.
    # This ephemeral binding is not a review registry entry and is never published as approval.
    with tempfile.TemporaryDirectory(prefix="nexus-system-implementation-") as folder:
        stage = Path(folder)
        for name in (*EXECUTOR_FILES, *(n["path"] for n in obj["source_notes"])):
            out = stage / name; out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes((root / name).read_bytes())
        for name, content in files.items():
            out = stage / name; out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(content.encode("utf-8"))
        validate_system(stage, candidate, {
            "system_specification_path": relative,
            "system_specification_sha256": _hash(files[relative].encode()),
            "execution_contract_digest": digest(execution_contract()),
        }, execution_contract())
    return {"files": files, "file_sha256": {p: _hash(s.encode()) for p, s in files.items()},
            "candidate": candidate, "system_specification_path": relative,
            "system_digest": digest(system), "execution_contract_digest": digest(execution_contract()),
            "review_required": True, **BOUNDARIES, **UNPROVEN}


def verify_receipt(receipt: Any, binding: dict[str, Any], *, lease_id: str,
                   role: str, original: dict[str, Any] | None = None) -> None:
    validate_binding(binding)
    expected = {"schema", "task_id", "binding_digest", "source_sha", "lease_id", "worker_id", "role",
                "bundle", "bundle_digest", "producer_receipt_digest", "producer_lease_id",
                "independent_implementation_qa_complete", "receipt_digest", *BOUNDARIES, *UNPROVEN}
    if (role not in {"producer", "independent-qa"}
        or type(receipt) is not dict or set(receipt) != expected
        or receipt.get("schema") != RECEIPT_SCHEMA or receipt.get("task_id") != binding["id"]
        or receipt.get("binding_digest") != digest(binding)
        or receipt.get("lease_id") != lease_id or type(lease_id) is not str or not 1 <= len(lease_id) <= 160
        or receipt.get("role") != role
        or receipt.get("worker_id") != ("developer-agent" if role == "producer" else "qa-verifier-agent")
        or type(receipt.get("source_sha")) is not str or not HEX40.fullmatch(receipt["source_sha"])
        or any(receipt.get(k) is not v for k, v in {**BOUNDARIES, **UNPROVEN}.items())
        or receipt.get("independent_implementation_qa_complete") is not (role == "independent-qa")
        or receipt.get("receipt_digest") != digest({k: v for k, v in receipt.items() if k != "receipt_digest"})
        or type(receipt.get("bundle")) is not dict or receipt.get("bundle_digest") != digest(receipt["bundle"])):
        raise SystemDevelopmentError("invalid source-system implementation receipt")
    bundle = receipt["bundle"]
    files = bundle.get("files")
    if (bundle.get("review_required") is not True
        or any(bundle.get(k) is not v for k, v in {**BOUNDARIES, **UNPROVEN}.items())
        or type(files) is not dict or len(files) != 2
        or any(type(p) is not str or type(s) is not str or not s for p, s in files.items())
        or bundle.get("file_sha256") != {p: _hash(s.encode()) for p, s in files.items()}
        or type(bundle.get("candidate")) is not dict
        or bundle["candidate"].get("candidate_sha256") != binding["candidate_sha256"]
        or set(files) != {bundle["candidate"].get("candidate_path"), bundle.get("system_specification_path")}
        or not re.fullmatch(r"research/intake_candidates/[a-z0-9_-]+\.json", bundle["candidate"]["candidate_path"])
        or not re.fullmatch(r"research/complete_systems/[a-z0-9_]+\.json", bundle["system_specification_path"])
        or bundle["file_sha256"][bundle["candidate"]["candidate_path"]] != binding["candidate_sha256"]
        or len(json.dumps(bundle)) > 36_000):
        raise SystemDevelopmentError("implementation receipt has no bounded executable artifact")
    if role == "producer":
        if receipt["producer_receipt_digest"] is not None or receipt["producer_lease_id"] is not None:
            raise SystemDevelopmentError("producer cannot claim prior independent verification")
    elif role == "independent-qa" and original is not None:
        verify_receipt(original, binding, lease_id=original.get("lease_id"), role="producer")
        if (original["lease_id"] == lease_id or receipt["bundle"] != original["bundle"]
            or receipt["producer_lease_id"] != original["lease_id"]
            or receipt["producer_receipt_digest"] != original["receipt_digest"]):
            raise SystemDevelopmentError("independent implementation QA does not bind the exact producer")
    else:
        raise SystemDevelopmentError("independent implementation QA requires original producer evidence")


def run_development(payload: Mapping[str, Any], *, source_sha: str, root: Path = ROOT) -> dict[str, Any]:
    binding = payload["source_system_development_task"]
    validate_binding(binding)
    role = "independent-qa" if payload.get("worker_id") == "qa-verifier-agent" else "producer"
    if (payload.get("task_id") != binding["id"] or payload.get("phase") != 7
        or payload.get("gate") != 17 or payload.get("transport") != "github-cloud"
        or payload.get("authority") != 2 or payload.get("worker_id") not in {"developer-agent", "qa-verifier-agent"}
        or not HEX40.fullmatch(source_sha)):
        raise SystemDevelopmentError("invalid Developer or independent QA lease route")
    original = payload.get("source_system_development_producer")
    if role == "independent-qa":
        if type(original) is not dict:
            raise SystemDevelopmentError("original implementation producer receipt required")
        verify_receipt(original, binding, lease_id=original.get("lease_id"), role="producer")
    elif original is not None:
        raise SystemDevelopmentError("producer lease cannot carry QA evidence")
    bundle = compile_system(binding, root)
    receipt = {"schema": RECEIPT_SCHEMA, "task_id": binding["id"], "binding_digest": digest(binding),
               "source_sha": source_sha, "lease_id": payload["lease_id"], "worker_id": payload["worker_id"],
               "role": role, "bundle": bundle, "bundle_digest": digest(bundle),
               "producer_receipt_digest": original["receipt_digest"] if original else None,
               "producer_lease_id": original["lease_id"] if original else None,
               "independent_implementation_qa_complete": role == "independent-qa", **BOUNDARIES, **UNPROVEN}
    receipt["receipt_digest"] = digest(receipt)
    verify_receipt(receipt, binding, lease_id=payload["lease_id"], role=role, original=original)
    return receipt
