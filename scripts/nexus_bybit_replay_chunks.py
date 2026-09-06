from __future__ import annotations

import argparse
import calendar
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import re
from typing import Any, Iterable
from urllib.parse import urlsplit
import urllib.request


LEGACY_ARTIFACT_PATTERN = re.compile(r"^bybit-chunk-(\d{2})-attempt-\d+$")
REHYDRATED_ARTIFACT_PATTERN = re.compile(r"^bybit-rehydrated-chunk-(\d{2})-\d+$")
ARTIFACT_PATTERN = LEGACY_ARTIFACT_PATTERN
CHUNK_IDS = tuple(f"{number:02d}" for number in range(27, 43)) + tuple(
    f"{number:02d}" for number in range(1, 27)
)


class _CrossHostAuthStrippingRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Preserve auth on same-origin redirects, but never leak it to artifact blob hosts."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is None:
            return None
        source = urlsplit(req.full_url)
        target = urlsplit(newurl)
        if (source.scheme.lower(), source.netloc.lower()) != (
            target.scheme.lower(),
            target.netloc.lower(),
        ):
            redirected.remove_header("Authorization")
        return redirected


def _install_safe_artifact_redirect_opener() -> None:
    # The GitHub artifact archive endpoint redirects to a signed Azure Blob URL.
    # urllib otherwise forwards the GitHub Authorization header across origins,
    # causing Azure to reject the otherwise-valid signed URL with HTTP 401.
    urllib.request.install_opener(
        urllib.request.build_opener(_CrossHostAuthStrippingRedirectHandler())
    )


_install_safe_artifact_redirect_opener()


@dataclass(frozen=True)
class ReplayChunk:
    id: str
    start: str
    end: str


def _month_bounds(year: int, month: int) -> tuple[str, str]:
    last_day = calendar.monthrange(year, month)[1]
    return f"{year:04d}-{month:02d}-01", f"{year:04d}-{month:02d}-{last_day:02d}"


def _next_month(year: int, month: int) -> tuple[int, int]:
    if month == 12:
        return year + 1, 1
    return year, month + 1


def canonical_chunks() -> tuple[ReplayChunk, ...]:
    chunks: list[ReplayChunk] = []
    year, month = 2023, 2
    for chunk_id in CHUNK_IDS:
        start, end = _month_bounds(year, month)
        chunks.append(ReplayChunk(chunk_id, start, end))
        year, month = _next_month(year, month)
    if len(chunks) != 42:
        raise AssertionError("canonical replay map must contain exactly 42 monthly chunks")
    if chunks[0] != ReplayChunk("27", "2023-02-01", "2023-02-28"):
        raise AssertionError("unexpected first canonical replay chunk")
    if chunks[15] != ReplayChunk("42", "2024-05-01", "2024-05-31"):
        raise AssertionError("unexpected chunk-42 boundary")
    if chunks[16] != ReplayChunk("01", "2024-06-01", "2024-06-30"):
        raise AssertionError("unexpected chunk-01 boundary")
    if chunks[-1] != ReplayChunk("26", "2026-07-01", "2026-07-31"):
        raise AssertionError("unexpected final canonical replay chunk")
    return tuple(chunks)


CANONICAL_CHUNKS = canonical_chunks()
CANONICAL_CHUNK_MAP = {chunk.id: chunk for chunk in CANONICAL_CHUNKS}


def _iter_artifacts(payload: Any) -> Iterable[dict[str, Any]]:
    pages = payload if isinstance(payload, list) else [payload]
    for page in pages:
        if not isinstance(page, dict):
            continue
        for artifact in page.get("artifacts", []):
            if isinstance(artifact, dict):
                yield artifact


def _artifact_chunk_id(name: str) -> str | None:
    for pattern in (LEGACY_ARTIFACT_PATTERN, REHYDRATED_ARTIFACT_PATTERN):
        match = pattern.match(name)
        if match:
            return match.group(1)
    return None


def _workflow_compatible_artifact_name(chunk_id: str, artifact_name: str) -> str:
    if LEGACY_ARTIFACT_PATTERN.match(artifact_name):
        return artifact_name
    if REHYDRATED_ARTIFACT_PATTERN.match(artifact_name):
        return f"bybit-chunk-{chunk_id}-attempt-rehydrated"
    raise ValueError(f"Unsupported replay artifact name: {artifact_name}")


def select_latest_unexpired(payload: Any) -> dict[str, dict[str, Any]]:
    latest: dict[str, tuple[tuple[str, int], dict[str, Any]]] = {}
    required = set(CANONICAL_CHUNK_MAP)
    for artifact in _iter_artifacts(payload):
        if artifact.get("expired"):
            continue
        artifact_name = str(artifact.get("name", ""))
        chunk_id = _artifact_chunk_id(artifact_name)
        if chunk_id is None or chunk_id not in required:
            continue
        key = (str(artifact.get("created_at", "")), int(artifact.get("id", 0)))
        current = latest.get(chunk_id)
        if current is None or key > current[0]:
            latest[chunk_id] = (key, artifact)
    return {chunk_id: value[1] for chunk_id, value in latest.items()}


def build_plan(payload: Any) -> dict[str, Any]:
    selected = select_latest_unexpired(payload)
    missing = [chunk for chunk in CANONICAL_CHUNKS if chunk.id not in selected]
    reusable = {}
    for chunk_id, artifact in sorted(selected.items()):
        source_name = str(artifact["name"])
        reusable[chunk_id] = {
            "artifact_id": int(artifact["id"]),
            "name": _workflow_compatible_artifact_name(chunk_id, source_name),
            "source_name": source_name,
            "created_at": str(artifact.get("created_at", "")),
        }
    return {
        "schema_version": 1,
        "required_chunk_count": len(CANONICAL_CHUNKS),
        "reusable_chunk_count": len(reusable),
        "missing_chunk_count": len(missing),
        "missing_ids": [chunk.id for chunk in missing],
        "missing_matrix": {"include": [asdict(chunk) for chunk in missing]},
        "reusable_artifacts": reusable,
    }


def write_github_outputs(path: Path, plan: dict[str, Any]) -> None:
    values = {
        "missing_count": str(plan["missing_chunk_count"]),
        "missing_ids": ",".join(plan["missing_ids"]),
        "missing_matrix": json.dumps(plan["missing_matrix"], separators=(",", ":")),
        "reusable_artifacts": json.dumps(plan["reusable_artifacts"], separators=(",", ":")),
    }
    with path.open("a", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-pages", type=Path, required=True)
    parser.add_argument("--plan-output", type=Path)
    parser.add_argument("--github-output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = json.loads(args.artifact_pages.read_text(encoding="utf-8"))
    plan = build_plan(payload)
    rendered = json.dumps(plan, indent=2, sort_keys=True) + "\n"
    if args.plan_output:
        args.plan_output.parent.mkdir(parents=True, exist_ok=True)
        args.plan_output.write_text(rendered, encoding="utf-8")
    if args.github_output:
        write_github_outputs(args.github_output, plan)
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
