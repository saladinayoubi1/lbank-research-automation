from __future__ import annotations

import functools
import sys

import nexus_multipair_recent_archive_runtime_snapshot as recent
from scripts.nexus_public_current_run_artifact import PHYSICAL_RECENT_TRANSPORT_AGE_MS


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] != "requalify":
        raise SystemExit("physical recent-archive adapter supports requalify only")
    if not (
        recent.MAX_TRANSPORT_AGE_MS < PHYSICAL_RECENT_TRANSPORT_AGE_MS < recent.MAX_SOURCE_LAG_MS
    ):
        raise RuntimeError("physical recent-archive transport window is outside bounded policy")

    original = recent.verify_recent_archive_runtime_snapshot
    recent.verify_recent_archive_runtime_snapshot = functools.partial(
        original,
        max_transport_age_ms=PHYSICAL_RECENT_TRANSPORT_AGE_MS,
    )
    try:
        return recent.main()
    finally:
        recent.verify_recent_archive_runtime_snapshot = original


if __name__ == "__main__":
    raise SystemExit(main())
