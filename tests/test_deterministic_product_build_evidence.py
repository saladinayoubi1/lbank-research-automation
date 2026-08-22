import json
from pathlib import Path

import pytest

from scripts.write_deterministic_product_build_evidence import write


def test_same_source_produces_identical_product_metadata(tmp_path: Path):
    first, second = tmp_path / "first.json", tmp_path / "second.json"
    write(first, "a" * 40, "2026-08-22T22:00:00+00:00")
    write(second, "a" * 40, "2026-08-22T22:00:00+00:00")
    assert first.read_bytes() == second.read_bytes()
    payload = json.loads(first.read_text(encoding="utf-8"))
    assert payload["paper_only"] is True
    assert payload["live_trading_authority"] is False
    assert "run_id" not in payload and "run_attempt" not in payload and "ref" not in payload


@pytest.mark.parametrize("sha", ["main", "A" * 40, "a" * 39])
def test_invalid_source_sha_fails(tmp_path: Path, sha: str):
    with pytest.raises(ValueError, match="source SHA"):
        write(tmp_path / "evidence.json", sha, "2026-08-22T22:00:00Z")


def test_timezone_free_source_timestamp_fails(tmp_path: Path):
    with pytest.raises(ValueError, match="timezone"):
        write(tmp_path / "evidence.json", "a" * 40, "2026-08-22T22:00:00")
