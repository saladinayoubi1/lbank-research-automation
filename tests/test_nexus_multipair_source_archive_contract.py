from __future__ import annotations

import subprocess
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAX_SOURCE_ARCHIVE_BYTES = 8 * 1024 * 1024
SEPARATE_RESEARCH_REPLAY_BUNDLE = (
    "docs/evidence/mr40-fixed-path-robustness-20261021/"
    "NEXUS_MR40_Robustness_20261021.zip"
)
STAGED_ENTRY_LEDGER = "docs/evidence/mr40-staged-entry-20261022/ledger.jsonl.gz"
STAGED_ENTRY_SUMMARY = "docs/evidence/mr40-staged-entry-20261022/results.json"
ADAPTIVE_SIZING_SUMMARY = "docs/evidence/mr40-adaptive-sizing-20261022/summary.json"
PARTIAL_TRIM_LEDGER = "docs/evidence/mr40-partial-loss-trim-20261022/ledger.jsonl.gz"
PARTIAL_TRIM_RESULTS = "docs/evidence/mr40-partial-loss-trim-20261022/results.json.gz"
PARTIAL_TRIM_RISK_AUDIT = "docs/evidence/mr40-partial-loss-trim-20261022/risk_attribution.json"
TRIGGER_RATCHET_LEDGER = "docs/evidence/mr40-trigger-ratchet-20261022/ledger.jsonl.gz"
TRIGGER_RATCHET_RESULTS = "docs/evidence/mr40-trigger-ratchet-20261022/results.json.gz"
OLDER_RESEARCH_RESULTS = "docs/evidence/mr40-isolated-improvement-20261022/results.json"
PREVIOUS_RR_SUMMARY = "docs/evidence/mr40-rr-sizing-20261022/summary.json"
REQUIRED_RUNTIME_FILES = {
    "requirements.lock",
    "nexus_multipair_strategy_discovery.py",
    "nexus_multipair_training_refinement.py",
    "nexus_multipair_runtime_requalification_snapshot.py",
    "scripts/nexus_snapshot_artifact.py",
    "scripts/nexus_runtime_snapshot_artifact.py",
}


def test_exact_source_archive_excludes_duplicate_market_data_and_keeps_runtime(tmp_path: Path) -> None:
    archive = tmp_path / "nexus-multipair-exact-source.zip"
    subprocess.run(
        ["git", "archive", "--format=zip", "--output", str(archive), "HEAD"],
        cwd=ROOT,
        check=True,
    )
    assert archive.stat().st_size <= MAX_SOURCE_ARCHIVE_BYTES

    with zipfile.ZipFile(archive) as bundle:
        members = bundle.infolist()
        names = {member.filename for member in members}

    assert not any(
        member.filename.startswith("data/market/") and not member.is_dir()
        for member in members
    )
    assert REQUIRED_RUNTIME_FILES <= names
    assert SEPARATE_RESEARCH_REPLAY_BUNDLE not in names
    assert STAGED_ENTRY_LEDGER not in names
    assert STAGED_ENTRY_SUMMARY not in names
    assert ADAPTIVE_SIZING_SUMMARY not in names
    assert PARTIAL_TRIM_LEDGER not in names
    assert PARTIAL_TRIM_RESULTS not in names
    assert PARTIAL_TRIM_RISK_AUDIT not in names
    assert TRIGGER_RATCHET_LEDGER not in names
    assert TRIGGER_RATCHET_RESULTS not in names
    assert OLDER_RESEARCH_RESULTS not in names
    assert PREVIOUS_RR_SUMMARY not in names
    subprocess.run(
        ["git", "cat-file", "-e", f"HEAD:{SEPARATE_RESEARCH_REPLAY_BUNDLE}"],
        cwd=ROOT,
        check=True,
    )


def test_research_evidence_remains_versioned_outside_runtime_archive() -> None:
    for path in (
        STAGED_ENTRY_LEDGER, STAGED_ENTRY_SUMMARY, ADAPTIVE_SIZING_SUMMARY,
        PARTIAL_TRIM_LEDGER, PARTIAL_TRIM_RESULTS, PARTIAL_TRIM_RISK_AUDIT,
        PREVIOUS_RR_SUMMARY, TRIGGER_RATCHET_LEDGER,
        TRIGGER_RATCHET_RESULTS, OLDER_RESEARCH_RESULTS,
    ):
        subprocess.run(
            ["git", "cat-file", "-e", f"HEAD:{path}"],
            cwd=ROOT,
            check=True,
        )
