"""Complete, source-linked system contract for the existing reviewed research intake.

Source notes are bounded human/research paraphrases, not authenticated provider
payloads. Their hashes establish identity only. Separate repository review must
substantiate source interpretation and every declared research extension.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping
from urllib.parse import urlsplit

SCHEMA = "nexus.complete-strategy-system.v1"
SOURCE_SCHEMA = "nexus.strategy-source-note.v1"
ROOTS = {"system":"research/complete_systems", "source":"research/source_notes"}
EXECUTOR_FILES = (
    "nexus_mechanism_factory.py", "nexus_composite_strategy_research.py",
    "research/strategy_finder_shared_cash_physical.py",
    "scripts/nexus_strategy_finder_executable_intake.py",
    "scripts/nexus_strategy_finder_shared_cash_eval.py",
    "nexus_multitimeframe_verified_archive_discovery.py",
)
BINDINGS = {
    "context":"factory_context", "entry":"factory_entry",
    "exit":"shared_cash_stop_target_timeout", "sizing":"shared_cash_cost_aware_size",
    "no_trade":"shared_cash_denial_rules",
}
REVIEW_FIELDS = {"system_specification_path", "system_specification_sha256",
                 "execution_contract_digest"}
HEX64 = re.compile(r"^[0-9a-f]{64}$")


class CompleteSystemError(ValueError):
    pass


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _pairs(items):
    value = {}
    for key, item in items:
        if key in value:
            raise CompleteSystemError("duplicate JSON field in complete-system evidence")
        value[key] = item
    return value


def _read(root: Path, relative: str, kind: str) -> tuple[dict[str, Any], str]:
    if not isinstance(relative, str) or not re.fullmatch(
        re.escape(ROOTS[kind]) + r"/[a-z0-9_-]+\.json", relative,
    ):
        raise CompleteSystemError("system/source note must be a committed bounded JSON path")
    path = root / relative
    if (any(part.is_symlink() for part in (root, path.parent.parent, path.parent, path))
        or not path.is_file() or not 0 < path.stat().st_size <= 100_000):
        raise CompleteSystemError("system/source note is missing, linked, or oversized")
    raw = path.read_bytes()
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs)
    except (ValueError, UnicodeError) as exc:
        raise CompleteSystemError("system/source note is unreadable") from exc
    if type(value) is not dict:
        raise CompleteSystemError("system/source note must be an object")
    return value, hashlib.sha256(raw).hexdigest()


def implementation_hashes(root: Path) -> dict[str, str]:
    result = {}
    for relative in EXECUTOR_FILES:
        path = root / relative
        if path.is_symlink() or path.parent.is_symlink() or not path.is_file():
            raise CompleteSystemError("complete-system executor source is missing or linked")
        result[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def validate_system(root: Path, candidate: Mapping[str, Any], permit: Mapping[str, Any],
                    execution: Mapping[str, Any]) -> dict[str, Any]:
    """No implicit exits/risk: bind one reviewed complete system to actual code."""
    if not REVIEW_FIELDS <= set(permit):
        raise CompleteSystemError("complete-system specification has not been separately reviewed")
    relative = permit["system_specification_path"]
    value, rawsha = _read(root, relative, "system")
    if rawsha != permit["system_specification_sha256"]:
        raise CompleteSystemError("complete-system review SHA is stale")
    required = {"schema", "candidate", "source_notes", "rule_bindings", "execution_contract",
                "execution_source_sha256", "study_window", "selection_basis", "research_only",
                "paper_eligible", "live_enabled", "automatic_strategy_promotion"}
    if set(value) != required or value.get("schema") != SCHEMA:
        raise CompleteSystemError("incomplete or unsupported complete-system specification")
    expected_candidate = {key:candidate[key] for key in (
        "candidate_id", "candidate_path", "candidate_sha256", "original_factory_contract_digest",
    )}
    if value["candidate"] != expected_candidate:
        raise CompleteSystemError("complete-system candidate binding mismatch")
    if (value["execution_contract"] != dict(execution)
        or permit["execution_contract_digest"] != digest(dict(execution))):
        raise CompleteSystemError("unsupported exit/risk contract requires implementation review")
    # A caller's data/spec root is not proof of the code actually imported.
    # A reviewed copy of different source files cannot stand in for this runtime.
    actual_sources = implementation_hashes(Path(__file__).resolve().parent)
    if (implementation_hashes(root) != actual_sources
        or value["execution_source_sha256"] != actual_sources):
        raise CompleteSystemError("complete-system executor code changed after review")
    if (value["selection_basis"] != "one_frozen_hypothesis_no_posthoc_tournament"
        or value["research_only"] is not True or value["paper_eligible"] is not False
        or value["live_enabled"] is not False or value["automatic_strategy_promotion"] is not False):
        raise CompleteSystemError("complete-system selection or authority boundary changed")
    notes = value["source_notes"]
    if not isinstance(notes, list) or not 1 <= len(notes) <= 8:
        raise CompleteSystemError("complete system requires bounded source-linked notes")
    source_ids, coverage = set(), {}
    for note in notes:
        if (type(note) is not dict or set(note) != {"id", "path", "sha256", "url"}
            or not isinstance(note["id"], str) or not re.fullmatch(r"[a-z0-9_-]{1,60}", note["id"])
            or note["id"] in source_ids):
            raise CompleteSystemError("source note identity is missing or duplicated")
        if not isinstance(note["url"], str):
            raise CompleteSystemError("source URL is missing")
        parsed = urlsplit(note["url"])
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise CompleteSystemError("source note must identify a public HTTPS research source")
        body, notedigest = _read(root, note["path"], "source")
        if (notedigest != note["sha256"] or body.get("schema") != SOURCE_SCHEMA
            or body.get("source_url") != note["url"]
            or body.get("content_kind") != "research_paraphrase_not_provider_raw_bytes"
            or body.get("provider_authentication_verified") is not False):
            raise CompleteSystemError("source note digest, origin, or evidence scope mismatch")
        source_ids.add(note["id"])
        coverage[note["id"]] = body.get("coverage", {})
    rules = value["rule_bindings"]
    if type(rules) is not dict or set(rules) != set(BINDINGS):
        raise CompleteSystemError("complete system must specify context, entry, exit, sizing and no-trade")
    for name, implementation in BINDINGS.items():
        rule = rules[name]
        if (type(rule) is not dict or set(rule) != {"implementation", "origin", "source_ids", "summary"}
            or rule["implementation"] != implementation
            or not isinstance(rule["origin"], str)
            or rule["origin"] not in {"source", "research_extension"}
            or not isinstance(rule["source_ids"], list)
            or any(not isinstance(item, str) for item in rule["source_ids"])
            or not set(rule["source_ids"]) <= source_ids
            or (rule["origin"] == "source" and not rule["source_ids"])
            or not isinstance(rule["summary"], str) or not 40 <= len(rule["summary"]) <= 2000):
            raise CompleteSystemError("source-to-executable rule mapping is incomplete or unsupported")
        if rule["origin"] == "source" and not any(
            isinstance(coverage[ident], Mapping)
            and isinstance(coverage[ident].get(name), str) and coverage[ident][name].strip()
            for ident in rule["source_ids"]
        ):
            raise CompleteSystemError("source note does not substantiate the attributed rule")
    window = value["study_window"]
    if type(window) is not dict or set(window) != {"warmup_utc", "start_utc", "end_exclusive_utc"}:
        raise CompleteSystemError("complete-system study window must be frozen before execution")
    if any(not isinstance(item, str) or not item for item in window.values()):
        raise CompleteSystemError("complete-system study timestamps are missing")
    return {
        "schema":SCHEMA, "system_specification_path":relative,
        "system_specification_sha256":rawsha, "system_digest":digest(value),
        "execution_contract_digest":digest(dict(execution)),
        "execution_source_sha256":actual_sources,
        "source_notes":notes, "rule_bindings":rules, "study_window":window,
        "source_interpretation_independently_attested_here":False,
        "provider_authentication_verified":False,
        "paper_eligible":False, "live_enabled":False,
    }
