from __future__ import annotations

import sys
from pathlib import Path

import pytest

import nexus_multipair_recent_archive_runtime_snapshot as recent
from scripts import nexus_recent_archive_physical_requalification as adapter


def test_physical_requalification_uses_bounded_transport_override(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, int] = {}

    def fake_verify(
        root: str | Path,
        value: dict,
        *,
        source_sha: str,
        now_ms: int,
        max_transport_age_ms: int = recent.MAX_TRANSPORT_AGE_MS,
    ) -> dict:
        del root, value, source_sha, now_ms
        seen["max_transport_age_ms"] = max_transport_age_ms
        return {"decision": "pass"}

    def fake_main() -> int:
        verification = recent.verify_recent_archive_runtime_snapshot(
            Path("."), {}, source_sha="7" * 40, now_ms=1
        )
        assert verification["decision"] == "pass"
        return 0

    monkeypatch.setattr(recent, "verify_recent_archive_runtime_snapshot", fake_verify)
    monkeypatch.setattr(recent, "main", fake_main)
    monkeypatch.setattr(sys, "argv", ["adapter", "requalify"])

    assert adapter.main() == 0
    assert seen["max_transport_age_ms"] == adapter.PHYSICAL_RECENT_TRANSPORT_AGE_MS
    assert recent.MAX_TRANSPORT_AGE_MS < adapter.PHYSICAL_RECENT_TRANSPORT_AGE_MS
    assert adapter.PHYSICAL_RECENT_TRANSPORT_AGE_MS < recent.MAX_SOURCE_LAG_MS
    assert recent.verify_recent_archive_runtime_snapshot is fake_verify


def test_physical_requalification_adapter_rejects_other_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["adapter", "acquire"])
    with pytest.raises(SystemExit, match="requalify only"):
        adapter.main()
