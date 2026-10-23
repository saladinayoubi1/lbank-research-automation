"""One-shot MANUAL 2026-10-23 fixed archival Shadow -> MR40 pre-arm risk.

NEVER a background job or scheduler. ZERO brokerage/private API hooks.
This command first validates the immutable authenticated Oct22 Bybit Spot
source, then (only after Oct23 UTC ends and the official Oct23 daily archive
exists) runs the already-locked six-bar Shadow and independent closed-signal
risk meter. It refuses overwrite and fails closed on partial artifacts.
Archive receipts are POST-DAY observations, never a live close-time fill.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from research.nexus_mr40_bybit_archive_bridge_v1 import BASE_URL
from research.nexus_mr40_bybit_forward_shadow_v1 import (
    NOT_BEFORE, EXPECTED_BRIDGE, check_clock, validate_bridge,
    reuse_oct22_only_if_archive_ws_parity_proven, run as run_shadow)
from research.nexus_mr40_independent_closed_signal_v1 import (
    ROWS_SHA, frozen_rows, canon)
from research.nexus_mr40_prearm_forward_risk_telemetry_v1 import (
    OCT22_CLOSE, OCT22_PARITY, OCT22_SHA, check_lock,
    run as run_risk, verified_json, validate_inputs)

DAY = "2026-10-23"
HTTP_URL = BASE_URL + DAY + ".csv.gz"
OCT22_PARITY_FILE_SHA = "ea5f020264cb3e307bc142f22a9736c8c5afdd5df16fa9615927f887384c099c"


def preflight(root: Path, original_dir: Path):
    """Actual independent Oct22 receipt and locked original sources, no network."""
    original = frozen_rows(original_dir)
    if len(original) != 8514:
        raise ValueError("wrong_unchanged_historical_8514_rows")
    bridge_path = root / "results/bybit_spot_two_day_bridge.json"
    bridge = json.loads(bridge_path.read_bytes())
    if bridge.get("digest") != EXPECTED_BRIDGE or len(validate_bridge(bridge)) != 12:
        raise ValueError("pinned_bridge_authentication_failed")
    archive_dir = root / "results"
    oct22_gz = archive_dir / "Bybit_BTCUSDT_Spot_2026-10-22.csv.gz"
    oct22_proof = archive_dir / "bybit_oct22_ticks_vs_ws_reconciliation.json"
    if hashlib.sha256(oct22_proof.read_bytes()).hexdigest() != OCT22_PARITY_FILE_SHA:
        raise ValueError("actual_oct22_archive_vs_ws_proof_file_SHA_changed")
    old_day, evidence = reuse_oct22_only_if_archive_ws_parity_proven(oct22_gz, oct22_proof)
    if (len(old_day) != 6
        or evidence.get("gzip_sha256") != OCT22_SHA
        or evidence.get("oct22_prior_verified_live_WS_same_venue_parity_digest") != OCT22_PARITY):
        raise ValueError("genuine_oct22_official_trade_source_and_live_ws_mismatch")
    history_file = archive_dir / "mr40_oct22_spot_verified_historical_closed_state_20261023.json"
    history, old_digest = verified_json(history_file)
    if (old_digest != OCT22_CLOSE
        or history.get("original_entry_markers") != 47
        or history.get("original_exit_markers") != 47
        or history.get("oct22_first_entry_markers") != 0
        or history.get("oct22_natural_exit_markers") != 0
        or history.get("oct22_last_closed_target_long") is not False
        or history.get("trusted_oct22_archive_gzip_sha256") != OCT22_SHA):
        raise ValueError("oct22_authenticated_historical_MR40_flat_state_changed")
    shadow_lock = root / "research/mr40_forward_archive_shadow_protocol_20261022.json"
    shadow_spec = json.loads(shadow_lock.read_bytes())
    if (shadow_spec.get("schema") != "nexus.mr40.prospective_spot_archive_shadow_protocol.v1"
        or shadow_spec.get("fixed_observation_day") != DAY
        or shadow_spec.get("prerequisites", {}).get("historical_bridge_oct20_21_logical_digest") != EXPECTED_BRIDGE
        or shadow_spec.get("constraints", {}).get("orders") != 0
        or shadow_spec.get("constraints", {}).get("promote") is not False):
        raise ValueError("original_oct23_shadow_contract_drift")
    risk_lock = root / "research/mr40_prearm_forward_risk_telemetry_protocol_20261023.json"
    check_lock(json.loads(risk_lock.read_bytes()))
    return {
        "original_dir": original_dir,
        "bridge": bridge_path,
        "oct22_report": oct22_proof,
        "oct22_history": history_file,
        "archive_dir": archive_dir,
        "shadow_lock": shadow_lock,
        "risk_lock": risk_lock,
    }


def inspect_targets(root: Path):
    a = root / "results/Bybit_BTCUSDT_Spot_2026-10-23.csv.gz"
    shadow = root / "results/bybit_oct23_spot_forward_shadow_20261024.json"
    risk = root / "results/mr40_oct23_prearm_forward_risk_telemetry_20261024.json"
    if a.exists() != shadow.exists():
        raise ValueError("partial_oct23_archive_shadow_trusted_pair_requires_manual_review")
    if risk.exists():
        raise ValueError("risk_report_already_exists_refuse_any_mutation")
    return a, shadow, risk


def one_official_head():
    """At most ONE external read-only HEAD, after UTC day completion."""
    req = urllib.request.Request(HTTP_URL, headers={
        "User-Agent": "NEXUS-MR40-fixed-Oct23-no-orders-manual-one-shot"
    }, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            code = r.status
            if code != 200:
                raise ValueError("unexpected_official_spot_HEAD_status_" + str(code))
            return {"status": code, "bytes": r.headers.get("Content-Length"),
                    "last_modified": r.headers.get("Last-Modified")}
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {"status": 404, "unpublished": True}
        raise


def execute(root, original_dir, *, now_ms=None, preflight_only=False,
            official_head=one_official_head, run_shadow_action=run_shadow,
            run_risk_action=run_risk):
    """Manual, deterministic, nonrecurring orchestration, never brokerage."""
    root, original_dir = Path(root), Path(original_dir)
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    if type(now_ms) is not int:
        raise ValueError("invalid_UTC_clock")
    if now_ms < NOT_BEFORE:
        # No file access or network before the precommitted UTC boundary.
        return {"status": "NOT_YET_TIME", "fixed_day": DAY,
                "earliest_utc": "2026-10-24T00:00:00Z", "orders": 0}
    check_clock(now_ms)
    a, shadow, risk = inspect_targets(root)
    trusted = preflight(root, original_dir)
    if not a.exists():
        if preflight_only:
            return {"status": "READY_FOR_OFFICIAL_SOURCE_PUBLICATION",
                    "fixed_day": DAY, "official_gzip_local": False,
                    "no_archive_http_or_order_performed": True}
        head = official_head()
        if head["status"] == 404:
            return {"status": "OFFICIAL_DAY_NOT_PUBLISHED",
                    "day": DAY, "official_url": HTTP_URL, "orders": 0}
        if head["status"] != 200:
            raise ValueError("official_spot_full_day_source_unavailable")
        # This fixed function does its own full source-GET+rollup+receipt and
        # EXCLUSIVE double write, with no alternate venue or date fallback.
        run_shadow_action(
            trusted["shadow_lock"], original_dir, trusted["bridge"],
            trusted["archive_dir"], shadow,
            oct22_verified_audit=trusted["oct22_report"])
        if not (a.exists() and shadow.exists()):
            raise ValueError("new_oct23_official_archive_and_shadow_pair_incomplete")
    elif preflight_only:
        return {"status": "READY_FOR_REPLAY_EXISTING_OFFICIAL_SOURCE",
                "fixed_day": DAY, "orders": 0}
    # Whether freshly created or already existing, the next step independently
    # validates gzip SHA+CRC+CSV+rollup; recomputes all six Oct23 MR40 signals
    # from 8514 original + 12 bridge + 6 verified Oct22 + 6 genuine Oct23.
    # A spoofed self-consistent JSON digest cannot bypass the new signal gate.
    run_risk_action(
        trusted["risk_lock"], shadow, trusted["oct22_history"], a, risk,
        original_dir=original_dir, bridge_file=trusted["bridge"],
        oct22_source_report=trusted["oct22_report"])
    if not risk.is_file():
        raise ValueError("new_oct23_forward_risk_report_missing_after_replay")
    _, risk_digest = verified_json(risk)
    return {"status": "LOCKED_POST_DAY_RESEARCH_RISK_TELEMETRY_COMPLETE",
            "fixed_day": DAY, "report_digest": risk_digest, "orders": 0,
            "paper_modified": False, "live": False,
            "no_fill_or_economic_edge_claim": True}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--original-dir", type=Path, required=True)
    p.add_argument("--preflight-only", action="store_true",
                   help="Only validate precommitted source data, after date gate; never download")
    v = p.parse_args()
    outcome = execute(v.root, v.original_dir, preflight_only=v.preflight_only)
    print(json.dumps(outcome, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
