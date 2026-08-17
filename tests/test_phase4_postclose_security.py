from __future__ import annotations

from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import threading
from types import SimpleNamespace
import zipfile

import pytest

import agent_transport as at
import deepseek_network_transport as dnt
import deepseek_provider as dp
import paper_event_store as pes
from capability_broker import AuthorizationDenied, CapabilityBroker, CapabilityGrant, Operation
from network_egress import HttpMethod
from scripts import agent_task_executor as executor


class _BytesResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeOpener:
    def __init__(self, payload: bytes):
        self.payload = payload

    def open(self, req, timeout=30):  # noqa: ANN001
        return _BytesResponse(self.payload)


def _zip_result(payload: bytes) -> bytes:
    target = io.BytesIO()
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("result.json", payload)
    return target.getvalue()


def _provenance(timeframe: str = "minute15") -> dict[str, object]:
    return {
        "kind": "automatic",
        "source_id": "security-regression",
        "source_timestamp": "2026-08-17T00:00:00Z",
        "received_timestamp": "2026-08-17T00:00:01Z",
        "timeframe": timeframe,
        "confidence": "1",
        "strategy_version": "strategy-v1",
        "policy_version": "risk-v1",
    }


def _event(event_type: str, payload: dict[str, object], *, provenance: dict[str, object] | None = None):
    return pes.build_event(
        event_id="security-event-1",
        event_type=event_type,
        aggregate_id="paper-account-security",
        sequence=1,
        occurred_at="2026-08-17T00:00:02Z",
        correlation_id="security-correlation",
        causation_id="security-cause",
        provenance=provenance or _provenance(),
        previous_event_digest=pes.GENESIS_DIGEST,
        payload=payload,
    )


def test_deepseek_transport_rejects_oversized_response_before_json_parse():
    class _TransportResponse:
        status = 200

        def getheader(self, name):  # noqa: ANN001
            return None

        def read(self, size=-1):
            assert size == dnt.MAX_RESPONSE_BYTES + 1
            return b"x" * size

    class _Connection:
        def request(self, *args, **kwargs):  # noqa: ANN002, ANN003
            return None

        def getresponse(self):
            return _TransportResponse()

        def close(self):
            return None

    class _Authorizer:
        def reject_redirect(self, status, location):  # noqa: ANN001
            assert status == 200
            assert location is None

    authorized = SimpleNamespace(
        request_bytes=2,
        method=HttpMethod.POST,
        host=dnt.DEEPSEEK_HOST,
        port=443,
        path_and_query="/chat/completions",
        max_response_bytes=dnt.MAX_RESPONSE_BYTES,
    )
    with pytest.raises(Exception, match="response byte limit exceeded"):
        dnt.post_authorized_json(
            body=b"{}",
            headers={"Content-Type": "application/json"},
            authorized=authorized,
            authorizer=_Authorizer(),
            timeout=1.0,
            connection_factory=lambda *args, **kwargs: _Connection(),
        )


