from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import http.client
import json
import shutil
import sqlite3
import subprocess
from threading import Thread

import pytest

from nexus_external_paper_arbiter import (
    ArbiterDenied, ExternalPaperArbiter, OBSERVATION_SCHEMA, OpenSSLSigner,
    ThreadingHTTPServer, assert_external_host, bootstrap_state, handler_for,
)
from nexus_paper_writer_fence import (
    FAILOVER_WRITER, PRIMARY_WRITER, verify_writer_permit,
)
# Reuse the existing explicitly test-only signing key, never a deployment key.
from test_nexus_paper_writer_fence import _sign, _trust, NOW, CHECKPOINT


def request(writer=FAILOVER_WRITER, nonce="1" * 64, ttl=60_000):
    return {"writer_id": writer, "journal_checkpoint_digest": CHECKPOINT,
            "request_nonce": nonce, "ttl_ms": ttl}


@pytest.fixture
def setup(tmp_path):
    tmp_path.chmod(0o700)
    state = tmp_path / "authority.sqlite3"
    bootstrap_state(state, _trust())
    clock = [NOW]
    observations = []

    def fence(previous, target, nonce, until):
        value = {"schema": OBSERVATION_SCHEMA, "writer_id": previous,
                 "target_writer_id": target, "controller_id": "TEST_ONLY_external_controller",
                 "method": "external_power_fence", "fenced": True,
                 "restart_inhibited": True, "observed_at_ms": clock[0],
                 "hold_until_ms": until, "request_nonce": nonce}
        observations.append(value)
        return value

    def make(**kwargs):
        return ExternalPaperArbiter(state, _trust(), lambda data: _sign(json.loads(data)),
                                    fence=kwargs.pop("fence", fence),
                                    clock_ms=lambda: clock[0], **kwargs)
    return state, clock, observations, make


def test_signed_permit_is_accepted_by_existing_writer_and_rechecks_fence(setup):
    state, clock, observations, make = setup
    arbiter = make()
    permit = arbiter.issue(request())
    receipt = verify_writer_permit(permit, _trust(), local_writer_id=FAILOVER_WRITER,
        local_journal_checkpoint_digest=CHECKPOINT, last_accepted_epoch=0, now_ms=clock[0])
    assert receipt["epoch"] == 1
    assert receipt["live_trading_authority"] is False
    assert receipt["protective_exit_authority"] == ["reduce", "close"]
    assert arbiter.current(FAILOVER_WRITER) == permit
    assert len(observations) == 2
    with pytest.raises(ArbiterDenied, match="no current permit"):
        arbiter.current(PRIMARY_WRITER)


def test_unconfigured_real_controller_cannot_issue_even_with_client_proof(setup):
    state, clock, _, _ = setup
    arbiter = ExternalPaperArbiter(state, _trust(), lambda data: _sign(json.loads(data)),
                                   clock_ms=lambda: clock[0])
    with pytest.raises(ArbiterDenied, match="not provisioned"):
        arbiter.issue(request())
    fake = {**request(), "previous_writer_fenced": True, "fence_method": "external_stonith"}
    with pytest.raises(ArbiterDenied, match="contract"):
        arbiter.issue(fake)
    assert sqlite3.connect(state).execute("SELECT epoch FROM authority").fetchone()[0] == 0


def test_two_service_instances_cannot_grant_simultaneous_writers(setup):
    _, _, _, make = setup
    first, second = make(), make()
    def attempt(arbiter, body):
        try:
            return arbiter.issue(body)
        except ArbiterDenied:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(attempt, first, request())
        b = pool.submit(attempt, second, request(PRIMARY_WRITER, "2" * 64))
        grants = [v for v in (a.result(), b.result()) if v is not None]
    assert len(grants) == 1
    assert grants[0]["epoch"] == 1


