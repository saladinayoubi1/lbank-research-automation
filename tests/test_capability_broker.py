from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from capability_broker import (
    AuthorizationDenied,
    CapabilityBroker,
    CapabilityGrant,
    InvalidPolicy,
    Operation,
)


def grant(root: Path, resource: Path | str, operation: Operation, **overrides) -> CapabilityGrant:
    values = {
        "subject": "research-agent",
        "operation": operation,
        "root": root,
        "resource": Path(resource),
        "purpose": "repository test",
        "expires_at": datetime.now(timezone.utc) + timedelta(minutes=5),
        "max_bytes": 1024,
        "max_uses": 1,
        "correlation_id": "test-correlation",
    }
    values.update(overrides)
    return CapabilityGrant(**values)


def test_authorized_read_and_audit_chain(tmp_path: Path) -> None:
    target = tmp_path / "allowed.txt"
    target.write_bytes(b"approved")
    broker = CapabilityBroker()
    token = broker.issue(grant(tmp_path, target, Operation.READ_FILE))

    assert broker.read_file(token, "research-agent") == b"approved"
    assert broker.verify_audit_chain()
    assert all("approved" not in json.dumps(record) for record in broker.audit_records())


def test_default_deny_unknown_token(tmp_path: Path) -> None:
    broker = CapabilityBroker()
    with pytest.raises(AuthorizationDenied, match="unknown"):
        broker.read_file("not-a-token", "research-agent")


def test_operation_separation_read_does_not_imply_write(tmp_path: Path) -> None:
    target = tmp_path / "allowed.txt"
    target.write_text("original", encoding="utf-8")
    broker = CapabilityBroker()
    token = broker.issue(grant(tmp_path, target, Operation.READ_FILE))

    with pytest.raises(AuthorizationDenied, match="operation mismatch"):
        broker.write_file(token, "research-agent", b"changed")
    assert target.read_text(encoding="utf-8") == "original"


def test_parent_traversal_and_sibling_escape_denied(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("secret", encoding="utf-8")
    broker = CapabilityBroker()

    with pytest.raises(AuthorizationDenied, match="escapes"):
        broker.issue(grant(root, Path("..") / "secret.txt", Operation.READ_FILE))

    with pytest.raises(AuthorizationDenied, match="escapes"):
        broker.issue(grant(root, outside, Operation.READ_FILE))


def test_symlink_escape_denied(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("secret", encoding="utf-8")
    link = root / "link.txt"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable on this runner")

    broker = CapabilityBroker()
    with pytest.raises(AuthorizationDenied):
        broker.issue(grant(root, link, Operation.READ_FILE))


def test_expiry_subject_use_limit_and_revoke_all(tmp_path: Path) -> None:
    target = tmp_path / "allowed.txt"
    target.write_bytes(b"approved")
    broker = CapabilityBroker()

    with pytest.raises(InvalidPolicy, match="future"):
        broker.issue(
            grant(
                tmp_path,
                target,
                Operation.READ_FILE,
                expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
            )
        )

    token = broker.issue(grant(tmp_path, target, Operation.READ_FILE, max_uses=2))
    with pytest.raises(AuthorizationDenied, match="subject mismatch"):
        broker.read_file(token, "other-agent")

    assert broker.read_file(token, "research-agent") == b"approved"
    assert broker.read_file(token, "research-agent") == b"approved"
    with pytest.raises(AuthorizationDenied, match="exhausted"):
        broker.read_file(token, "research-agent")

    second = broker.issue(grant(tmp_path, target, Operation.READ_FILE))
    broker.revoke_all()
    with pytest.raises(AuthorizationDenied, match="revoked"):
        broker.read_file(second, "research-agent")
    assert broker.verify_audit_chain()


def test_byte_limits_fail_closed(tmp_path: Path) -> None:
    target = tmp_path / "large.txt"
    target.write_bytes(b"12345")
    broker = CapabilityBroker()
    token = broker.issue(grant(tmp_path, target, Operation.READ_FILE, max_bytes=4))
    with pytest.raises(AuthorizationDenied, match="byte limit"):
        broker.read_file(token, "research-agent")


def test_create_is_exclusive_and_write_is_bounded(tmp_path: Path) -> None:
    broker = CapabilityBroker()
    create_token = broker.issue(grant(tmp_path, "new.txt", Operation.CREATE_FILE, max_bytes=3))
    broker.create_file(create_token, "research-agent", b"new")
    assert (tmp_path / "new.txt").read_bytes() == b"new"

    duplicate = broker.issue(grant(tmp_path, "new.txt", Operation.CREATE_FILE, max_bytes=3))
    with pytest.raises(AuthorizationDenied, match="already exists"):
        broker.create_file(duplicate, "research-agent", b"bad")

    write_token = broker.issue(grant(tmp_path, "new.txt", Operation.WRITE_FILE, max_bytes=2))
    with pytest.raises(AuthorizationDenied, match="byte limit"):
        broker.write_file(write_token, "research-agent", b"toolarge")
    assert (tmp_path / "new.txt").read_bytes() == b"new"


def test_directory_listing_is_exact_and_bounded(tmp_path: Path) -> None:
    (tmp_path / "b.txt").write_text("b", encoding="utf-8")
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    broker = CapabilityBroker()
    token = broker.issue(grant(tmp_path, ".", Operation.LIST_DIRECTORY, max_bytes=20))
    assert broker.list_directory(token, "research-agent") == ("a.txt", "b.txt")


def test_schema_is_deny_by_default_and_has_no_wildcard_operation() -> None:
    schema_path = Path("policy/capability-policy.schema.json")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert schema["properties"]["default"]["const"] == "deny"
    operations = schema["properties"]["grants"]["items"]["properties"]["operation"]["enum"]
    assert "shell" not in operations
    assert "*" not in operations
    assert set(operations) == {operation.value for operation in Operation}
