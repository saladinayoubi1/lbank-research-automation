from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


STATE_SCHEMA = "nexus.bybit-prospective-paper-forward.v1"
EVENT_SCHEMA = "nexus.bybit-prospective-paper-forward-event.v1"
FORWARD_ID = "bybit_btc_eth_regime_consensus_prospective_paper_v1_20260826"
STRATEGY_ID = "bybit_btc_eth_regime_consensus_v1"
MINIMUM_BARS = 180
DAILY_BAR_INTERVAL = 6
TERMINAL_STATUS = {"COMPLETE_REVIEW_REQUIRED", "QUARANTINED"}
STATUS_DECISIONS = {
    "WAITING_FOR_FIRST_PROSPECTIVE_BAR": "collect_prospective_paper_evidence",
    "COLLECTING": "collect_prospective_paper_evidence",
    "COMPLETE_REVIEW_REQUIRED": "paper_forward_passed_requires_separate_owner_review",
    "QUARANTINED": "paper_forward_failed_no_promotion",
}
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^(?:sha256:)?[0-9a-f]{64}$")
UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
RUN_URL_RE = re.compile(r"^https://github\.com/[^/\s]+/[^/\s]+/actions/runs/(\d+)$")


class PaperGateReportError(RuntimeError):
    pass


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PaperGateReportError("Paper state is not canonical JSON") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _utc(value: object, *, allow_none: bool = False) -> str | None:
    if value is None and allow_none:
        return None
    if not isinstance(value, str) or not UTC_RE.fullmatch(value):
        raise PaperGateReportError("Paper timestamp is not canonical UTC")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise PaperGateReportError("Paper timestamp is invalid") from exc
    return value


def verify_state(
    state: Mapping[str, Any], *, expected_source_sha: str, expected_run_id: int
) -> None:
    if not isinstance(state, Mapping):
        raise PaperGateReportError("Paper state must be an object")
    if not SHA_RE.fullmatch(expected_source_sha) or expected_run_id <= 0:
        raise PaperGateReportError("Expected workflow binding is invalid")

    unsigned = dict(state)
    claimed = unsigned.pop("state_digest", None)
    if not isinstance(claimed, str) or claimed != _digest(unsigned):
        raise PaperGateReportError("Paper state digest mismatch")

    status = state.get("status")
    checks = {
        "schema": state.get("schema_version") == STATE_SCHEMA,
        "forward": state.get("forward_id") == FORWARD_ID,
        "strategy": state.get("strategy_id") == STRATEGY_ID,
        "status": status in STATUS_DECISIONS,
        "decision": state.get("decision") == STATUS_DECISIONS.get(status),
        "paper": state.get("paper_only") is True,
        "live": state.get("live_trading_enabled") is False,
        "credentials": state.get("private_credentials_used") is False,
        "promotion": state.get("automatic_live_promotion") is False,
        "source": state.get("latest_source_sha") == expected_source_sha,
        "run": state.get("last_run_id") == expected_run_id,
        "profiles": set(state.get("profiles", {})) == {"conservative", "stress"},
    }
    if not all(checks.values()):
        raise PaperGateReportError(f"Paper state contract rejected: {checks}")

    count = state.get("completed_bar_count")
    events = state.get("events")
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise PaperGateReportError("Completed Paper bar count is invalid")
    if not isinstance(events, list) or len(events) != count:
        raise PaperGateReportError("Paper event count is inconsistent")

    previous = "0" * 64
    for sequence, event in enumerate(events, start=1):
        if not isinstance(event, Mapping):
            raise PaperGateReportError("Paper event is not an object")
        event_core = dict(event)
        event_digest = event_core.pop("event_digest", None)
        source_sha = event_core.get("source_sha")
        execution_utc = _utc(event_core.get("execution_utc"))
        if (
            event_core.get("schema_version") != EVENT_SCHEMA
            or event_core.get("sequence") != sequence
            or event_core.get("previous_event_digest") != previous
            or not isinstance(event_digest, str)
            or event_digest != _digest(event_core)
            or not isinstance(source_sha, str)
            or not SHA_RE.fullmatch(source_sha)
            or event_core.get("paper_only") is not True
            or event_core.get("live_trading_enabled") is not False
            or execution_utc is None
        ):
            raise PaperGateReportError("Paper event chain rejected")
        previous = event_digest

    last_execution = _utc(state.get("last_execution_utc"), allow_none=True)
    if events and last_execution != events[-1].get("execution_utc"):
        raise PaperGateReportError("Paper last execution is inconsistent")
    if not events and last_execution is not None:
        raise PaperGateReportError("Empty Paper chain has a last execution")