def test_deepseek_provider_rejects_non_object_response_and_retains_ambiguity(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr(dp, "_reserve", lambda *args, **kwargs: ("reserved", 0.01))
    monkeypatch.setattr(dp, "authorize_deepseek_json", lambda *args, **kwargs: (object(), object()))
    monkeypatch.setattr(dp, "post_authorized_json", lambda *args, **kwargs: b"[]")
    with pytest.raises(dp.AmbiguousCharge, match="root is malformed"):
        dp.chat([{"role": "user", "content": "Reply with exactly: NEXUS_DEEPSEEK_OK"}])


def test_artifact_redirect_strips_authorization_and_rejects_http_downgrade():
    handler = at._StripAuthorizationRedirectHandler()
    req = at.urllib.request.Request(
        "https://api.github.com/repos/o/r/actions/artifacts/1/zip",
        headers={"Authorization": "Bearer secret", "Proxy-Authorization": "Bearer proxy-secret"},
    )
    redirected = handler.redirect_request(
        req,
        None,
        302,
        "Found",
        {},
        "https://example.invalid/signed-artifact",
    )
    assert redirected is not None
    assert redirected.get_header("Authorization") is None
    assert redirected.get_header("Proxy-Authorization") is None
    with pytest.raises(RuntimeError, match="remain HTTPS"):
        handler.redirect_request(req, None, 302, "Found", {}, "http://example.invalid/artifact")


def test_agent_artifact_rejects_oversized_result_member(monkeypatch):
    oversized = b"x" * (at.MAX_RESULT_JSON_BYTES + 1)
    archive = _zip_result(oversized)
    assert len(archive) < at.MAX_ARTIFACT_ARCHIVE_BYTES
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setattr(at.urllib.request, "build_opener", lambda *args, **kwargs: _FakeOpener(archive))
    with pytest.raises(RuntimeError, match="uncompressed size|result.json exceeds"):
        at._artifact_json(1)


def test_find_result_rejects_oversized_artifact_metadata(monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setattr(
        at,
        "_api",
        lambda *args, **kwargs: {
            "artifacts": [
                {
                    "id": 1,
                    "name": "nexus-agent-result-lease-1",
                    "expired": False,
                    "created_at": "2026-08-17T00:00:00Z",
                    "size_in_bytes": at.MAX_ARTIFACT_ARCHIVE_BYTES + 1,
                }
            ]
        },
    )
    with pytest.raises(RuntimeError, match="metadata size"):
        at.find_result("lease-1")


def test_dispatch_payload_decoder_rejects_non_base64_shell_material():
    with pytest.raises(ValueError, match="encoding is invalid"):
        executor.decode_payload("abc'; echo injected; #")


def test_runtime_workflow_never_interpolates_dispatch_payload_into_shell():
    workflow = Path(".github/workflows/nexus-runtime-worker.yml").read_text(encoding="utf-8")
    assert "--payload-b64 '${{ github.event.inputs.payload_b64 }}'" not in workflow
    assert '--payload-b64 "${{ github.event.inputs.payload_b64 }}"' not in workflow
    assert "NEXUS_TASK_PAYLOAD_B64: ${{ github.event.inputs.payload_b64 }}" in workflow
    assert "github.actor == github.repository_owner" in workflow
    assert "github.ref_name == github.event.repository.default_branch" in workflow
    assert workflow.count("persist-credentials: false") >= 4


def test_all_phase_self_hosted_workflows_pin_trusted_dispatch_boundaries():
    autonomy = Path(".github/workflows/nexus_local_autonomy.yml").read_text(encoding="utf-8")
    continuous = Path(".github/workflows/nexus-continuous-phase3.yml").read_text(encoding="utf-8")
    activation = Path(".github/workflows/nexus_phase3_resource_activation.yml").read_text(encoding="utf-8")
    local_runner = Path(".github/workflows/nexus-local-runner.yml").read_text(encoding="utf-8")
    runtime = Path(".github/workflows/nexus-runtime-worker.yml").read_text(encoding="utf-8")

    for workflow in (autonomy, continuous):
        assert "github.actor == github.repository_owner" in workflow
        assert "github.ref_name == github.event.repository.default_branch" in workflow
        assert "persist-credentials: false" in workflow
        assert "Verify exact trigger SHA" in workflow

    assert "github.event.pull_request.head.repo.full_name == github.repository" in activation
    assert "github.actor == github.repository_owner" in activation
    assert "persist-credentials: false" in activation
    assert "Verify exact trusted SHA" in activation
    assert "persist-credentials: false" in local_runner
    assert "Verify exact trigger SHA" in local_runner
    assert "github.event.pull_request.head.repo.full_name == github.repository" in runtime
    assert "github.actor == github.repository_owner" in runtime


def test_bounded_reader_refuses_one_byte_over_limit():
    with pytest.raises(RuntimeError, match="exceeds bounded size"):
        at._bounded_read(io.BytesIO(b"12345"), 4, "test stream")
    assert at._bounded_read(io.BytesIO(b"1234"), 4, "test stream") == b"1234"


def test_one_use_capability_is_reserved_before_concurrent_io(tmp_path: Path, monkeypatch):
    target = tmp_path / "allowed.txt"
    target.write_bytes(b"approved")
    broker = CapabilityBroker()
    token = broker.issue(CapabilityGrant(
        subject="research-agent",
        operation=Operation.READ_FILE,
        root=tmp_path,
        resource=target,
        purpose="concurrency security regression",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        max_bytes=1024,
        max_uses=1,
        correlation_id="capability-race-regression",
    ))

    original_resolve = broker._resolve_existing_file
    first_entered_io = threading.Event()
    release_first = threading.Event()
    calls_lock = threading.Lock()
    calls = 0

    def blocking_resolve(grant):  # noqa: ANN001
        nonlocal calls
        with calls_lock:
            calls += 1
            call_number = calls
        if call_number == 1:
            first_entered_io.set()
            assert release_first.wait(3), "first authorized operation was not released"
        return original_resolve(grant)

    monkeypatch.setattr(broker, "_resolve_existing_file", blocking_resolve)
    results: list[tuple[str, object]] = []

    def worker() -> None:
        try:
            results.append(("ok", broker.read_file(token, "research-agent")))
        except AuthorizationDenied as exc:
            results.append(("denied", str(exc)))

    first = threading.Thread(target=worker)
    second = threading.Thread(target=worker)
    first.start()
    assert first_entered_io.wait(2), "first operation never crossed authorization boundary"
    second.start()
    second.join(2)
    assert not second.is_alive(), "second caller should fail before reaching blocked I/O"
    release_first.set()
    first.join(2)
    assert not first.is_alive()

    assert sorted(kind for kind, _ in results) == ["denied", "ok"]
    assert any("exhausted" in str(value) for kind, value in results if kind == "denied")
    assert calls == 1
    assert broker.verify_audit_chain()


def test_paper_event_rejects_unbounded_sensitive_or_cross_timeframe_values():
    with pytest.raises(pes.PaperEventError, match="reason_code"):
        _event("risk_rejection_recorded", {"reason_code": "x" * (pes.MAX_REASON_CODE_CHARS + 1)})
    with pytest.raises(pes.PaperEventError, match="forbidden authority or secret material"):
        _event("risk_rejection_recorded", {"reason_code": "api_key=super-secret-value"})
    with pytest.raises(pes.PaperEventError, match="timeframe does not match provenance"):
        _event(
            "signal_recorded",
            {"symbol": "BTCUSDT", "timeframe": "hour1", "side": "buy", "quantity": "1", "reference_price": "60000"},
            provenance=_provenance("minute15"),
        )
    with pytest.raises(pes.PaperEventError, match="unsupported paper order type"):
        _event(
            "order_intent_recorded",
            {"symbol": "BTCUSDT", "side": "long", "quantity": "1", "order_type": "live_market"},
        )
    with pytest.raises(pes.PaperEventError, match="bounded decimal size"):
        _event("demo_account_opened", {"currency": "USDT", "opening_cash": "9" * (pes.MAX_DECIMAL_CHARS + 1)})
