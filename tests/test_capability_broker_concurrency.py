from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
import threading

from capability_broker import AuthorizationDenied, CapabilityBroker, CapabilityGrant, Operation


def test_one_shot_capability_cannot_be_reused_concurrently(tmp_path: Path) -> None:
    target = tmp_path / "allowed.txt"
    target.write_bytes(b"approved")
    broker = CapabilityBroker()
    token = broker.issue(
        CapabilityGrant(
            subject="research-agent",
            operation=Operation.READ_FILE,
            root=tmp_path,
            resource=target,
            purpose="concurrency regression",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
            max_bytes=1024,
            max_uses=1,
            correlation_id="concurrent-use-regression",
        )
    )

    start = threading.Barrier(3)

    def read_once() -> str:
        start.wait(timeout=5)
        try:
            broker.read_file(token, "research-agent")
            return "success"
        except AuthorizationDenied as exc:
            return f"denied:{exc}"

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(read_once) for _ in range(2)]
        start.wait(timeout=5)
        outcomes = [future.result(timeout=5) for future in futures]

    assert outcomes.count("success") == 1
    assert len([item for item in outcomes if item.startswith("denied:capability use limit exhausted")]) == 1
    assert broker.verify_audit_chain()