def test_expiry_and_service_restart_keep_monotonic_epoch_and_nonce(setup):
    _, clock, _, make = setup
    first = make().issue(request())
    with pytest.raises(ArbiterDenied, match="still active"):
        make().issue(request(PRIMARY_WRITER, "2" * 64))
    clock[0] = first["expires_at_ms"]
    with pytest.raises(ArbiterDenied, match="already used"):
        make().issue(request())
    with pytest.raises(ArbiterDenied, match="no current permit"):
        make().current(FAILOVER_WRITER)
    next_permit = make().issue(request(PRIMARY_WRITER, "2" * 64))
    assert next_permit["epoch"] == 2
    assert next_permit["previous_writer_id"] == FAILOVER_WRITER


@pytest.mark.parametrize("change", [
    {"fenced": False}, {"restart_inhibited": False}, {"method": "network_timeout"},
    {"writer_id": FAILOVER_WRITER}, {"target_writer_id": PRIMARY_WRITER},
    {"controller_id": PRIMARY_WRITER}, {"request_nonce": "0" * 64},
    {"observed_at_ms": NOW - 1}, {"observed_at_ms": NOW + 1},
    {"hold_until_ms": NOW + 60_000}, {"fenced": 1},
])
def test_false_stale_or_unbound_fencing_never_advances_epoch(setup, change):
    state, clock, observations, make = setup
    good = make().fence
    def bad(*args):
        return {**good(*args), **change}
    with pytest.raises(ArbiterDenied, match="observation"):
        make(fence=bad).issue(request())
    assert sqlite3.connect(state).execute("SELECT epoch FROM authority").fetchone()[0] == 0


def test_arbiter_or_controller_loss_and_clock_rollback_deny_current_authority(setup):
    state, clock, _, make = setup
    arbiter = make()
    arbiter.issue(request())
    clock[0] = NOW - 1
    with pytest.raises(ArbiterDenied, match="clock"):
        arbiter.current(FAILOVER_WRITER)
    clock[0] = NOW
    def lost(*args):
        raise ArbiterDenied("controller unavailable")
    with pytest.raises(ArbiterDenied, match="controller unavailable"):
        make(fence=lost).current(FAILOVER_WRITER)
    def timeout(*args):
        raise TimeoutError("controller request timed out")
    with pytest.raises(ArbiterDenied, match="controller is unavailable"):
        make(fence=timeout).current(FAILOVER_WRITER)
    state.unlink()
    with pytest.raises(ArbiterDenied, match="private file"):
        arbiter.current(FAILOVER_WRITER)
    assert not state.exists()  # No automatic recreation/reset during serve.


def test_corrupt_or_changed_key_state_is_not_a_new_epoch_zero(setup):
    state, _, _, make = setup
    make().issue(request())
    with sqlite3.connect(state) as conn:
        conn.execute("UPDATE authority SET epoch=0")
    with pytest.raises(ArbiterDenied, match="integrity"):
        make()
    with pytest.raises(ArbiterDenied, match="cannot be initialized"):
        bootstrap_state(state, _trust())


@pytest.mark.parametrize("change", [
    {"ttl_ms": True}, {"ttl_ms": 600_001}, {"ttl_ms": 0}, {"writer_id": "third-writer"},
    {"journal_checkpoint_digest": "wrong"}, {"request_nonce": "wrong"},
    {"live_trading_authority": True},
])
def test_request_authority_and_bounds_are_strict(setup, change):
    _, _, _, make = setup
    with pytest.raises(ArbiterDenied):
        make().issue({**request(), **change})


def test_bad_signer_cannot_commit_an_invalid_grant(setup):
    state, clock, _, make = setup
    arbiter = make()
    arbiter.signer = lambda data: "invalid"
    with pytest.raises(ValueError):
        arbiter.issue(request())
    assert make().issue(request())["epoch"] == 1


def test_writer_hosts_cannot_start_signing_service(monkeypatch):
    monkeypatch.setattr("nexus_external_paper_arbiter.socket.gethostname", lambda: PRIMARY_WRITER)
    with pytest.raises(ArbiterDenied, match="independent Linux"):
        assert_external_host()


