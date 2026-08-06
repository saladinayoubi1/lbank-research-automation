"""Prepare local reports and launch the browser dashboard."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_ROOT = ROOT / "data" / "market"
INTEGRATION_ROOT = ROOT / "data" / "integrations"
LEGACY_INTEGRATION_ROOT = ROOT / "integrations"
RESEARCH_REPORT = INTEGRATION_ROOT / "research_evidence_summary.json"
ZOTERO_REPORT = INTEGRATION_ROOT / "zotero_metadata_report_v2.json"
REFERENCE_JSON = ROOT / "references" / "crypto-fx-library.json"
BACKFILL_STATUS = DATA_ROOT / "_backfill_status.csv"
READINESS_JSON = DATA_ROOT / "_data_readiness.json"
READINESS_CSV = DATA_ROOT / "_data_readiness.csv"


def ensure_research_report() -> None:
    if RESEARCH_REPORT.exists():
        return
    payload = {
        "schema_version": "1.1.0",
        "status": "research-only",
        "paper_trading_only": True,
        "claims": [],
        "evidence": [],
        "next_review_due": None,
    }
    RESEARCH_REPORT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def ensure_zotero_report() -> None:
    if ZOTERO_REPORT.exists():
        return
    legacy = LEGACY_INTEGRATION_ROOT / ZOTERO_REPORT.name
    if legacy.exists():
        shutil.copy2(legacy, ZOTERO_REPORT)
        return
    if not REFERENCE_JSON.exists():
        raise FileNotFoundError(f"Missing reference file: {REFERENCE_JSON}")
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "zotero_metadata_audit.py"),
            str(REFERENCE_JSON),
            "--json",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    ZOTERO_REPORT.write_text(result.stdout, encoding="utf-8")


def ensure_readiness_reports() -> None:
    if not BACKFILL_STATUS.exists():
        raise FileNotFoundError(f"Missing readiness source: {BACKFILL_STATUS}")
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "data_readiness.py"),
            "--status-path",
            str(BACKFILL_STATUS),
        ],
        cwd=ROOT,
        check=True,
    )
    if not READINESS_JSON.exists() or not READINESS_CSV.exists():
        raise FileNotFoundError("Readiness reports were not generated")


def main() -> None:
    INTEGRATION_ROOT.mkdir(parents=True, exist_ok=True)
    if LEGACY_INTEGRATION_ROOT.exists():
        for name in (RESEARCH_REPORT.name, ZOTERO_REPORT.name):
            source = LEGACY_INTEGRATION_ROOT / name
            target = INTEGRATION_ROOT / name
            if source.exists() and not target.exists():
                shutil.copy2(source, target)

    ensure_research_report()
    ensure_zotero_report()
    ensure_readiness_reports()

    print("Reports ready:")
    print(f"  {READINESS_JSON}")
    print(f"  {READINESS_CSV}")
    print(f"  {RESEARCH_REPORT}")
    print(f"  {ZOTERO_REPORT}")
    print("Dashboard available at http://127.0.0.1:8000")

    subprocess.run(
        [
            sys.executable,
            str(ROOT / "web_ui_server.py"),
            "--data-root",
            str(DATA_ROOT),
        ],
        cwd=ROOT,
        check=True,
    )


if __name__ == "__main__":
    main()
