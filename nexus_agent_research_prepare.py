"""Prepare real, immutable Research Agent inputs from approved Actions cache transport.

The approved multi-timeframe workflow (already allowed actions:read) verifies
the original official Bybit archive and publishes a source-bound cache bundle.
The bounded runtime worker retains frozen contents:read ONLY; it restores that
cache and verifies archive ZIP/delivery/ledger digests without fetching GitHub
Actions artifacts or expanding its token authority.

The producer's exact numerical evidence is also exchanged via a source/lease
scoped immutable cache, not by fetching an ambiguously latest GitHub artifact.
Actions cache is a transport, NEVER the durable Research frontier/database.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

from nexus_composite_strategy_research import ARCHIVE_SHA256, digest, load_ledger, safe_write, select_next
from scripts.agent_task_executor import decode_payload
from nexus_research_missions import FIRST, PREDECESSOR, TASKS, ANCESTRY, validate_ancestry
from scripts.select_nexus_bybit_replay_artifact import (
    validate_candidate, safe_extract, sha256_file,
)

TASK_ID = FIRST
REPO = "saladinayoubi1/lbank-research-automation"
REPLAY_NAME = "NEXUS_BYBIT_replay_v2_2022-12-01_to_2026-07-31.zip"
DELIVERY_NAME = "NEXUS_BYBIT_replay_v2_delivery.json"
DATA_CACHE = Path("build/agent-research-cache")
PRODUCER_CACHE = Path("build/agent-producer-cache")
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
INPUT_CACHE_V1_PREFIX = "nexus-composite-inputs-v1-"
INPUT_CACHE_V2_PREFIX = "nexus-composite-inputs-v2-"


class ResearchPreparationError(ValueError):
    pass


def _read_regular_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ResearchPreparationError("required research evidence is missing or linked")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ResearchPreparationError("required research evidence is malformed") from exc
    if not isinstance(data, dict):
        raise ResearchPreparationError("required research evidence is not an object")
    return data


def _classify(mode: str) -> tuple[dict[str, Any] | None, str]:
    encoded = os.environ.get("NEXUS_TASK_PAYLOAD_B64", "")
    if not encoded:
        return None, "none"
    payload = decode_payload(encoded)
    if payload["task_id"] not in TASKS:
        return None, "none"
    if (
        payload["phase"] != 7
        or payload["transport"] != "github-cloud"
        or payload["worker_id"] not in {"research-agent", "qa-verifier-agent"}
        or os.environ.get("GITHUB_REPOSITORY") != REPO
        or not HEX40.fullmatch(os.environ.get("GITHUB_SHA", ""))
    ):
        raise ResearchPreparationError("untrusted real Research Agent task context")
    expected_mode = "independent-qa" if payload["worker_id"] == "qa-verifier-agent" else "producer"
    if mode not in ("inspect", "auto", expected_mode):
        raise ResearchPreparationError("untrusted Research Agent role")
    if expected_mode == "independent-qa" and (
        payload["research_producer_source_sha"] != os.environ["GITHUB_SHA"]
        or not HEX64.fullmatch(payload["research_producer_receipt_digest"])
        or not re.fullmatch(r"[a-zA-Z0-9_-]{1,160}", payload["research_producer_lease_id"])
    ):
        raise ResearchPreparationError("QA original producer identity is untrusted")
    if payload["task_id"] in PREDECESSOR:
        validate_ancestry({key: payload[key] for key in ANCESTRY})
    return payload, expected_mode


def _research_input_cache_identity(payload: dict[str, Any], source_sha: str) -> tuple[str, str]:
    if not HEX40.fullmatch(source_sha):
        raise ResearchPreparationError("research input cache source SHA is invalid")
    if payload["task_id"] not in PREDECESSOR:
        return INPUT_CACHE_V1_PREFIX + source_sha, ""
    ancestry = validate_ancestry({key: payload[key] for key in ANCESTRY})
    ledger_digest = ancestry["research_predecessor_ledger_digest"]
    if not HEX64.fullmatch(ledger_digest):
        raise ResearchPreparationError("research predecessor ledger digest is invalid")
    return INPUT_CACHE_V2_PREFIX + source_sha + "-" + ledger_digest, ledger_digest


def _verified_input_bundle(root: Path, source_sha: str, predecessor: dict[str, str] | None = None) -> dict[str, Any]:
    metadata = _read_regular_json(DATA_CACHE / "manifest.json")
    claim = metadata.pop("manifest_digest", None)
    if (
        claim != digest(metadata)
        or metadata.get("schema") != "nexus.real-research-transport.v1"
        or metadata.get("source_sha") != source_sha
        or metadata.get("archive_sha256") != ARCHIVE_SHA256
        or not HEX64.fullmatch(str(metadata.get("replay_zip_sha256", "")))
        or metadata.get("research_only") is not True
        or metadata.get("auto_demo_promotion") is not False
        or metadata.get("live_enabled") is not False
    ):
        raise ResearchPreparationError("trusted Research data cache provenance rejected")
    archived, _delivery = validate_candidate(
        DATA_CACHE, expected_file_name=REPLAY_NAME,
        expected_semantic_sha256=ARCHIVE_SHA256, delivery_name=DELIVERY_NAME,
    )
    if sha256_file(archived) != metadata["replay_zip_sha256"]:
        raise ResearchPreparationError("Research cache ZIP changed after source verification")
    previous_file = DATA_CACHE / "previous-ledger.json"
    if previous_file.is_symlink() or not previous_file.is_file():
        raise ResearchPreparationError("required prior novelty frontier not present")
    previous = load_ledger(previous_file)
    if (
        not previous["config_fingerprints_evaluated"]
        or previous["ledger_digest"] != metadata.get("prior_ledger_digest")
    ):
        raise ResearchPreparationError("Research cache prior novelty ledger mismatch")
    if predecessor is not None:
        # The preceding numerical producer+independent QA must have attested
        # this exact frontier, not merely a similarly named latest artifact.
        if previous["ledger_digest"] != predecessor["research_predecessor_ledger_digest"]:
            raise ResearchPreparationError("source cache does not match prior QA-attested novelty ledger")
        candidate = select_next(previous)
        # The general research grammar may revisit risk variants. A new real
        # successor lease must instead introduce a never-tested causal family.
        if candidate is None or candidate["mechanism"] in previous["mechanisms_evaluated"]:
            raise ResearchPreparationError(
                "no new reviewed causal mechanism remains; Developer Agent review required"
            )
        if candidate["mechanism"] == predecessor["research_predecessor_mechanism"]:
            raise ResearchPreparationError("no different reviewed causal mechanism remains")
    safe_extract(archived, root / "archive")
    shutil.copyfile(previous_file, root / "previous-ledger.json")
    return {
        "archive_sha256": ARCHIVE_SHA256,
        "replay_zip_sha256": metadata["replay_zip_sha256"],
        "prior_ledger_digest": previous["ledger_digest"],
    }


def _copy_exact_producer(root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    original_lease = payload["research_producer_lease_id"]
    original_digest = payload["research_producer_receipt_digest"]
    original_sha = payload["research_producer_source_sha"]
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,160}", original_lease):
        raise ResearchPreparationError("invalid original Research producer lease")
    cached = PRODUCER_CACHE / "result"
    original = _read_regular_json(cached / "agent-receipt.json")
    if (
        original.get("schema") != "nexus.agent-composite-execution.v1"
        or original.get("receipt_digest") != original_digest
        or original.get("source_sha") != original_sha
        or original.get("lease_id") != original_lease
        or original.get("archive_sha256") != ARCHIVE_SHA256
        or original.get("research_only") is not True
        or original.get("auto_demo_promotion") is not False
        or original.get("live_enabled") is not False
        or original.get("independent_qa_complete") is not False
    ):
        raise ResearchPreparationError("independent QA producer cache identity rejected")
    expected_core = {k: v for k, v in original.items() if k != "receipt_digest"}
    if digest(expected_core) != original_digest:
        raise ResearchPreparationError("producer receipt cache digest changed")
    old = load_ledger(cached / "previous-ledger.json")
    # The newly published frontier may have moved on while QA waited.
    # QA replays the producer's copied ORIGINAL prior-ledger, not the newest.
    if old["ledger_digest"] != original.get("prior_ledger_digest"):
        raise ResearchPreparationError("QA cannot bind original producer frontier")
    dest = root / "producer" / "result"
    if dest.exists():
        raise ResearchPreparationError("QA producer staging directory must be empty")
    shutil.copytree(cached, dest, symlinks=False)
    return {
        "producer_lease_id": original_lease,
        "producer_receipt_digest": original_digest,
        "producer_source_sha": original_sha,
        "producer_prior_ledger_digest": old["ledger_digest"],
    }


def prepare(mode: str, root: Path) -> dict[str, Any]:
    payload, role = _classify(mode)
    if payload is None:
        return {"research_task": False}
    if mode == "inspect":
        cache_key, predecessor_ledger_digest = _research_input_cache_identity(
            payload, os.environ["GITHUB_SHA"]
        )
        return {
            "research_task": True,
            "mode": role,
            "producer_lease_id": payload.get("research_producer_lease_id", ""),
            "producer_source_sha": payload.get("research_producer_source_sha", ""),
            "research_input_cache_key": cache_key,
            "predecessor_ledger_digest": predecessor_ledger_digest,
        }
    if root.exists():
        raise ResearchPreparationError("refuse dirty or pre-existing Research staging root")
    root.mkdir(parents=True)
    predecessor = (
        validate_ancestry({key: payload[key] for key in ANCESTRY})
        if payload["task_id"] in PREDECESSOR else None
    )
    info = {
        "research_task": True,
        "task_id": payload["task_id"],
        "mode": role,
        "lease_id": payload["lease_id"],
        "source_sha": os.environ["GITHUB_SHA"],
        **_verified_input_bundle(root, os.environ["GITHUB_SHA"], predecessor),
        "auto_demo_promotion": False,
        "live_enabled": False,
    }
    if predecessor is not None:
        info.update(predecessor)
    if role == "independent-qa":
        info.update(_copy_exact_producer(root, payload))
    safe_write(root / "preparation.json", info)
    return info


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("inspect", "auto", "producer", "independent-qa"), default="auto")
    parser.add_argument("--root", type=Path, default=Path("build/agent-research"))
    args = parser.parse_args()
    info = prepare(args.mode, args.root)
    if os.environ.get("GITHUB_OUTPUT"):
        with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as handle:
            handle.write("research_task=" + str(info["research_task"]).lower() + "\n")
            handle.write("research_role=" + str(info.get("mode", "none")) + "\n")
            handle.write("producer_lease=" + str(info.get("producer_lease_id", "")) + "\n")
            handle.write("producer_source_sha=" + str(info.get("producer_source_sha", "")) + "\n")
            handle.write("research_input_cache_key=" + str(info.get("research_input_cache_key", "")) + "\n")
            handle.write("predecessor_ledger_digest=" + str(info.get("predecessor_ledger_digest", "")) + "\n")
    print(json.dumps(info, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
