"""Deny-by-default capability broker for repository-owned file operations.

The broker intentionally exposes no shell or ambient network access. Capabilities are
short-lived, operation-specific, byte-bounded, use-bounded, and revocable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
import hashlib
import json
import os
from pathlib import Path
import secrets
import threading
from typing import Any


class BrokerError(RuntimeError):
    """Base broker failure."""


class AuthorizationDenied(BrokerError):
    """The requested operation is not authorized."""


class InvalidPolicy(BrokerError):
    """Policy input is invalid."""


class Operation(StrEnum):
    READ_FILE = "read_file"
    WRITE_FILE = "write_file"
    CREATE_FILE = "create_file"
    LIST_DIRECTORY = "list_directory"


@dataclass(frozen=True)
class CapabilityGrant:
    subject: str
    operation: Operation
    root: Path
    resource: Path
    purpose: str
    expires_at: datetime
    max_bytes: int
    max_uses: int = 1
    correlation_id: str = field(default_factory=lambda: secrets.token_urlsafe(16))


@dataclass
class _CapabilityState:
    grant: CapabilityGrant
    remaining_uses: int
    revoked: bool = False


class CapabilityBroker:
    """Complete-mediation broker for narrow file operations.

    The broker stores no protected file content in its audit log. Each audit record is
    chained with SHA-256 so accidental or casual alteration is detectable.
    """

    def __init__(self) -> None:
        self._capabilities: dict[str, _CapabilityState] = {}
        self._audit: list[dict[str, Any]] = []
        self._audit_head = "0" * 64
        self._lock = threading.RLock()

    def issue(self, grant: CapabilityGrant) -> str:
        self._validate_grant(grant)
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._capabilities[token] = _CapabilityState(grant, grant.max_uses)
            self._record("issued", grant, "allow")
        return token

    def revoke(self, token: str) -> None:
        with self._lock:
            state = self._capabilities.get(token)
            if state is None:
                raise AuthorizationDenied("unknown capability")
            state.revoked = True
            self._record("revoked", state.grant, "allow")

    def revoke_all(self) -> None:
        with self._lock:
            for state in self._capabilities.values():
                state.revoked = True
            self._record_system("revoke_all", "allow")

    def read_file(self, token: str, subject: str) -> bytes:
        state = self._authorize(token, subject, Operation.READ_FILE)
        path = self._resolve_existing_file(state.grant)
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(path, flags)
        try:
            opened = os.fstat(fd)
            current = os.stat(path, follow_symlinks=False)
            if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
                raise AuthorizationDenied("file identity changed during access")
            data = os.read(fd, state.grant.max_bytes + 1)
            if len(data) > state.grant.max_bytes:
                raise AuthorizationDenied("file exceeds capability byte limit")
        finally:
            os.close(fd)
        self._consume(state, "read_file")
        return data

    def write_file(self, token: str, subject: str, data: bytes) -> None:
        state = self._authorize(token, subject, Operation.WRITE_FILE)
        if len(data) > state.grant.max_bytes:
            raise AuthorizationDenied("write exceeds capability byte limit")
        path = self._resolve_existing_file(state.grant)
        flags = os.O_WRONLY | os.O_TRUNC | getattr(os, "O_BINARY", 0)
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(path, flags)
        try:
            os.write(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)
        self._consume(state, "write_file")

    def create_file(self, token: str, subject: str, data: bytes) -> None:
        state = self._authorize(token, subject, Operation.CREATE_FILE)
        if len(data) > state.grant.max_bytes:
            raise AuthorizationDenied("create exceeds capability byte limit")
        path = self._resolve_new_file(state.grant)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(path, flags, 0o600)
        try:
            os.write(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)
        self._consume(state, "create_file")

    def list_directory(self, token: str, subject: str) -> tuple[str, ...]:
        state = self._authorize(token, subject, Operation.LIST_DIRECTORY)
        path = self._resolve_existing_directory(state.grant)
        entries = tuple(sorted(entry.name for entry in os.scandir(path)))
        encoded_size = sum(len(name.encode("utf-8")) for name in entries)
        if encoded_size > state.grant.max_bytes:
            raise AuthorizationDenied("directory listing exceeds capability byte limit")
        self._consume(state, "list_directory")
        return entries

    def audit_records(self) -> tuple[dict[str, Any], ...]:
        with self._lock:
            return tuple(dict(record) for record in self._audit)

    def verify_audit_chain(self) -> bool:
        previous = "0" * 64
        for record in self.audit_records():
            expected = record["hash"]
            body = {key: value for key, value in record.items() if key != "hash"}
            if body["previous_hash"] != previous:
                return False
            digest = hashlib.sha256(
                json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            if digest != expected:
                return False
            previous = expected
        return True

    def _authorize(self, token: str, subject: str, operation: Operation) -> _CapabilityState:
        now = datetime.now(timezone.utc)
        with self._lock:
            state = self._capabilities.get(token)
            if state is None:
                raise AuthorizationDenied("unknown capability")
            grant = state.grant
            reason = None
            if state.revoked:
                reason = "revoked capability"
            elif grant.subject != subject:
                reason = "subject mismatch"
            elif grant.operation is not operation:
                reason = "operation mismatch"
            elif grant.expires_at <= now:
                reason = "expired capability"
            elif state.remaining_uses <= 0:
                reason = "capability use limit exhausted"
            if reason:
                self._record(operation.value, grant, "deny", reason)
                raise AuthorizationDenied(reason)
            return state

    def _consume(self, state: _CapabilityState, action: str) -> None:
        with self._lock:
            state.remaining_uses -= 1
            self._record(action, state.grant, "allow")

    @staticmethod
    def _validate_grant(grant: CapabilityGrant) -> None:
        if not grant.subject.strip() or not grant.purpose.strip():
            raise InvalidPolicy("subject and purpose are required")
        if grant.expires_at.tzinfo is None:
            raise InvalidPolicy("expiry must be timezone-aware")
        if grant.expires_at <= datetime.now(timezone.utc):
            raise InvalidPolicy("expiry must be in the future")
        if grant.max_bytes < 0 or grant.max_uses < 1:
            raise InvalidPolicy("invalid byte or use limit")
        root = grant.root.resolve(strict=True)
        if not root.is_dir():
            raise InvalidPolicy("root must be an existing directory")
        CapabilityBroker._assert_beneath(root, grant.resource, allow_missing=True)

    @staticmethod
    def _assert_beneath(root: Path, resource: Path, *, allow_missing: bool) -> Path:
        canonical_root = root.resolve(strict=True)
        candidate = resource if resource.is_absolute() else canonical_root / resource
        try:
            canonical = candidate.resolve(strict=not allow_missing)
        except FileNotFoundError as exc:
            raise AuthorizationDenied("resource does not exist") from exc
        try:
            canonical.relative_to(canonical_root)
        except ValueError as exc:
            raise AuthorizationDenied("resource escapes approved root") from exc
        return canonical

    def _resolve_existing_file(self, grant: CapabilityGrant) -> Path:
        path = self._assert_beneath(grant.root, grant.resource, allow_missing=False)
        if path.is_symlink() or not path.is_file():
            raise AuthorizationDenied("resource is not a regular non-symlink file")
        return path

    def _resolve_existing_directory(self, grant: CapabilityGrant) -> Path:
        path = self._assert_beneath(grant.root, grant.resource, allow_missing=False)
        if path.is_symlink() or not path.is_dir():
            raise AuthorizationDenied("resource is not a regular non-symlink directory")
        return path

    def _resolve_new_file(self, grant: CapabilityGrant) -> Path:
        root = grant.root.resolve(strict=True)
        candidate = grant.resource if grant.resource.is_absolute() else root / grant.resource
        parent = candidate.parent.resolve(strict=True)
        try:
            parent.relative_to(root)
        except ValueError as exc:
            raise AuthorizationDenied("destination escapes approved root") from exc
        if candidate.exists() or candidate.is_symlink():
            raise AuthorizationDenied("destination already exists")
        return candidate

    def _record(self, action: str, grant: CapabilityGrant, decision: str, reason: str = "") -> None:
        self._append_audit({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "decision": decision,
            "reason": reason,
            "subject": grant.subject,
            "operation": grant.operation.value,
            "resource": str(grant.resource),
            "purpose": grant.purpose,
            "correlation_id": grant.correlation_id,
        })

    def _record_system(self, action: str, decision: str) -> None:
        self._append_audit({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "decision": decision,
            "reason": "",
            "subject": "broker",
            "operation": "administrative",
            "resource": "",
            "purpose": "recovery",
            "correlation_id": "system",
        })

    def _append_audit(self, body: dict[str, Any]) -> None:
        body["previous_hash"] = self._audit_head
        digest = hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        body["hash"] = digest
        self._audit.append(body)
        self._audit_head = digest
