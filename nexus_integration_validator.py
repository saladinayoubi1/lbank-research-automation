"""Fail-closed validator for the canonical NEXUS integration graph."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
DEFAULT_REGISTRY = ROOT / "config" / "nexus-integration-registry.json"
MAX_BYTES = 256_000
STATUS_VOCABULARY = {"VERIFIED", "UNVERIFIED", "BLOCKED", "UNAVAILABLE"}
ROOT_KEYS = {"schema_version", "status", "scope", "live_trading", "nodes", "edges"}
NODE_KEYS = {"id", "type", "authority", "implementation", "tests"}
EDGE_KEYS = {"id", "producer", "consumer", "contract", "durable_state", "verifier", "evidence", "status"}
REQUIRED_PATH = [
    "mission", "supervisor", "router", "workers", "evidence", "independent_verifier",
    "canonical_data", "data_intelligence", "strategy_factory", "decision", "risk", "paper",
    "performance", "mission_control", "project_memory",
]


class IntegrationValidationError(ValueError):
    pass


def _exact_keys(value: dict[str, Any], expected: set[str], path: str) -> None:
    missing = expected - set(value)
    unknown = set(value) - expected
    if missing or unknown:
        raise IntegrationValidationError(
            f"{path} schema mismatch; missing={sorted(missing)}, unknown={sorted(unknown)}"
        )


def _mapping(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise IntegrationValidationError(f"{path} must be a string-keyed object")
    return value


def _nonempty_strings(value: Any, path: str) -> list[str]:
    if not isinstance(value, list) or not value or any(not isinstance(item, str) or not item for item in value):
        raise IntegrationValidationError(f"{path} must be a non-empty string list")
    if len(value) != len(set(value)):
        raise IntegrationValidationError(f"{path} contains duplicates")
    return value


def _repository_file(raw: str, path: str, root: Path) -> None:
    candidate = (root / raw).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise IntegrationValidationError(f"{path} escapes repository root") from exc
    if not candidate.is_file() or candidate.is_symlink():
        raise IntegrationValidationError(f"{path} does not reference a regular repository file: {raw}")


def validate_registry(payload: Any, root: Path = ROOT) -> None:
    registry = _mapping(payload, "registry")
    _exact_keys(registry, ROOT_KEYS, "registry")
    if registry["schema_version"] != 1:
        raise IntegrationValidationError("schema_version must equal 1")
    if registry["status"] != "accepted_maintenance_baseline":
        raise IntegrationValidationError("status must be accepted_maintenance_baseline")
    if registry["scope"] != "research_backtest_paper_only" or registry["live_trading"] is not False:
        raise IntegrationValidationError("registry must remain research/backtest/paper-only with live trading false")

    raw_nodes = registry["nodes"]
    if not isinstance(raw_nodes, list) or not raw_nodes:
        raise IntegrationValidationError("nodes must be a non-empty list")
    nodes: dict[str, dict[str, Any]] = {}
    for index, raw_node in enumerate(raw_nodes):
        node = _mapping(raw_node, f"nodes[{index}]")
        _exact_keys(node, NODE_KEYS, f"nodes[{index}]")
        node_id = node["id"]
        if not isinstance(node_id, str) or not node_id or node_id in nodes:
            raise IntegrationValidationError(f"nodes[{index}].id must be unique and non-empty")
        for field in ("type", "authority"):
            if not isinstance(node[field], str) or not node[field]:
                raise IntegrationValidationError(f"nodes[{index}].{field} must be non-empty")
        for field in ("implementation", "tests"):
            for file_index, filename in enumerate(_nonempty_strings(node[field], f"nodes[{index}].{field}")):
                _repository_file(filename, f"nodes[{index}].{field}[{file_index}]", root)
        nodes[node_id] = node

    missing_nodes = set(REQUIRED_PATH) - set(nodes)
    if missing_nodes:
        raise IntegrationValidationError(f"missing required integration nodes: {sorted(missing_nodes)}")
    if nodes.get("ai_room", {}).get("authority") != "proposal_only":
        raise IntegrationValidationError("AI Room must remain proposal_only")
    if nodes["risk"]["authority"] != "deterministic_final":
        raise IntegrationValidationError("Risk must remain deterministic_final")
    if nodes["paper"]["authority"] != "paper_only":
        raise IntegrationValidationError("Paper must remain paper_only")
    if nodes["independent_verifier"]["type"] != "verifier":
        raise IntegrationValidationError("independent_verifier must be a verifier node")

    raw_edges = registry["edges"]
    if not isinstance(raw_edges, list) or not raw_edges:
        raise IntegrationValidationError("edges must be a non-empty list")
    edge_ids: set[str] = set()
    pairs: set[tuple[str, str]] = set()
    for index, raw_edge in enumerate(raw_edges):
        edge = _mapping(raw_edge, f"edges[{index}]")
        _exact_keys(edge, EDGE_KEYS, f"edges[{index}]")
        edge_id = edge["id"]
        if not isinstance(edge_id, str) or not edge_id or edge_id in edge_ids:
            raise IntegrationValidationError(f"edges[{index}].id must be unique and non-empty")
        producer, consumer, verifier = edge["producer"], edge["consumer"], edge["verifier"]
        for field, node_id in (("producer", producer), ("consumer", consumer), ("verifier", verifier)):
            if node_id not in nodes:
                raise IntegrationValidationError(f"edges[{index}].{field} references unknown node {node_id!r}")
        if producer == consumer:
            raise IntegrationValidationError(f"edges[{index}] cannot self-connect")
        if verifier == producer and consumer != "independent_verifier":
            raise IntegrationValidationError(f"edges[{index}] producer cannot verify its own output")
        if nodes[verifier]["type"] != "verifier":
            raise IntegrationValidationError(f"edges[{index}].verifier is not a verifier node")
        if not isinstance(edge["contract"], str) or not edge["contract"].startswith("nexus."):
            raise IntegrationValidationError(f"edges[{index}].contract must be versioned NEXUS contract")
        if edge["status"] not in STATUS_VOCABULARY:
            raise IntegrationValidationError(f"edges[{index}].status is unsupported")
        for field in ("durable_state", "evidence"):
            for file_index, filename in enumerate(_nonempty_strings(edge[field], f"edges[{index}].{field}")):
                _repository_file(filename, f"edges[{index}].{field}[{file_index}]", root)
        edge_ids.add(edge_id)
        pairs.add((producer, consumer))

    required_pairs = set(zip(REQUIRED_PATH, REQUIRED_PATH[1:]))
    missing_pairs = required_pairs - pairs
    if missing_pairs:
        raise IntegrationValidationError(f"canonical path has missing edges: {sorted(missing_pairs)}")


def load_and_validate(path: Path = DEFAULT_REGISTRY, root: Path = ROOT) -> None:
    if not path.is_file() or path.is_symlink():
        raise IntegrationValidationError("registry must be a regular non-symlink file")
    raw = path.read_bytes()
    if len(raw) > MAX_BYTES:
        raise IntegrationValidationError(f"registry exceeds {MAX_BYTES}-byte limit")
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IntegrationValidationError(f"invalid JSON: {exc}") from exc
    validate_registry(payload, root)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the canonical NEXUS integration graph")
    parser.add_argument("path", nargs="?", type=Path, default=DEFAULT_REGISTRY)
    args = parser.parse_args()
    try:
        load_and_validate(args.path)
    except (OSError, IntegrationValidationError) as exc:
        parser.exit(1, f"NEXUS integration validation failed: {exc}\n")
    print("NEXUS integration registry: valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
