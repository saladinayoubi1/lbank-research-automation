"""Export *historical-only* canonical research files from one verified official Bybit archive.

Never grant live price, Paper, trading or automatic-promotion authority. A historical
integrity check uses the immutable acquisition timestamp; current transport/source
age is reported separately and NEVER silently refreshed or backdated.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
import zipfile
from pathlib import Path
from typing import Any

import nexus_multipair_recent_archive_runtime_snapshot as recent
import nexus_multipair_runtime_requalification_snapshot as binding
from nexus_multipair_trusted_surface import SYMBOLS, TIMEFRAMES
from market_data_provenance_manifest import build_provenance_manifest
from phase5_data_binding import bind_canonical_dataset, validate_canonical_dataset

CONTRACT = "nexus.historical-market-offline-bridge.v1"
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
MAX_ARCHIVE_BYTES = 16_000_000
MAX_FRAME_BYTES = 4_000_000
MAX_DATASET_BYTES = 2_000_000


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _members(source: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    allowed = {"snapshot-manifest.json"}
    allowed.update(f"bybit_market/{s}/{t}.parquet" for s in SYMBOLS for t in TIMEFRAMES)
    members = source.infolist()
    if (
        len(members) != len(allowed)
        or {item.filename for item in members} != allowed
        or any(
            item.is_dir()
            or (item.external_attr >> 16) & 0o170000 == 0o120000
            or item.file_size <= 0
            or item.file_size > (300_000 if item.filename.endswith(".json") else MAX_FRAME_BYTES)
            or item.flag_bits & 1
            for item in members
        )
        or sum(item.file_size for item in members) > 32_000_000
    ):
        raise ValueError("archive members, bounds or file types violate canonical contract")
    return {item.filename: item for item in members}


def export_historical(
    *,
    archive: Path,
    expected_archive_sha256: str,
    expected_snapshot_digest: str,
    source_sha: str,
    exporter_sha: str,
    artifact_run_id: int,
    artifact_id: int,
    now_ms: int,
    output_root: Path,
) -> dict[str, Any]:
    for name, value, pattern in (
        ("archive digest", expected_archive_sha256, HEX64),
        ("snapshot digest", expected_snapshot_digest, HEX64),
        ("source SHA", source_sha, HEX40),
        ("exporter SHA", exporter_sha, HEX40),
    ):
        if not isinstance(value, str) or not pattern.fullmatch(value):
            raise ValueError(f"invalid {name}")
    if any(type(x) is not int or x <= 0 for x in (artifact_run_id, artifact_id, now_ms)):
        raise ValueError("invalid historical identity or UTC clock")
    archive = archive.resolve(strict=True)
    if archive.is_symlink() or archive.stat().st_size > MAX_ARCHIVE_BYTES:
        raise ValueError("missing, symlinked or oversized trusted archive")
    if _sha(archive.read_bytes()) != expected_archive_sha256:
        raise ValueError("official inner archive SHA256 mismatch")
    output = output_root.resolve()
    if output.exists():
        raise ValueError("historical output must be new; never replace an existing vault")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".nexus-offline-stage-", dir=output.parent) as temp:
        stage = Path(temp)
        extracted = stage / "verified"
        extracted.mkdir()
        with zipfile.ZipFile(archive, "r") as stream:
            members = _members(stream)
            for path, info in members.items():
                target = extracted / path
                target.parent.mkdir(parents=True, exist_ok=True)
                contents = stream.read(info)
                if len(contents) != info.file_size:
                    raise ValueError("archive decompression size mismatch")
                target.write_bytes(contents)
        manifest = json.loads((extracted / "snapshot-manifest.json").read_text(encoding="utf-8"))
        if (
            manifest.get("source_sha") != source_sha
            or manifest.get("snapshot_digest") != expected_snapshot_digest
            or manifest.get("data_origin") != recent.DATA_ORIGIN
            or manifest.get("research_only") is not True
            or manifest.get("live_freshness_claimed") is not False
            or manifest.get("paper_execution_started") is not False
            or manifest.get("automatic_strategy_promotion") is not False
        ):
            raise ValueError("archive historical identity or authority mismatch")
        acquired = manifest.get("acquired_at_ms")
        if type(acquired) is not int or acquired > now_ms:
            raise ValueError("invalid or future original archive acquisition")
        # This verifies *original* artifact integrity at its actual acquisition.
        # It is intentionally NOT an assertion of current transport freshness.
        result = recent.verify_recent_archive_runtime_snapshot(
            extracted, manifest, source_sha=source_sha, now_ms=acquired,
        )
        if result["decision"] != "pass":
            raise ValueError("official archived frames were not valid at acquisition")
        canonical: list[tuple[str, bytes]] = []
        receipts: list[dict[str, Any]] = []
        for symbol in SYMBOLS:
            for timeframe in TIMEFRAMES:
                dataset = binding.bind_transported_runtime_dataset(
                    extracted, manifest, symbol=symbol, timeframe=timeframe,
                )
                # Rebind the original 240-bar frame with *honest transport metadata*.
                # The canonical endpoint_contract only identifies the configured
                # registry shape; no /v5/market/kline request acquired these bars.
                # The source actually was an independently verified Bybit *trade*
                # archive aggregated into historical candles.
                original = validate_canonical_dataset(dataset)
                rows = original["rows"]
                metadata = {
                    "collector": "official_public_bybit_spot_trade_archive_aggregated_recent",
                    "actual_transport": "official_bybit_spot_trade_archive",
                    "canonical_endpoint_contract_is_mapping_only": True,
                    "original_archive_sha256": expected_archive_sha256,
                    "original_snapshot_digest": expected_snapshot_digest,
                    "original_producer_sha": source_sha,
                    "original_acquired_at_ms": acquired,
                    "original_data_as_of_ms": manifest["data_as_of_ms"],
                    "historical_only": True,
                    "research_only": True,
                    "live_freshness_claimed": False,
                    "automatic_paper_eligible": False,
                }
                historical_manifest = build_provenance_manifest(
                    source="Bybit", market_type="spot",
                    source_symbol=original["source_symbol"],
                    canonical_symbol=original["instrument"],
                    timeframe=original["manifest_timeframe"],
                    endpoint_contract=original["endpoint_contract"],
                    mapping_policy_version=original["mapping_policy_version"],
                    retrieval_start_ms=rows[0]["open_time_ms"],
                    retrieval_end_ms=rows[-1]["open_time_ms"],
                    candles=rows,
                    metadata=metadata,
                )
                validated = validate_canonical_dataset(
                    bind_canonical_dataset(historical_manifest, rows)
                )
                if (
                    validated.get("row_count") != 240 or validated.get("source") != "Bybit"
                    or validated.get("source_role") != "primary"
                    or validated.get("paper_only") is not True
                ):
                    raise ValueError("archive-canonical dataset semantics mismatch")
                filename = f"canonical/{symbol}-{timeframe}.json"
                raw = _canonical(validated)
                if len(raw) > MAX_DATASET_BYTES:
                    raise ValueError("archive-canonical dataset exceeds import limit")
                canonical.append((filename, raw))
                receipts.append({
                    "filename": filename,
                    "sha256": _sha(raw),
                    "binding_sha256": validated["binding_sha256"],
                    "source_symbol": symbol,
                    "timeframe": timeframe,
                    "rows": validated["row_count"],
                    "last_open_time_ms": validated["rows"][-1]["open_time_ms"],
                })
        if len(receipts) != 12 or len({r["binding_sha256"] for r in receipts}) != 12:
            raise ValueError("incomplete or duplicated canonical offline bindings")
        body: dict[str, Any] = {
            "contract_version": CONTRACT,
            "source_sha": source_sha,
            "exporter_sha": exporter_sha,
            "artifact_run_id": artifact_run_id,
            "artifact_id": artifact_id,
            "archive_sha256": expected_archive_sha256,
            "snapshot_digest": expected_snapshot_digest,
            "original_acquired_at_ms": acquired,
            "data_as_of_ms": manifest["data_as_of_ms"],
            "latest_common_complete_date": manifest["latest_common_complete_date"],
            "actual_export_check_at_ms": now_ms,
            "transport_age_ms": now_ms - acquired,
            "data_age_ms": now_ms - manifest["data_as_of_ms"],
            "original_data_origin": recent.DATA_ORIGIN,
            "research_only": True,
            "historical_only": True,
            "live_freshness_claimed": False,
            "paper_execution_started": False,
            "automatic_paper_eligible": False,
            "automatic_strategy_promotion": False,
            "third_party_proxy_used": False,
            "source_exchange_substituted": False,
            "datasets": receipts,
        }
        receipt = {**body, "receipt_sha256": _sha(_canonical(body))}
        receipt_raw = _canonical(receipt)
        if len(receipt_raw) > 80_000:
            raise ValueError("oversized offline research provenance receipt")
        path = stage / "offline-import.zip"
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zipped:
            for filename, contents in sorted([*canonical, ("historical-receipt.json", receipt_raw)]):
                info = zipfile.ZipInfo(filename, (1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o600 << 16
                zipped.writestr(info, contents, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
        result_dir = stage / "export"
        result_dir.mkdir()
        (result_dir / "offline-import.zip").write_bytes(path.read_bytes())
        (result_dir / "offline-import.sha256").write_text(
            _sha(path.read_bytes()) + "\n", encoding="ascii",
        )
        result_dir.rename(output)
    return {
        "decision": "historical_only_verified",
        "count": len(receipts),
        "archive_sha256": expected_archive_sha256,
        "snapshot_digest": expected_snapshot_digest,
        "original_data_as_of_ms": manifest["data_as_of_ms"],
        "actual_export_check_at_ms": now_ms,
        "offline_archive_sha256": (output / "offline-import.sha256").read_text().strip(),
        "live_freshness_claimed": False,
        "paper_execution_started": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--expected-archive-sha256", required=True)
    parser.add_argument("--expected-snapshot-digest", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--exporter-sha", required=True)
    parser.add_argument("--artifact-run-id", required=True, type=int)
    parser.add_argument("--artifact-id", required=True, type=int)
    parser.add_argument("--now-ms", required=True, type=int)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(export_historical(
        archive=args.archive,
        expected_archive_sha256=args.expected_archive_sha256,
        expected_snapshot_digest=args.expected_snapshot_digest,
        source_sha=args.source_sha,
        exporter_sha=args.exporter_sha,
        artifact_run_id=args.artifact_run_id,
        artifact_id=args.artifact_id,
        now_ms=args.now_ms,
        output_root=args.output_root,
    ), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
