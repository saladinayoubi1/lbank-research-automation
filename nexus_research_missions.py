"""Research-only continuation of an independently verified Agent lease.

This proof sequence does not cap strategy count or trade count. A follow-on
lease MUST inherit its predecessor's exact checked numerical frontier and
select a different causal mechanism. If no different reviewed mechanism is
available, it fails closed for Developer Agent review instead of retesting
the same failed mechanism or promoting anything to Paper.
"""
from __future__ import annotations

import re
from typing import Any

FIRST = "P7-RESEARCH-COMPOSITE-001"
SECOND = "P7-RESEARCH-COMPOSITE-002"
THIRD = "P7-RESEARCH-COMPOSITE-003"
FOURTH = "P7-RESEARCH-COMPOSITE-004"
FIFTH = "P7-RESEARCH-COMPOSITE-005"
SIXTH = "P7-RESEARCH-COMPOSITE-006"
SEVENTH = "P7-RESEARCH-COMPOSITE-007"
EIGHTH = "P7-RESEARCH-COMPOSITE-008"
NINTH = "P7-RESEARCH-COMPOSITE-009"
# Future successors are definitions only; each remains inactive until its
# immediate predecessor has a durable independent-QA DONE receipt.
PREDECESSOR = {
    SECOND: FIRST, THIRD: SECOND, FOURTH: THIRD, FIFTH: FOURTH,
    SIXTH: FIFTH, SEVENTH: SIXTH, EIGHTH: SEVENTH, NINTH: EIGHTH,
}
TASKS = frozenset((FIRST, *PREDECESSOR))
SOURCE_HEX = re.compile(r"^[0-9a-f]{40}$")
DIGEST_HEX = re.compile(r"^[0-9a-f]{64}$")
ANCESTRY = (
    "research_predecessor_source_sha",
    "research_predecessor_receipt_digest",
    "research_predecessor_qa_digest",
    "research_predecessor_ledger_digest",
    "research_predecessor_mechanism",
)
SOURCE_KEY = ANCESTRY[0]
DIGEST_KEYS = ANCESTRY[1:4]
MECHANISM_KEY = ANCESTRY[4]


def attested_predecessor(task: dict[str, Any]) -> dict[str, str]:
    """Require distinct real producer/QA and exact original receipt binding."""
    production = task.get("result_evidence")
    qa = task.get("verification_evidence")
    if (
        task.get("id") not in PREDECESSOR.values()
        or task.get("status") != "DONE"
        or task.get("producer") != "research-agent"
        or task.get("verifier") != "qa-verifier-agent"
        or not isinstance(production, dict)
        or not isinstance(qa, dict)
        or production.get("executor") != "nexus-real-composite-backtest"
        or qa.get("executor") != "nexus-independent-composite-numeric-qa"
        or production.get("independent_qa_complete") is not False
        or qa.get("independent_qa_complete") is not True
        or production.get("auto_demo_promotion") is not False
        or qa.get("auto_demo_promotion") is not False
        or production.get("live_enabled") is not False
        or qa.get("live_enabled") is not False
        or qa.get("producer_lease_id") != task.get("research_producer_lease_id")
        or qa.get("producer_receipt_digest") != production.get("receipt_digest")
        or qa.get("source_sha") != production.get("source_sha")
        or not SOURCE_HEX.fullmatch(str(production.get("source_sha", "")))
        or not all(DIGEST_HEX.fullmatch(str(production.get(k, "")))
                   for k in ("receipt_digest", "ledger_digest", "prior_ledger_digest",
                             "config_fingerprint"))
        or not DIGEST_HEX.fullmatch(str(qa.get("qa_digest", "")))
        or not isinstance(production.get("mechanism"), str)
        or len(production["mechanism"]) > 80
        or not production["mechanism"]
    ):
        raise ValueError("previous real Research+independent-QA evidence is not exact")
    return dict(zip(ANCESTRY, (
        production["source_sha"], production["receipt_digest"], qa["qa_digest"],
        production["ledger_digest"], production["mechanism"],
    )))


def validate_ancestry(data: dict[str, Any]) -> dict[str, str]:
    if (
        not isinstance(data, dict)
        or set(data) != set(ANCESTRY)
        or not SOURCE_HEX.fullmatch(str(data.get(SOURCE_KEY, "")))
        or any(not DIGEST_HEX.fullmatch(str(data.get(k, ""))) for k in DIGEST_KEYS)
        or not isinstance(data.get(MECHANISM_KEY), str)
        or not re.fullmatch(r"[a-z][a-z0-9_]{2,79}", data[MECHANISM_KEY])
    ):
        raise ValueError("successor Research dispatch lacks exact predecessor attestation")
    return dict(data)