def build_report(
    state: Mapping[str, Any],
    *,
    expected_source_sha: str,
    expected_run_id: int,
    run_url: str,
    artifact_id: int,
    artifact_digest: str,
) -> tuple[dict[str, Any], str]:
    verify_state(
        state,
        expected_source_sha=expected_source_sha,
        expected_run_id=expected_run_id,
    )
    match = RUN_URL_RE.fullmatch(run_url)
    if not match or int(match.group(1)) != expected_run_id:
        raise PaperGateReportError("Workflow run URL is not bound to the expected run")
    if artifact_id <= 0 or not DIGEST_RE.fullmatch(artifact_digest):
        raise PaperGateReportError("Artifact evidence is invalid")

    status = str(state["status"])
    count = int(state["completed_bar_count"])
    last_execution = state["last_execution_utc"] or "none"
    publish = status in TERMINAL_STATUS or (
        count > 0 and count % DAILY_BAR_INTERVAL == 0
    )
    marker = f"<!-- nexus-paper-gate:v1:{count}:{last_execution}:{status} -->"
    metadata = {
        "schema_version": "nexus.paper-gate-report.v1",
        "publish": publish,
        "marker": marker,
        "status": status,
        "decision": state["decision"],
        "completed_bar_count": count,
        "minimum_completed_bars": MINIMUM_BARS,
        "last_execution_utc": state["last_execution_utc"],
        "state_digest": state["state_digest"],
        "source_sha": expected_source_sha,
        "run_id": expected_run_id,
        "artifact_id": artifact_id,
        "artifact_digest": artifact_digest,
        "paper_only": True,
        "live_trading_enabled": False,
        "automatic_live_promotion": False,
    }

    heading = (
        "## Prospective Paper terminal evidence"
        if status in TERMINAL_STATUS
        else "## Automated prospective Paper daily checkpoint"
    )
    lines = [
        marker,
        heading,
        "",
        f"- Status: `{status}`",
        f"- Completed four-hour bars: `{count} / {MINIMUM_BARS}`",
        f"- Latest execution: `{last_execution}`",
        f"- Workflow run: [{expected_run_id}]({run_url})",
        f"- Source SHA: `{expected_source_sha}`",
        f"- State digest: `{state['state_digest']}`",
        f"- Artifact ID: `{artifact_id}`",
        f"- Artifact digest: `{artifact_digest}`",
        "- Paper-only: `true`; Live: `false`; private credentials: `false`; automatic Live promotion: `false`",
        "",
    ]
    if status == "COMPLETE_REVIEW_REQUIRED":
        lines.append(
            "The observation threshold was reached and the result requires separate human review; no promotion is automatic."
        )
    elif status == "QUARANTINED":
        lines.append(
            "The evidence chain is quarantined and cannot be promoted or used to widen authority."
        )
    else:
        lines.append(
            "The evidence gate remains open until both 30 elapsed days and 180 completed bars are satisfied."
        )
    lines.extend(
        [
            "",
            "Authority remains Research/Backtest/Paper only. No exchange order, Live/L4, credential, signing, billing, deployment, production promotion, financial action, or self-authorization is granted.",
        ]
    )
    return metadata, "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--expected-source-sha", required=True)
    parser.add_argument("--expected-run-id", type=int, required=True)
    parser.add_argument("--run-url", required=True)
    parser.add_argument("--artifact-id", type=int, required=True)
    parser.add_argument("--artifact-digest", required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--markdown", type=Path, required=True)
    args = parser.parse_args()

    try:
        state = json.loads(args.state.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PaperGateReportError(f"Paper state is unavailable: {exc}") from exc
    metadata, markdown = build_report(
        state,
        expected_source_sha=args.expected_source_sha,
        expected_run_id=args.expected_run_id,
        run_url=args.run_url,
        artifact_id=args.artifact_id,
        artifact_digest=args.artifact_digest,
    )
    args.metadata.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.metadata.write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    args.markdown.write_text(markdown, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
