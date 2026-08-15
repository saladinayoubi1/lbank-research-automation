"""Deterministic fail-closed pre-egress policy for DeepSeek-bound payloads."""
from __future__ import annotations

import re
from typing import Any


class EgressDenied(ValueError):
    pass


_HEALTH_SMOKE = "Reply with exactly: NEXUS_DEEPSEEK_OK"
_RESEARCH_PREFIX = "You are an independent quantitative-research reviewer for NEXUS."
_ALLOWED_MESSAGE_KEYS = {"role", "content"}

_DENY_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", re.IGNORECASE),
    re.compile(r"authorization\s*:\s*bearer\s+\S+", re.IGNORECASE),
    re.compile(
        r"(?:api[_ -]?key|secret|password|access[_ -]?token|refresh[_ -]?token)\s*[:=]\s*[\"']?[A-Za-z0-9_./+=-]{8,}",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:private\s+)?account\s+(?:number|no\.?|id)\s*[:=]?\s*[A-Z0-9 -]{6,}\b", re.IGNORECASE),
    re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b"),
    re.compile(r"\b(?:raw[_ -]?chat|chat\s+transcript|conversation\s+transcript)\b", re.IGNORECASE),
)

_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_WINDOWS_USER_PATH = re.compile(r"\b[A-Z]:\\Users\\[^\\\s]+", re.IGNORECASE)
_POSIX_USER_PATH = re.compile(r"(?<![A-Za-z0-9_])/(?:home|Users)/[^/\s]+")


def _classify(content: str) -> str:
    if content == _HEALTH_SMOKE:
        return "health_smoke"
    if content.startswith(_RESEARCH_PREFIX):
        return "research_advisory"
    raise EgressDenied("DeepSeek egress payload is unclassified")


def _deny_sensitive(content: str) -> None:
    for pattern in _DENY_PATTERNS:
        if pattern.search(content):
            raise EgressDenied("DeepSeek egress payload contains sensitive or prohibited content")


def _redact(content: str) -> str:
    content = _EMAIL.sub("[REDACTED_EMAIL]", content)
    content = _WINDOWS_USER_PATH.sub("[REDACTED_USER_PATH]", content)
    content = _POSIX_USER_PATH.sub("[REDACTED_USER_PATH]", content)
    return content


def prepare_egress_messages(messages: Any) -> tuple[str, list[dict[str, str]]]:
    """Classify, validate, redact and allowlist one outbound advisory message.

    Only the frozen health-smoke probe and repository-owned quantitative-research
    advisory prompt are authorized. Unknown shapes/content fail closed.
    """
    if not isinstance(messages, list) or len(messages) != 1:
        raise EgressDenied("DeepSeek egress payload must contain exactly one allowlisted message")
    message = messages[0]
    if not isinstance(message, dict) or set(message) != _ALLOWED_MESSAGE_KEYS:
        raise EgressDenied("DeepSeek egress message fields are not allowlisted")
    if message.get("role") != "user":
        raise EgressDenied("DeepSeek egress role is not allowlisted")
    content = message.get("content")
    if not isinstance(content, str) or not content or len(content.encode("utf-8")) > 24_000:
        raise EgressDenied("DeepSeek egress content is empty or outside the bounded size")

    classification = _classify(content)
    _deny_sensitive(content)
    redacted = _redact(content)
    _deny_sensitive(redacted)
    return classification, [{"role": "user", "content": redacted}]
