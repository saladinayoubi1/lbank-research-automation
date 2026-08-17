from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

MAX_DEPTH = 10
MAX_ITEMS = 10_000
MAX_STRING_BYTES = 64_000

PAPER_MODES = {"paper", "demo", "simulation", "simulated"}
FORBIDDEN_EXACT_KEYS = {
    "api_key",
    "api_secret",
    "secret",
    "password",
    "access_token",
    "refresh_token",
    "authorization",
    "bearer_token",
    "private_key",
    "credentials",
    "exchange_credentials",
    "withdraw",
    "withdrawal",
    "withdrawal_address",
    "real_order",
    "live_order",
    "live_trading",
    "private_endpoint",
    "production_deploy",
    "production_deployment",
    "billing",
    "payment_method",
    "signing_key",
    "raw_chat_transcript",
    "chat_transcript",
    "conversation_transcript",
}
FORBIDDEN_KEY_FRAGMENTS = {
    "credential",
    "withdraw",
    "private_exchange",
    "private_api",
    "live_order",
    "real_order",
    "production_promotion",
    "billing_authority",
    "signing_authority",
}
FORBIDDEN_TOOL_PREFIXES = (
    "exchange.private",
    "exchange.live",
    "wallet.withdraw",
    "production.deploy",
    "billing.",
    "signing.",
    "shell.",
)
DEFAULT_ALLOWED_TOOLS = frozenset(
    {
        "market.read_public",
        "research.run_bounded",
        "strategy.propose",
        "risk.evaluate",
        "paper.execute_validated",
        "portfolio.read",
        "audit.read",
        "mission.propose",
        "memory.read_bounded",
    }
)

_SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", re.IGNORECASE),
    re.compile(r"authorization\s*:\s*bearer\s+\S+", re.IGNORECASE),
    re.compile(
        r"(?:api[_ -]?key|api[_ -]?secret|password|access[_ -]?token|refresh[_ -]?token)"
        r"\s*[:=]\s*[\"']?[A-Za-z0-9_./+=-]{8,}",
        re.IGNORECASE,
    ),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
)


class AirGapViolation(ValueError):
    pass


class SecretMaterialDetected(AirGapViolation):
    pass


class ToolDenied(AirGapViolation):
    pass


class IndependentSafetyGateFailure(AirGapViolation):
    pass


@dataclass(frozen=True)
class ValidationResult:
    paper_only: bool
    item_count: int
    max_depth_seen: int
    reason_code: str


def _normalize_key(key: Any) -> str:
    if not isinstance(key, str) or not key or len(key) > 256:
        raise AirGapViolation("contract keys must be non-empty bounded strings")
    normalized = re.sub(r"[^a-z0-9]+", "_", key.casefold()).strip("_")
    if not normalized:
        raise AirGapViolation("contract key is not canonical")
    return normalized


def _check_key(key: str) -> None:
    if key in FORBIDDEN_EXACT_KEYS:
        raise AirGapViolation(f"forbidden paper-contract field: {key}")
    if any(fragment in key for fragment in FORBIDDEN_KEY_FRAGMENTS):
        raise AirGapViolation(f"forbidden paper-contract capability: {key}")


def _check_text(value: str, field: str) -> None:
    if len(value.encode("utf-8")) > MAX_STRING_BYTES:
        raise AirGapViolation(f"{field} exceeds bounded string size")
    for pattern in _SECRET_PATTERNS:
        if pattern.search(value):
            raise SecretMaterialDetected(f"secret material detected in {field}")


