from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from typing import Any

import requests

import bybit_spot_archive_audit as audit

RETRYABLE_STATUS_CODES = {403, 408, 425, 429, 500, 502, 503, 504}


def robust_download_archive(
    symbol: str,
    audit_date: str,
    cache_root: Path,
    timeout_seconds: float = 120.0,
    max_attempts: int = 5,
    session: requests.Session | None = None,
) -> dict[str, Any]:
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")

    cache_root.mkdir(parents=True, exist_ok=True)
    path = cache_root / audit.archive_filename(symbol, audit_date)
    url = audit.archive_url(symbol, audit_date)

    if path.exists() and path.stat().st_size > 0:
        content = path.read_bytes()
        return {
            "symbol": symbol,
            "audit_date": audit_date,
            "url": url,
            "path": path.as_posix(),
            "size_bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
            "http_status": 200,
            "download_attempts": 0,
            "loaded_from_cache": True,
        }

    client = session or requests.Session()
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            response = client.get(
                url,
                timeout=timeout_seconds,
                allow_redirects=True,
                headers={
                    "Accept": "application/gzip,application/octet-stream,*/*",
                    "Referer": f"{audit.ARCHIVE_BASE_URL}/{symbol}/",
                },
            )
            if (
                response.status_code in RETRYABLE_STATUS_CODES
                and attempt < max_attempts
            ):
                time.sleep(min(30.0, float(2 ** (attempt - 1))))
                continue
            response.raise_for_status()
            content = response.content
            if not content:
                raise audit.BybitArchiveAuditError(
                    f"Downloaded empty archive: {url}"
                )
            temporary = path.with_suffix(path.suffix + ".tmp")
            temporary.write_bytes(content)
            temporary.replace(path)
            return {
                "symbol": symbol,
                "audit_date": audit_date,
                "url": url,
                "path": path.as_posix(),
                "size_bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
                "http_status": int(response.status_code),
                "download_attempts": attempt,
                "loaded_from_cache": False,
            }
        except Exception as exc:
            last_error = exc
            if attempt < max_attempts:
                time.sleep(min(30.0, float(2 ** (attempt - 1))))

    assert last_error is not None
    raise last_error


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the Bybit official Spot archive audit with retry-safe downloads."
    )
    parser.add_argument("--audit-date", default=audit.DEFAULT_AUDIT_DATE)
    parser.add_argument("--cache-root", type=Path, default=audit.DEFAULT_CACHE_ROOT)
    parser.add_argument("--output-root", type=Path, default=audit.DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--max-attempts", type=int, default=5)
    parser.add_argument("--clean", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    def downloader(symbol: str, audit_date: str, cache_root: Path):
        return robust_download_archive(
            symbol,
            audit_date,
            cache_root,
            max_attempts=args.max_attempts,
        )

    report = audit.build_archive_audit_report(
        audit_date=args.audit_date,
        cache_root=args.cache_root,
        downloader=downloader,
    )
    audit.write_report(report, args.output_root, args.clean)
    print(json.dumps(report["summary"], sort_keys=True))
    return (
        0
        if report["summary"]["candidate_for_full_spot_archive_backfill"]
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
