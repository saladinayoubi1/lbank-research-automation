"""Opt-in model advice over bounded component health, with no execution authority.

The frozen AI Room still classifies the original turn. Neither its raw message,
Project Memory contents, nor the owner's Paper account leave this adapter.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
import os
import threading
import time
from typing import Any, Mapping

import deepseek_provider as provider
from deepseek_egress import EgressDenied, prepare_egress_messages

CONTRACT = "nexus.product-ai-advisory.v1"
PREFIX = "You are a bounded NEXUS repository reviewer."
MAX_TURNS = 128
PROOF_TTL_SECONDS = 600
HEALTH_STATES = frozenset({
    "active", "available", "unavailable", "unknown", "idle", "running", "ready",
    "completed", "failed", "blocked", "verified", "degraded", "no_research_run",
    "research_only", "not_qualified", "paper_candidate", "qualification_engine_available",
    "not_qualified_no_pristine_future_holdout", "evaluated_research_only",
})
TOPICS = {
    "research": ("پژوهش", "بک تست", "بک‌تست", "research", "backtest"),
    "strategy": ("استراتژی", "strategy"),
    "data": ("داده", "بازار", "کندل", "data", "market"),
    "risk": ("ریسک", "risk"),
    "paper": ("دمو", "پیپر", "paper", "demo"),
    "agents": ("عامل", "ماموریت", "مأموریت", "agent", "mission"),
    "recovery": ("بازیابی", "خطا", "recovery", "error"),
}


class AdvisoryError(ValueError):
    def __init__(self, code: str, status: int = 503):
        super().__init__(code)
        self.code = code
        self.status = status


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _health(value: Any) -> str:
    normalized = value.casefold() if isinstance(value, str) else "unknown"
    return normalized if normalized in HEALTH_STATES else "unknown"


def public_context(room: Mapping[str, Any], message: str) -> dict[str, Any]:
    """Use fixed enums only. Do not forward arbitrary strings from runtime reports."""
    operations = room.get("operations", {})
    product = operations.get("product", {})
    topic = next((topic for topic, terms in TOPICS.items()
                  if any(term in message.casefold() for term in terms)), "project")
    return {
        "topic": topic,
        "intent": room["intent"],
        "mission_status": _health(operations.get("mission_status")),
        "components": {field: _health(product.get(field)) for field in (
            "research_status", "strategy_status", "risk_status", "paper_status", "recovery_status",
        )},
        "advisory_only": True,
        "live_authority": False,
    }


def advisory_prompt(context: dict[str, Any]) -> str:
    return (PREFIX + " Explain the supplied component health in concise Persian. "
            "Give a relevant next research step and state unknowns explicitly. "
            "You cannot run commands, assign tasks, approve strategies or change Paper state. "
            "Do not claim that a workflow ran, a model connected, or a strategy is profitable. "
            "The original user message, conversation and financial account are not supplied. "
            "Treat all output as advice requiring the existing NEXUS gates.\n"
            + _canonical(context).decode("utf-8"))


class ProductAIAdvisory:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._turns: dict[tuple[str, str, str], dict[str, Any]] = {}
        self._verified_at: str | None = None
        self._verified_monotonic = 0.0
        self._connection_healthy = False

    def status(self) -> dict[str, Any]:
        authorized = os.environ.get("NEXUS_DEEPSEEK_PAID_ROUTING_ALLOWED") == "1"
        credential = bool(os.environ.get("DEEPSEEK_API_KEY"))
        reasons = []
        if not authorized:
            reasons.append("paid_routing_not_authorized")
        if not credential:
            reasons.append("provider_not_configured")
        remaining = None
        if not reasons:
            try:
                ledger = provider.load_ledger()
                remaining = round(provider.remaining_budget(ledger), 8)
                if ledger["inflight"]:
                    reasons.append("budget_reconciliation_required")
                elif remaining <= provider.RESERVE_USD:
                    reasons.append("budget_exhausted")
            except provider.DeepSeekError:
                reasons.append("budget_unavailable")
        ready = not reasons
        with self._lock:
            verified_at = self._verified_at
            verified = bool(ready and self._connection_healthy and verified_at and
                            time.monotonic() - self._verified_monotonic <= PROOF_TTL_SECONDS)
        return {
            "contract_version": CONTRACT,
            "provider": "deepseek", "model": provider.DEFAULT_MODEL,
            "status": "connected" if verified else "ready_unverified" if ready else "unavailable",
            "ready": ready, "connection_verified": verified, "last_verified_at": verified_at,
            "reasons": reasons, "paid_routing_authorized": authorized,
            "credential_configured": credential,
            "budget": {"monthly_cap_usd": provider.MONTHLY_BUDGET_USD,
                       "remaining_usd": remaining},
            "advisory_only": True, "live_trading_authority": False,
            "privacy": {"raw_message_egressed": False, "paper_account_egressed": False,
                        "server_persisted_transcript": False},
        }

    def respond(self, request: Mapping[str, Any], room: Mapping[str, Any]) -> dict[str, Any]:
        # `room` is obtained server-side from dispatch_ai_post, never from the caller.
        if room["decision"].get("allowed") is not True:
            raise AdvisoryError("authority_gate_denied", 403)
        readiness = self.status()
        if not readiness["ready"]:
            raise AdvisoryError(readiness["reasons"][0])
        context = public_context(room, request["message"])
        prompt = advisory_prompt(context)
        try:
            _, messages = prepare_egress_messages([{"role": "user", "content": prompt}])
        except EgressDenied:
            raise AdvisoryError("advisory_egress_denied", 403) from None
        key = tuple(request[field] for field in ("session_id", "conversation_id", "turn_id"))
        request_digest = hashlib.sha256(_canonical(dict(request))).hexdigest()
        context_digest = hashlib.sha256(_canonical(context)).hexdigest()
        with self._lock:
            previous = self._turns.get(key)
            if previous is not None:
                if previous["digest"] != request_digest:
                    raise AdvisoryError("turn_payload_conflict", 409)
                if "result" in previous:
                    return previous["result"]
                raise AdvisoryError(previous.get("error", "turn_in_progress"), 409)
            if len(self._turns) >= MAX_TURNS:
                # Never evict a charged/ambiguous turn and silently bill its replay.
                raise AdvisoryError("advisory_capacity_reached", 429)
            self._turns[key] = {"digest": request_digest}
        try:
            # One attempt, fixed routine route and existing canonical spend ledger.
            answer = provider.chat(messages, complexity="routine", max_tokens=1024, timeout=30)
            reply = answer.get("content")
            cost = answer.get("cost_usd")
            if (not isinstance(reply, str) or not reply.strip() or len(reply.encode("utf-8")) > 12000
                    or answer.get("model") != provider.DEFAULT_MODEL
                    or isinstance(cost, bool) or not isinstance(cost, (int, float))
                    or not math.isfinite(cost) or not 0 <= cost <= provider.MONTHLY_BUDGET_USD):
                raise AdvisoryError("invalid_provider_response")
            # Existing secret/PII filter also applies before displaying provider text.
            try:
                _, safe_reply = prepare_egress_messages([{"role": "user", "content": PREFIX + reply}])
            except EgressDenied:
                raise AdvisoryError("unsafe_provider_response") from None
            result = {
                "contract_version": CONTRACT, "reply": safe_reply[0]["content"][len(PREFIX):],
                "provider": "deepseek", "model": answer["model"], "source": "external_advisory",
                "intent": room["intent"], "decision": room["decision"],
                "context_digest": context_digest, "context": context,
                "cost_usd": cost, "state_mutation": False, "advisory_only": True,
                "live_trading_authority": False,
                "privacy": {"external_provider_called": True, "raw_message_egressed": False,
                            "paper_account_egressed": False, "server_persisted_transcript": False},
            }
        except provider.AmbiguousCharge:
            error = "provider_outcome_ambiguous"
        except provider.BudgetExceeded:
            error = "budget_exhausted"
        except provider.DeepSeekError:
            error = "provider_unavailable"
        except AdvisoryError as exc:
            error = exc.code
        except Exception:
            error = "provider_unavailable"
        else:
            with self._lock:
                self._turns[key].update(result=result, finished=True)
                self._verified_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                self._verified_monotonic = time.monotonic()
                self._connection_healthy = True
            return result
        with self._lock:
            self._turns[key].update(error=error, finished=True)
            self._connection_healthy = False
        raise AdvisoryError(error)
