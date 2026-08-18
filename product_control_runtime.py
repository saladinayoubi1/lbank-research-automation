from __future__ import annotations

import csv
import io
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Mapping

from paper_event_store import build_event, replay
from product_runtime import ProductRuntime, _paper_provenance, _risk_policy, _risk_state, _session_signal_count, serialize_portfolio

CONTROL_CONTRACT = "nexus.product-controls.v1"


class ProductControlError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class ProductControlRuntime:
    def __init__(self, runtime: ProductRuntime) -> None:
        self.runtime = runtime

    def _append_control_event(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self.runtime._lock:
            events = self.runtime._ensure_account()
            state = replay(events).state
            at = _now()
            correlation = f"product-control:{uuid.uuid4().hex}"
            event = build_event(
                event_id=f"control:{state.last_sequence + 1}:{uuid.uuid4().hex}",
                event_type=event_type,
                aggregate_id=state.aggregate_id or "nexus-demo-paper",
                sequence=state.last_sequence + 1,
                occurred_at=at,
                correlation_id=correlation,
                causation_id=correlation,
                provenance=_paper_provenance(timeframe="session", at=at),
                previous_event_digest=state.last_event_digest,
                payload=payload,
            )
            updated = [*events, event]
            self.runtime._write_events(updated)
            new_state = replay(updated).state
            return {
                "contract_version": CONTROL_CONTRACT,
                "paper_only": True,
                "event": event,
                "account": serialize_portfolio(new_state),
                "live_trading_authority": False,
            }

    def set_session(self, request: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(request, Mapping) or set(request) != {"open"} or not isinstance(request["open"], bool):
            raise ProductControlError("session control schema mismatch")
        return self._append_control_event("session_boundary_recorded", {"boundary": "open" if request["open"] else "close"})

    def set_kill_switch(self, request: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(request, Mapping) or set(request) != {"enabled", "reason_code"}:
            raise ProductControlError("kill-switch control schema mismatch")
        enabled = request["enabled"]
        reason = request["reason_code"]
        if not isinstance(enabled, bool) or not isinstance(reason, str) or not reason.strip() or len(reason) > 100:
            raise ProductControlError("kill-switch control values are invalid")
        return self._append_control_event("kill_switch_transitioned", {"enabled": enabled, "reason_code": reason.strip()})

    def risk_snapshot(self) -> dict[str, Any]:
        with self.runtime._lock:
            events = self.runtime._ensure_account()
            state = replay(events).state
            symbols = [row[0] for row in state.positions] or ["BTCUSDT"]
            return {
                "contract_version": CONTROL_CONTRACT,
                "paper_only": True,
                "policy": _risk_policy(),
                "state": _risk_state(state, symbol=symbols[0], signals_today=_session_signal_count(events)),
                "account": serialize_portfolio(state),
                "live_trading_authority": False,
            }

    def recovery_snapshot(self) -> dict[str, Any]:
        try:
            with self.runtime._lock:
                events = self.runtime._read_events()
                if not events:
                    events = self.runtime._ensure_account()
                replayed = replay(events)
                state = replayed.state
                return {
                    "contract_version": CONTROL_CONTRACT,
                    "status": "verified",
                    "paper_only": True,
                    "event_count": len(events),
                    "applied_events": replayed.applied_events,
                    "last_sequence": state.last_sequence,
                    "head_event_digest": state.last_event_digest,
                    "atomic_journal": True,
                    "fail_closed_on_corruption": True,
                    "live_trading_authority": False,
                }
        except Exception as exc:
            return {
                "contract_version": CONTROL_CONTRACT,
                "status": "failed_closed",
                "paper_only": True,
                "reason": str(exc),
                "live_trading_authority": False,
            }

    def notifications(self, *, limit: int = 100) -> dict[str, Any]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise ProductControlError("notification limit out of range")
        events = self.runtime.paper_events(limit=min(limit * 4, 1000))["events"]
        interesting = {
            "risk_rejection_recorded": "risk",
            "kill_switch_transitioned": "critical",
            "session_boundary_recorded": "control",
            "position_opened": "execution",
            "position_closed": "execution",
            "position_reversed": "execution",
        }
        rows = []
        for event in reversed(events):
            level = interesting.get(event["event_type"])
            if level is None:
                continue
            rows.append({
                "id": event["event_id"], "level": level, "event_type": event["event_type"],
                "occurred_at": event["occurred_at"], "payload": event["payload"], "digest": event["event_digest"],
            })
            if len(rows) >= limit:
                break
        return {"contract_version": CONTROL_CONTRACT, "paper_only": True, "notifications": rows, "count": len(rows)}

    def export_json(self) -> bytes:
        payload = {
            "generated_at": _now(),
            "paper": self.runtime.paper_snapshot(),
            "events": self.runtime.paper_events(limit=1000),
            "risk": self.risk_snapshot(),
            "recovery": self.recovery_snapshot(),
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")

    def export_csv(self) -> bytes:
        events = self.runtime.paper_events(limit=1000)["events"]
        out = io.StringIO(newline="")
        writer = csv.writer(out)
        writer.writerow(["sequence", "occurred_at", "event_type", "symbol", "reason_code", "event_digest"])
        for event in events:
            payload = event.get("payload", {})
            writer.writerow([
                event.get("sequence"), event.get("occurred_at"), event.get("event_type"),
                payload.get("symbol", ""), payload.get("reason_code", ""), event.get("event_digest", ""),
            ])
        return out.getvalue().encode("utf-8-sig")
