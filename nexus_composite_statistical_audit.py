"""Source-bound, conservative statistical review of NEXUS composite candidates.

An observed 2-symbol x 3-historical-split x 2-cost grid IS NOT 12 independent
samples. In particular, stress and conservative evaluate the SAME trades.
Previously inspected historical test folds are never a pristine holdout.

This module provides (1) automatic digest-bound *historical limitations* for
Agent Manager Research/QA, and (2) an optional deterministic one-sided sign-test
diagnostic for separately supplied, pre-frozen, non-overlapping future WEEKLY
returns. The latter counts each week once, adjusts for all previously tried
mechanisms and both cost profiles, and NEVER authorizes REG-50 or Paper/Live.

The p-values are only heuristic if weekly observations are serially correlated,
the benchmark/strategy were refined, the record freeze was not independently
time-attested, or data/fill provenance was not separately verified. These
conditions cannot be proven by a self-declared JSON or by matching hashes.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Any

SCHEMA_HISTORICAL = "nexus.composite-historical-statistical-review.v1"
SCHEMA_FORWARD = "nexus.composite-prospective-weekly-statistical-review.v1"
SCHEMA_EVIDENCE = "nexus.composite-prospective-weekly-evidence.v1"
EXPECTED_SYMBOLS = ("BTCUSDT", "ETHUSDT")
EXPECTED_PROFILES = ("conservative", "stress")
EXPECTED_PARTS = ("train", "validation", "historically_inspected_test")
SOURCE_SHA = re.compile(r"^[0-9a-f]{40}$")
HEX_SHA = re.compile(r"^[0-9a-f]{64}$")
MIN_WEEKLY_WINDOWS = 12
ALPHA_FAMILYWISE = 0.05
WEEK = timedelta(days=7)
MAX_WEEKLY_WINDOWS = 104


class StatisticalReviewError(ValueError):
    pass


def _hash(value: Any) -> str:
    try:
        packed = json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise StatisticalReviewError("evidence cannot be canonical JSON") from exc
    return hashlib.sha256(packed).hexdigest()


def _stamp(value: Any) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise StatisticalReviewError("prospective timestamp must be exact UTC Z")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError) as exc:
        raise StatisticalReviewError("invalid prospective timestamp") from exc
    if parsed.tzinfo != timezone.utc:
        raise StatisticalReviewError("prospective timestamp is not UTC")
    return parsed


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise StatisticalReviewError(f"{name} is not numeric")
    result = float(value)
    if not math.isfinite(result) or abs(result) > 100:
        raise StatisticalReviewError(f"{name} is non-finite or outside 100pct bound")
    return result


def _ledger_counter(ledger: Mapping[str, Any]) -> dict[str, int]:
    if not isinstance(ledger, Mapping):
        raise StatisticalReviewError("novelty ledger must be available")
    if _hash({k: v for k, v in ledger.items() if k != "ledger_digest"}) != ledger.get("ledger_digest"):
        raise StatisticalReviewError("novelty ledger digest mismatch")
    history = ledger.get("config_fingerprints_evaluated")
    tested = ledger.get("mechanisms_evaluated")
    screened = ledger.get("frontier_screened_mechanisms", [])
    if (
        not isinstance(history, list) or not isinstance(tested, list)
        or not isinstance(screened, list)
        or any(not isinstance(x, str) or not HEX_SHA.fullmatch(x) for x in history)
        or any(not isinstance(x, str) or not x for x in tested + screened)
        or len(history) != len(set(history))
        or len(tested) != len(set(tested))
        or len(screened) != len(set(screened))
    ):
        raise StatisticalReviewError("novelty ledger history is malformed or duplicated")
    # A mechanism screened on training but not fully evaluated is a search
    # attempt, and cannot be omitted from the multiple-comparison count.
    unseen_screened = set(screened) - set(tested)
    attempted = len(history) + len(unseen_screened)
    if attempted < 1:
        raise StatisticalReviewError("statistical search includes no evaluated hypothesis")
    return {
        "evaluated_parameter_fingerprints": len(history),
        "additional_screened_mechanisms": len(unseen_screened),
        "hypotheses_considered_at_least": attempted,
    }


def historical_review(report: Mapping[str, Any], ledger: Mapping[str, Any]) -> dict[str, Any]:
    """Non-authoritative gate: reviewed history never proves future edge."""
    if not isinstance(report, Mapping):
        raise StatisticalReviewError("research report is unavailable")
    unsigned = {k: v for k, v in report.items() if k != "report_digest"}
    if (
        report.get("report_digest") != _hash(unsigned)
        or report.get("status") != "EVALUATED_RESEARCH_ONLY"
        or report.get("historical_test_pristine") is not False
        or report.get("independent_future_data_required") is not True
        or report.get("research_only") is not True
        or report.get("auto_demo_promotion") is not False
        or report.get("live_enabled") is not False
        or report.get("ledger_digest") != ledger.get("ledger_digest")
        or not SOURCE_SHA.fullmatch(str(report.get("source_sha", "")))
        or not HEX_SHA.fullmatch(str(report.get("archive_sha256", "")))
    ):
        raise StatisticalReviewError("historical report lineage/authority is invalid")
    rows = report.get("rows")
    if not isinstance(rows, list) or len(rows) != 12:
        raise StatisticalReviewError("historical two-symbol/fold/cost grid incomplete")
    expected = {
        (symbol, part, profile)
        for symbol in EXPECTED_SYMBOLS
        for part in EXPECTED_PARTS
        for profile in EXPECTED_PROFILES
    }
    actual: set[tuple[str, str, str]] = set()
    diagnostics: dict[str, Any] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise StatisticalReviewError("historical row malformed")
        key = (row.get("symbol"), row.get("part"), row.get("profile"))
        if key not in expected or key in actual:
            raise StatisticalReviewError("historical duplicate/unsupported research cell")
        actual.add(key)
        _finite(row.get("net_return_pct"), "historical net_return_pct")
        if type(row.get("closed_round_trips")) is not int or row["closed_round_trips"] < 0:
            raise StatisticalReviewError("historical trade count is invalid")
        if row.get("trade_count_limit") is not None:
            raise StatisticalReviewError("an artificial trade count limit is forbidden")
        diagnostics["|".join(key)] = {
            "net_return_pct": row["net_return_pct"],
            "closed_round_trips": row["closed_round_trips"],
        }
    if actual != expected:
        raise StatisticalReviewError("historical cost/fold grid omitted")
    attempts = _ledger_counter(ledger)
    screening = report.get("frontier_screening")
    if isinstance(screening, Mapping):
        n = screening.get("candidate_count")
        if type(n) is not int or n < 1:
            raise StatisticalReviewError("historical frontier candidate count invalid")
        # Do not silently under-report the current frontier ranking attempt.
        attempts["hypotheses_considered_at_least"] = max(
            attempts["hypotheses_considered_at_least"], n,
        )
    core = {
        "schema_version": SCHEMA_HISTORICAL,
        "source_sha": report["source_sha"],
        "archive_sha256": report["archive_sha256"],
        "report_digest": report["report_digest"],
        "ledger_digest": ledger["ledger_digest"],
        "selected_config_fingerprint": report["selected"]["fingerprint"],
        "cells_checked": 12,
        "independent_observations_inferred_from_cells": 0,
        "cost_profiles_are_correlated": True,
        "btc_eth_are_potentially_correlated": True,
        "historical_test_pristine": False,
        "valid_future_holdout_present": False,
        "statistical_significance_established": False,
        "decision": "INSUFFICIENT_PRISTINE_PROSPECTIVE_EVIDENCE",
        "reason_codes": [
            "HISTORICAL_TEST_PREVIOUSLY_INSPECTED",
            "COST_PROFILE_AND_PAIR_NONINDEPENDENCE",
            "NO_SOURCE_BOUND_FROZEN_PROSPECTIVE_WINDOWS",
        ],
        "search_multiplicity": attempts,
        "descriptive_historical_cells": diagnostics,
        "historical_minimum_trade_count": None,
        "registry_eligibility_authority": False,
        "owner_demo_admission_allowed": False,
        "automatic_strategy_promotion": False,
        "live_trading_authority": False,
    }
    return {**core, "statistical_review_digest": _hash(core)}


def _sign_p_value(n: int, positive: int) -> float:
    if n <= 0 or not 0 <= positive <= n:
        raise StatisticalReviewError("sign-test counts invalid")
    # Exact one-sided Pr[X >= k] for independent Bernoulli signs under p=0.5.
    # NO claim of independence is inferred merely from non-overlapping dates.
    return sum(math.comb(n, k) for k in range(positive, n + 1)) / 2**n


def prospective_diagnostic(
    evidence: Mapping[str, Any], ledger: Mapping[str, Any],
) -> dict[str, Any]:
    """Observational statistical diagnostic ONLY; never promotes or certifies."""
    if not isinstance(evidence, Mapping) or evidence.get("schema_version") != SCHEMA_EVIDENCE:
        raise StatisticalReviewError("prospective evidence schema unavailable")
    freeze = evidence.get("freeze")
    if not isinstance(freeze, Mapping) or set(freeze) != {
        "candidate_source_sha", "candidate_config_digest", "ledger_digest",
        "frozen_before_utc", "candidate_digest", "planned_weekly_windows",
        "analysis_not_before_utc",
    }:
        raise StatisticalReviewError("prospective research freeze is missing")
    for key in ("candidate_config_digest", "ledger_digest", "candidate_digest"):
        if not HEX_SHA.fullmatch(str(freeze.get(key, ""))):
            raise StatisticalReviewError("prospective frozen digest missing")
    if not SOURCE_SHA.fullmatch(str(freeze.get("candidate_source_sha", ""))):
        raise StatisticalReviewError("prospective frozen source SHA invalid")
    if freeze["ledger_digest"] != ledger.get("ledger_digest"):
        raise StatisticalReviewError("prospective freeze does not bind novelty ledger")
    frozen = _stamp(freeze["frozen_before_utc"])
    locked_count = freeze["planned_weekly_windows"]
    if type(locked_count) is not int or not 1 <= locked_count <= MAX_WEEKLY_WINDOWS:
        raise StatisticalReviewError("future observation count must be preregistered")
    preregistered_analysis = _stamp(freeze["analysis_not_before_utc"])
    attempt = _ledger_counter(ledger)
    rows = evidence.get("weekly_windows")
    if not isinstance(rows, list) or len(rows) != locked_count:
        raise StatisticalReviewError("premature peeking or changed weekly horizon refused")
    success = {profile: 0 for profile in EXPECTED_PROFILES}
    previous = None
    for row in rows:
        if not isinstance(row, Mapping) or set(row) != {
            "week_start_utc", "week_end_utc", "dataset_bindings_sha256",
            "conservative_net_return_pct", "stress_net_return_pct",
            "benchmark_net_return_pct", "paper_event_digest",
        }:
            raise StatisticalReviewError("weekly prospective row schema invalid")
        start, end = _stamp(row["week_start_utc"]), _stamp(row["week_end_utc"])
        if (
            end - start != WEEK or start < frozen or
            (previous is not None and start != previous)
        ):
            raise StatisticalReviewError("weekly holdout overlaps, precedes freeze or has a gap")
        previous = end
        links = row["dataset_bindings_sha256"]
        if not isinstance(links, Mapping) or set(links) != set(EXPECTED_SYMBOLS):
            raise StatisticalReviewError("both bound canonical sources required")
        if any(not HEX_SHA.fullmatch(str(links[s])) for s in EXPECTED_SYMBOLS):
            raise StatisticalReviewError("unsigned, missing or malformed source binding")
        if not HEX_SHA.fullmatch(str(row["paper_event_digest"])):
            raise StatisticalReviewError("prospective paper event receipt digest missing")
        benchmark = _finite(row["benchmark_net_return_pct"], "benchmark")
        for profile in EXPECTED_PROFILES:
            observed = _finite(row[f"{profile}_net_return_pct"], f"{profile}_net_return_pct")
            if observed > benchmark:
                success[profile] += 1
    length = len(rows)
    if previous != preregistered_analysis:
        raise StatisticalReviewError("prospective end differs from preregistered analysis time")
    multiplicity = 2 * attempt["hypotheses_considered_at_least"]
    raw = {profile: _sign_p_value(length, wins) for profile, wins in success.items()}
    adjusted = {profile: min(1.0, multiplicity * p) for profile, p in raw.items()}
    diagnostic_pass = bool(
        length >= MIN_WEEKLY_WINDOWS and
        all(adjusted[profile] < ALPHA_FAMILYWISE for profile in EXPECTED_PROFILES)
    )
    reasons: list[str] = []
    if length < MIN_WEEKLY_WINDOWS:
        reasons.append("INSUFFICIENT_NONOVERLAPPING_FUTURE_WEEKS")
    if not diagnostic_pass:
        reasons.append("SEARCH_ADJUSTED_SIGN_SCREEN_NOT_SUPPORTED")
    # A JSON digest cannot independently prove source authenticity, first
    # availability after freeze, stationarity, exchange fills or honest
    # bench selection. Never let its p-value become an approval gate.
    reasons.extend([
        "DATA_AND_FREEZE_INDEPENDENT_ATTESTATION_REQUIRED",
        "WEEKLY_SIGN_INDEPENDENCE_NOT_PROVEN",
        "ACTUAL_PROSPECTIVE_PAPER_CLOSES_UNVERIFIED",
    ])
    core = {
        "schema_version": SCHEMA_FORWARD,
        "candidate_source_sha": freeze["candidate_source_sha"],
        "candidate_config_digest": freeze["candidate_config_digest"],
        "candidate_digest": freeze["candidate_digest"],
        "ledger_digest": ledger["ledger_digest"],
        "freeze_utc": freeze["frozen_before_utc"],
        "preregistered_analysis_not_before_utc": freeze["analysis_not_before_utc"],
        "preregistered_weekly_windows": locked_count,
        "weekly_windows_observed": length,
        "raw_onesided_sign_p": raw,
        "bonferroni_familywise_adjusted_p": adjusted,
        "weekly_excess_positive_count": success,
        "multiple_comparison_count": multiplicity,
        "alpha_familywise": ALPHA_FAMILYWISE,
        "test_assumptions": [
            "weeks_nonoverlapping_not_proof_of_independence",
            "two_cost_profiles_on_same_trades_are_not_two_samples",
            "benchmark_must_be_independently_preregistered",
            "no_future_window_may_be_selected_or_retested",
        ],
        "descriptive_sign_test_supported": diagnostic_pass,
        "statistical_edge_established": False,
        "pristine_prospective_proof_verified": False,
        "historical_minimum_trade_count": None,
        "decision": "DIAGNOSTIC_REQUIRES_INDEPENDENT_FUTURE_ATTESTATION",
        "reason_codes": reasons,
        "registry_eligibility_authority": False,
        "owner_demo_admission_allowed": False,
        "automatic_strategy_promotion": False,
        "live_trading_authority": False,
    }
    return {**core, "statistical_review_digest": _hash(core)}
