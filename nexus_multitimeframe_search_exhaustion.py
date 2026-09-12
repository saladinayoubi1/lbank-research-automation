"""Certify and reuse an exactly exhausted Multi-Timeframe research neighborhood.

Reuse is deliberately narrow: the immutable dataset semantic SHA, base manifest,
research gates, authority, workflow, dependency lock, source commit, and every
implementation file that defines the search must match exactly. A certificate can
only be emitted after both the base search and its bounded training-only refinement
return zero research proposals. Locked holdout evidence is never used to generate
or widen the next search surface.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

import nexus_multitimeframe_strategy_discovery as discovery

NEIGHBORHOOD_SCHEMA = "nexus.multitimeframe-search-neighborhood.v1"
CERTIFICATE_SCHEMA = "nexus.multitimeframe-search-exhaustion.v1"
_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
IMPLEMENTATION_FILES: tuple[str, ...] = (
    ".github/workflows/nexus_multitimeframe_strategy_discovery.yml",
    "nexus_demo_archive_replay.py",
    "nexus_multitimeframe_search_exhaustion.py",
    "nexus_multitimeframe_strategy_discovery.py",
    "nexus_multitimeframe_training_refinement.py",
    "nexus_multitimeframe_verified_archive_discovery.py",
    "requirements-dev.lock",
)


class MultiTimeframeExhaustionError(RuntimeError):
    pass


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise MultiTimeframeExhaustionError("exhaustion evidence is not canonical JSON") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise MultiTimeframeExhaustionError(f"implementation file unavailable: {path.as_posix()}") from exc
    return digest.hexdigest()


def _load(path: str | Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MultiTimeframeExhaustionError("exhaustion input is unavailable") from exc
    if not isinstance(value, dict):
        raise MultiTimeframeExhaustionError("exhaustion input is not an object")
    return value


def _atomic(path: str | Path, value: Mapping[str, Any]) -> None:
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + f".{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(dict(value), indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, target)


def _resolve_source_sha(source_sha: str | None) -> str:
    if source_sha is not None:
        value = str(source_sha).strip().lower()
        if not _SHA40_RE.fullmatch(value):
            raise MultiTimeframeExhaustionError("source SHA is invalid")
        return value
    for env_name in ("TRIGGER_SOURCE_SHA", "GITHUB_SHA"):
        raw = os.environ.get(env_name)
        if raw:
            value = raw.strip().lower()
            if not _SHA40_RE.fullmatch(value):
                raise MultiTimeframeExhaustionError(f"{env_name} is not a valid source SHA")
            return value
    raise MultiTimeframeExhaustionError("source SHA is required")


def build_neighborhood(
    manifest_path: str | Path,
    *,
    source_sha: str | None = None,
    dataset_semantic_sha256: str,
    root: str | Path = ".",
    implementation_files: Sequence[str] = IMPLEMENTATION_FILES,
) -> dict[str, Any]:
    source_sha = _resolve_source_sha(source_sha)
    dataset_semantic_sha256 = str(dataset_semantic_sha256).strip().lower()
    if not _SHA256_RE.fullmatch(dataset_semantic_sha256):
        raise MultiTimeframeExhaustionError("dataset semantic SHA256 is invalid")
    manifest = discovery.load_manifest(manifest_path)
    repo_root = Path(root).resolve()
    implementation_sha256 = {
        name: _file_sha256(repo_root / name) for name in sorted(set(implementation_files))
    }
    core = {
        "schema_version": NEIGHBORHOOD_SCHEMA,
        "source_sha": source_sha,
        "dataset_semantic_sha256": dataset_semantic_sha256,
        "dataset_archive_sha256": manifest["dataset"]["archive_sha256"],
        "experiment_id": manifest["experiment_id"],
        "manifest_sha256": _digest(manifest),
        "gates_sha256": _digest(manifest["gates"]),
        "authority_sha256": _digest(manifest["authority"]),
        "implementation_sha256": implementation_sha256,
        "symbols": list(manifest["symbols"]),
        "timeframes": list(manifest["timeframes"]),
        "families": list(manifest["families"]),
        "research_only": True,
        "paper_only": True,
        "live_trading_authority": False,
        "automatic_strategy_promotion": False,
    }
    return {**core, "neighborhood_fingerprint": _digest(core)}


def verify_neighborhood(value: Mapping[str, Any]) -> None:
    core = dict(value)
    claimed = core.pop("neighborhood_fingerprint", None)
    if (
        core.get("schema_version") != NEIGHBORHOOD_SCHEMA
        or claimed != _digest(core)
        or not _SHA40_RE.fullmatch(str(core.get("source_sha", "")))
        or not _SHA256_RE.fullmatch(str(core.get("dataset_semantic_sha256", "")))
        or core.get("research_only") is not True
        or core.get("paper_only") is not True
        or core.get("live_trading_authority") is not False
        or core.get("automatic_strategy_promotion") is not False
    ):
        raise MultiTimeframeExhaustionError("search neighborhood verification failed")


def build_certificate(
    neighborhood: Mapping[str, Any],
    base_result: Mapping[str, Any],
    refinement_plan: Mapping[str, Any],
    refined_result: Mapping[str, Any],
) -> dict[str, Any]:
    verify_neighborhood(neighborhood)
    if discovery.verify_discovery(base_result).get("decision") != "pass":
        raise MultiTimeframeExhaustionError("base discovery verification failed")
    if discovery.verify_discovery(refined_result).get("decision") != "pass":
        raise MultiTimeframeExhaustionError("refined discovery verification failed")
    if int(base_result.get("research_proposal_count", -1)) != 0:
        raise MultiTimeframeExhaustionError("base search is not exhausted")
    if int(refined_result.get("research_proposal_count", -1)) != 0:
        raise MultiTimeframeExhaustionError("refined search is not exhausted")
    if refinement_plan.get("should_refine") is not True:
        raise MultiTimeframeExhaustionError("bounded refinement did not run")
    if refinement_plan.get("selection_basis") != "training_only":
        raise MultiTimeframeExhaustionError("refinement is not training-only")
    if refinement_plan.get("locked_holdout_used_for_refinement") is not False:
        raise MultiTimeframeExhaustionError("locked holdout influenced refinement")
    if refinement_plan.get("source_discovery_sha") != base_result.get("source_sha"):
        raise MultiTimeframeExhaustionError("refinement source SHA mismatch")
    if refinement_plan.get("source_discovery_digest") != base_result.get("discovery_digest"):
        raise MultiTimeframeExhaustionError("refinement source digest mismatch")
    if refined_result.get("source_sha") != base_result.get("source_sha"):
        raise MultiTimeframeExhaustionError("refined source SHA mismatch")
    if base_result.get("source_sha") != neighborhood.get("source_sha"):
        raise MultiTimeframeExhaustionError("base source SHA mismatch")
    if base_result.get("dataset_archive_sha256") != neighborhood.get("dataset_archive_sha256"):
        raise MultiTimeframeExhaustionError("base dataset archive mismatch")
    if refined_result.get("dataset_archive_sha256") != neighborhood.get("dataset_archive_sha256"):
        raise MultiTimeframeExhaustionError("refined dataset archive mismatch")
    for value in (base_result, refinement_plan, refined_result):
        if value.get("research_only") is not True or value.get("paper_only") is not True:
            raise MultiTimeframeExhaustionError("research/paper authority mismatch")
        if value.get("live_trading_authority") is not False:
            raise MultiTimeframeExhaustionError("Live authority is forbidden")
        if value.get("automatic_strategy_promotion") is not False:
            raise MultiTimeframeExhaustionError("automatic strategy promotion is forbidden")

    core = {
        "schema_version": CERTIFICATE_SCHEMA,
        "neighborhood_fingerprint": neighborhood["neighborhood_fingerprint"],
        "dataset_semantic_sha256": neighborhood["dataset_semantic_sha256"],
        "dataset_archive_sha256": neighborhood["dataset_archive_sha256"],
        "manifest_sha256": neighborhood["manifest_sha256"],
        "gates_sha256": neighborhood["gates_sha256"],
        "authority_sha256": neighborhood["authority_sha256"],
        "implementation_sha256": neighborhood["implementation_sha256"],
        "source_sha": neighborhood["source_sha"],
        "base_discovery_digest": base_result["discovery_digest"],
        "refinement_plan_digest": refinement_plan["plan_digest"],
        "training_basis_digest": refinement_plan["training_basis_digest"],
        "refined_discovery_digest": refined_result["discovery_digest"],
        "base_research_proposal_count": 0,
        "refined_research_proposal_count": 0,
        "locked_holdout_used_for_refinement": False,
        "selection_basis": "training_only",
        "exhausted": True,
        "reuse_policy": "exact_static_neighborhood_only",
        "research_only": True,
        "paper_only": True,
        "live_trading_authority": False,
        "automatic_strategy_promotion": False,
    }
    return {**core, "certificate_digest": _digest(core)}


def verify_certificate(value: Mapping[str, Any]) -> None:
    core = dict(value)
    claimed = core.pop("certificate_digest", None)
    if (
        core.get("schema_version") != CERTIFICATE_SCHEMA
        or claimed != _digest(core)
        or not _SHA40_RE.fullmatch(str(core.get("source_sha", "")))
        or core.get("exhausted") is not True
        or core.get("reuse_policy") != "exact_static_neighborhood_only"
        or core.get("base_research_proposal_count") != 0
        or core.get("refined_research_proposal_count") != 0
        or core.get("selection_basis") != "training_only"
        or core.get("locked_holdout_used_for_refinement") is not False
        or core.get("research_only") is not True
        or core.get("paper_only") is not True
        or core.get("live_trading_authority") is not False
        or core.get("automatic_strategy_promotion") is not False
    ):
        raise MultiTimeframeExhaustionError("search exhaustion certificate verification failed")


def certificate_is_reusable(neighborhood: Mapping[str, Any], certificate: Mapping[str, Any]) -> bool:
    try:
        verify_neighborhood(neighborhood)
        verify_certificate(certificate)
    except MultiTimeframeExhaustionError:
        return False
    return (
        certificate.get("neighborhood_fingerprint") == neighborhood.get("neighborhood_fingerprint")
        and certificate.get("source_sha") == neighborhood.get("source_sha")
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    fingerprint = sub.add_parser("fingerprint")
    fingerprint.add_argument("--manifest", type=Path, required=True)
    fingerprint.add_argument("--source-sha")
    fingerprint.add_argument("--dataset-semantic-sha256", required=True)
    fingerprint.add_argument("--root", type=Path, default=Path("."))
    fingerprint.add_argument("--output", type=Path, required=True)

    certify = sub.add_parser("certify")
    certify.add_argument("--neighborhood", type=Path, required=True)
    certify.add_argument("--base-discovery", type=Path, required=True)
    certify.add_argument("--refinement-plan", type=Path, required=True)
    certify.add_argument("--refined-discovery", type=Path, required=True)
    certify.add_argument("--output", type=Path, required=True)

    check = sub.add_parser("check")
    check.add_argument("--neighborhood", type=Path, required=True)
    check.add_argument("--certificate", type=Path, required=True)

    args = parser.parse_args()
    if args.command == "fingerprint":
        value = build_neighborhood(
            args.manifest,
            source_sha=args.source_sha,
            dataset_semantic_sha256=args.dataset_semantic_sha256,
            root=args.root,
        )
        _atomic(args.output, value)
        print(json.dumps(value, sort_keys=True))
        return 0
    if args.command == "certify":
        value = build_certificate(
            _load(args.neighborhood),
            _load(args.base_discovery),
            _load(args.refinement_plan),
            _load(args.refined_discovery),
        )
        _atomic(args.output, value)
        print(json.dumps(value, sort_keys=True))
        return 0

    reusable = certificate_is_reusable(_load(args.neighborhood), _load(args.certificate))
    print(json.dumps({"reusable": reusable}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
