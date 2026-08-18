from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

_BUILD_CONTRACT = "nexus.product-build-evidence.v1"
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
MAX_EVIDENCE_BYTES = 256_000


class ProductBuildEvidenceError(RuntimeError):
    pass


def _read(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_EVIDENCE_BYTES:
        raise ProductBuildEvidenceError("build evidence path is unsafe")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProductBuildEvidenceError("build evidence is invalid") from exc
    if not isinstance(payload, dict):
        raise ProductBuildEvidenceError("build evidence root must be an object")
    return payload


def build_evidence_snapshot() -> dict[str, Any]:
    path_raw = os.environ.get("NEXUS_BUILD_EVIDENCE_PATH", "").strip()
    payload = _read(Path(path_raw)) if path_raw else None
    if payload is None:
        return {"contract_version": _BUILD_CONTRACT, "status": "unavailable", "exact_source": False, "paper_only": True}
    if payload.get("contract_version") != _BUILD_CONTRACT:
        raise ProductBuildEvidenceError("build evidence contract mismatch")
    source_sha = str(payload.get("source_sha") or "").lower()
    if not _SHA_RE.fullmatch(source_sha):
        raise ProductBuildEvidenceError("build evidence source SHA invalid")
    if payload.get("paper_only") is not True or payload.get("live_trading_authority") is not False:
        raise ProductBuildEvidenceError("build evidence widened authority")
    return {**payload, "status": "verified", "exact_source": True}


def supervisor_snapshot(root: Path) -> dict[str, Any]:
    path = Path(root) / "supervisor-state.json"
    payload = _read(path)
    if payload is None:
        return {
            "contract_version": "nexus.local-supervisor.v1",
            "status": "unknown",
            "restart_count": 0,
            "bounded_restart_policy": True,
            "paper_only": True,
        }
    if payload.get("contract_version") != "nexus.local-supervisor.v1" or payload.get("paper_only") is not True:
        raise ProductBuildEvidenceError("local supervisor state invalid")
    return payload