def test_wsl_is_not_an_independent_deployment_host(monkeypatch):
    monkeypatch.setattr("nexus_external_paper_arbiter.socket.gethostname", lambda: "ubuntu-alias")
    monkeypatch.setattr("nexus_external_paper_arbiter.sys.platform", "linux")
    monkeypatch.setattr("nexus_external_paper_arbiter.platform.release", lambda: "6.6-microsoft-standard-WSL2")
    with pytest.raises(ArbiterDenied, match="independent Linux"):
        assert_external_host()


def test_separate_linux_hostname_can_pass_only_host_precheck(monkeypatch):
    monkeypatch.setattr("nexus_external_paper_arbiter.socket.gethostname", lambda: "external-test-server")
    monkeypatch.setattr("nexus_external_paper_arbiter.sys.platform", "linux")
    monkeypatch.setattr("nexus_external_paper_arbiter.platform.release", lambda: "6.6-linux")
    monkeypatch.delenv("COMPUTERNAME", raising=False)
    assert_external_host()


def test_http_auth_is_scoped_and_no_client_claim_enables_default_fencer(setup, monkeypatch):
    state, clock, _, _ = setup
    arbiter = ExternalPaperArbiter(state, _trust(), lambda data: _sign(json.loads(data)),
                                   clock_ms=lambda: clock[0])
    tokens = {PRIMARY_WRITER: "a" * 64, FAILOVER_WRITER: "b" * 64}
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(arbiter, tokens))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
    try:
        client.request("GET", "/healthz")
        response = client.getresponse()
        assert response.status == 200
        assert json.loads(response.read())["takeover_enabled"] is False
        client.request("GET", "/v1/trust-root")
        response = client.getresponse()
        assert response.status == 401
        response.read()
        client.request("POST", "/v1/permit", json.dumps(request()),
                       {"Authorization": "Bearer " + tokens[PRIMARY_WRITER]})
        response = client.getresponse()
        assert response.status == 409
        response.read()
        client.request("POST", "/v1/permit", json.dumps(request()),
                       {"Authorization": "Bearer " + tokens[FAILOVER_WRITER]})
        response = client.getresponse()
        assert response.status == 409
        assert json.loads(response.read())["takeover_enabled"] is False
        # Fault-inject unavailable storage while HTTP workers are running.
        # Windows cannot unlink a SQLite file still held by another thread;
        # the separate state-loss test covers actual missing-file rejection.
        def unavailable_connection():
            raise ArbiterDenied("simulated durable storage outage")
        monkeypatch.setattr(arbiter, "connection", unavailable_connection)
        client.request("GET", "/healthz")
        response = client.getresponse()
        assert response.status == 503
        assert json.loads(response.read())["takeover_enabled"] is False
    finally:
        client.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


@pytest.mark.skipif(shutil.which("openssl") is None, reason="OpenSSL integration requires executable")
def test_openssl_test_key_signatures_match_existing_verifier(tmp_path):
    key = tmp_path / "TEST_ONLY_NOT_DEPLOYMENT.pem"
    subprocess.run(["openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt",
                    "rsa_keygen_bits:2048", "-out", str(key)],
                   capture_output=True, check=True, timeout=30)
    key.chmod(0o600)
    signer = OpenSSLSigner(key)
    trust = signer.trust_root("TEST_ONLY_arbiter")
    tmp_path.chmod(0o700)
    state = tmp_path / "test.sqlite3"
    bootstrap_state(state, trust)
    def test_fencer(previous, target, nonce, until):
        return {"schema": OBSERVATION_SCHEMA, "writer_id": previous, "target_writer_id": target,
                "controller_id": "TEST_ONLY_controller", "method": "external_power_fence",
                "fenced": True, "restart_inhibited": True, "observed_at_ms": NOW,
                "hold_until_ms": until, "request_nonce": nonce}
    permit = ExternalPaperArbiter(state, trust, signer, fence=test_fencer,
                                  clock_ms=lambda: NOW).issue(request())
    assert verify_writer_permit(permit, trust, local_writer_id=FAILOVER_WRITER,
        local_journal_checkpoint_digest=CHECKPOINT, last_accepted_epoch=0, now_ms=NOW)["epoch"] == 1