def validate_paper_contract(value: Any) -> ValidationResult:
    """Recursively reject live/credential/withdrawal/production/billing/signing authority.

    This validator is intentionally format-agnostic so UI, AI, mission, strategy and
    execution adapters can pass their structured proposal before any paper authority is
    considered. It never grants execution by itself.
    """

    item_count = 0
    max_depth_seen = 0

    def walk(node: Any, *, depth: int, path: str) -> None:
        nonlocal item_count, max_depth_seen
        if depth > MAX_DEPTH:
            raise AirGapViolation("contract exceeds maximum nesting depth")
        max_depth_seen = max(max_depth_seen, depth)
        item_count += 1
        if item_count > MAX_ITEMS:
            raise AirGapViolation("contract exceeds maximum item count")

        if isinstance(node, Mapping):
            for raw_key, child in node.items():
                key = _normalize_key(raw_key)
                _check_key(key)
                child_path = f"{path}.{key}" if path else key
                if key in {"mode", "execution_mode", "trading_mode"}:
                    if not isinstance(child, str) or child.casefold() not in PAPER_MODES:
                        raise AirGapViolation("execution mode is not paper/demo/simulation")
                if key in {"paper_trading_only", "paper_only"} and child is not True:
                    raise AirGapViolation("paper-only assertion cannot be false")
                walk(child, depth=depth + 1, path=child_path)
            return

        if isinstance(node, (list, tuple)):
            for index, child in enumerate(node):
                walk(child, depth=depth + 1, path=f"{path}[{index}]")
            return

        if isinstance(node, str):
            _check_text(node, path or "value")
            lowered = node.casefold().strip()
            if path.endswith((".mode", ".execution_mode", ".trading_mode")) and lowered not in PAPER_MODES:
                raise AirGapViolation("execution mode is not paper/demo/simulation")
            return

        if isinstance(node, float):
            raise AirGapViolation("binary floating point is not accepted in paper contracts")
        if node is None or isinstance(node, (bool, int)):
            return
        raise AirGapViolation(f"unsupported paper-contract value at {path or 'root'}")

    walk(value, depth=0, path="")
    return ValidationResult(True, item_count, max_depth_seen, "paper_airgap_valid")


def scan_text_for_secrets(text: str) -> None:
    if not isinstance(text, str):
        raise SecretMaterialDetected("secret scan input must be text")
    _check_text(text, "text")


def redact_for_egress(value: str, secret_values: Iterable[str] = ()) -> str:
    if not isinstance(value, str):
        raise AirGapViolation("egress payload must be text")
    if len(value.encode("utf-8")) > MAX_STRING_BYTES:
        raise AirGapViolation("egress payload exceeds bounded string size")
    redacted = value
    for raw in secret_values:
        if not isinstance(raw, str) or not raw:
            raise AirGapViolation("secret values must be non-empty strings")
        redacted = redacted.replace(raw, "[REDACTED_SECRET]")
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED_SECRET]", redacted)
    scan_text_for_secrets(redacted)
    return redacted


class ToolAllowlist:
    def __init__(self, allowed: Iterable[str] = DEFAULT_ALLOWED_TOOLS) -> None:
        normalized = frozenset(allowed)
        if not normalized or any(not isinstance(item, str) or not item for item in normalized):
            raise AirGapViolation("tool allowlist is invalid")
        for tool in normalized:
            if any(tool.startswith(prefix) for prefix in FORBIDDEN_TOOL_PREFIXES):
                raise ToolDenied(f"forbidden tool cannot be allowlisted: {tool}")
        self._allowed = normalized

    @property
    def allowed(self) -> frozenset[str]:
        return self._allowed

    def require(self, tool: str) -> str:
        if not isinstance(tool, str) or not tool:
            raise ToolDenied("tool identity is required")
        if any(tool.startswith(prefix) for prefix in FORBIDDEN_TOOL_PREFIXES):
            raise ToolDenied("tool is inside a forbidden authority namespace")
        if tool not in self._allowed:
            raise ToolDenied("tool is not explicitly allowlisted")
        return tool


def independent_airgap_check(*, contract: Any, tool: str, trusted_gate_enabled: bool = True) -> str:
    """Independent final deny check used in addition to upstream policy/validator results.

    Callers cannot pass an upstream `allowed=True` to bypass this function. The contract
    and tool identity are independently re-evaluated here. Disabling the trusted gate is
    itself a hard failure, preventing policy+validator+self-tests from silently becoming
    the sole source of authority.
    """

    if trusted_gate_enabled is not True:
        raise IndependentSafetyGateFailure("trusted independent air-gap gate is disabled")
    validate_paper_contract(contract)
    ToolAllowlist().require(tool)
    return "independent_paper_airgap_pass"


def canonical_contract_bytes(value: Any) -> bytes:
    validate_paper_contract(value)
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise AirGapViolation("paper contract is not canonically serializable") from exc
