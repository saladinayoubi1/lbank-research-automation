"""Prepare local reports and launch the browser dashboard."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from integration_report_provenance import ENVELOPE_SCHEMA, build_envelope

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


def _source_identity() -> tuple[str, str, str]:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
        capture_output=True, text=True,
    )
    commit = result.stdout.strip()
    run = os.environ.get("GITHUB_RUN_ID")
    workflow_run = f"github-{run}" if run and run.isdigit() and not run.startswith("0") else f"local-{commit[:12]}"
    generated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return commit, workflow_run, generated_at


def _write_bound_report(path: Path, *, kind: str, report: dict) -> None:
    commit, workflow_run, generated_at = _source_identity()
    envelope = build_envelope(
        kind=kind, report=report, source_commit=commit,
        workflow_run=workflow_run, generated_at=generated_at,
    )
    path.write_text(json.dumps(envelope, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _bind_existing(path: Path, *, kind: str) -> bool:
    if not path.exists():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Invalid existing {kind} report") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"Invalid existing {kind} report")
    if payload.get("schema") == ENVELOPE_SCHEMA:
        return True
    _write_bound_report(path, kind=kind, report=payload)
    return True


def ensure_research_report() -> None:
    if _bind_existing(RESEARCH_REPORT, kind="research"):
        return
    payload = {
        "schema_version": "1.1.0",
        "status": "research-only",
        "paper_trading_only": True,
        "claims": [],
        "evidence": [],
        "next_review_due": datetime.now(timezone.utc).date().isoformat(),
    }
    _write_bound_report(RESEARCH_REPORT, kind="research", report=payload)


def ensure_zotero_report() -> None:
    if _bind_existing(ZOTERO_REPORT, kind="zotero"):
        return
    legacy = LEGACY_INTEGRATION_ROOT / ZOTERO_REPORT.name
    if legacy.exists():
        shutil.copy2(legacy, ZOTERO_REPORT)
        _bind_existing(ZOTERO_REPORT, kind="zotero")
        return
    if not REFERENCE_JSON.exists():
        raise FileNotFoundError(f"Missing reference file: {REFERENCE_JSON}")
    cmd = [
        sys.executable,
        str(ROOT / "tools" / "zotero_metadata_audit.py"),
        str(REFERENCE_JSON),
        "--json",
    ]
    result = subprocess.run(
        cmd,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    # zotero_metadata_audit.py uses exit code 1 to mean metadata findings were
    # detected. That is a valid audit result, not a launcher failure. Exit code
    # 2 (or any unexpected code) represents an actual audit execution failure.
    if result.returncode not in (0, 1):
        raise subprocess.CalledProcessError(
            result.returncode,
            cmd,
            output=result.stdout,
            stderr=result.stderr,
        )
    if not result.stdout.strip():
        raise RuntimeError("Zotero metadata audit produced no JSON report")
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Zotero metadata audit produced invalid JSON") from exc
    _write_bound_report(ZOTERO_REPORT, kind="zotero", report=report)


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
