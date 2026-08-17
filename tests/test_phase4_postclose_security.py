from __future__ import annotations

import io
from pathlib import Path
import zipfile

import pytest

import agent_transport as at
import deepseek_provider as dp
import paper_event_store as pes
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


def test_deepseek_provider_rejects_non_object_response_after_authorized_transport(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr(dp, "authorize_deepseek_json", lambda body: (object(), object()))
    monkeypatch.setattr(dp, "_reserve", lambda *args, **kwargs: ("reserved", 0.01))
    monkeypatch.setattr(dp, "post_authorized_json", lambda **kwargs: b"[]")
    with pytest.raises(dp.AmbiguousCharge, match="root is malformed"):
        dp.chat([{"role": "user", "content": "bounded test"}])


def test_artifact_redirect_strips_repository_credentials_and_denies_http_downgrade():
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


def test_runtime_worker_keeps_dispatch_data_out_of_shell_source():
    workflow = Path(".github/workflows/nexus-runtime-worker.yml").read_text(encoding="utf-8")
    assert "--payload-b64 '${{ github.event.inputs.payload_b64 }}'" not in workflow
    assert '--payload-b64 "${{ github.event.inputs.payload_b64 }}"' not in workflow
    assert "NEXUS_TASK_PAYLOAD_B64: ${{ github.event.inputs.payload_b64 }}" in workflow
    assert "github.actor == github.repository_owner" in workflow
    assert "github.ref_name == github.event.repository.default_branch" in workflow
    assert workflow.count("persist-credentials: false") >= 4


def test_self_hosted_phase_workflows_pin_trusted_manual_refs_and_credentials():
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

    assert "github.event_name != 'pull_request'" in activation
    assert "github.actor == github.repository_owner" in activation
    assert "github.ref_name == github.event.repository.default_branch" in activation
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
