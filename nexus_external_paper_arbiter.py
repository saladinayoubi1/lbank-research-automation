"""External Paper permit issuer. Never run this signing service on a writer.

The production HTTP entry point deliberately has no fencing adapter: it can be
deployed and checked, but cannot issue permits until a real external controller
is integrated and physically qualified. Client-supplied fencing claims are
never accepted. No owner journal, trading loop, or GitHub runtime state lives
here. The SQLite file is the independent arbiter's durable ownership record.
"""
from __future__ import annotations

import argparse
import base64
from contextlib import contextmanager
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import platform
import re
import secrets
import socket
import sqlite3
import ssl
import stat
import subprocess
import sys
import time
from typing import Callable, Mapping

from nexus_paper_writer_fence import (
    ALLOWED_FENCE_METHODS, FAILOVER_WRITER, MAX_TTL_MS, PERMIT_SCHEMA,
    PRIMARY_WRITER, TRUST_SCHEMA, WRITERS, digest, verify_writer_permit,
    _validate_trust_root,
)

STATE_SCHEMA = "nexus.external-paper-arbiter-state.v1"
OBSERVATION_SCHEMA = "nexus.external-fence-observation.v1"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
MAX_BODY = 4096


class ArbiterDenied(ValueError):
    """No permit is issued when an input or dependency is untrusted."""


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def safe_path(path: Path) -> None:
    if not path.is_absolute() or any(p.is_symlink() for p in (path, *path.parents)):
        raise ArbiterDenied("arbiter storage must be absolute and not linked")


def private_file(path: Path) -> None:
    safe_path(path)
    if not path.is_file() or (os.name == "posix" and stat.S_IMODE(path.stat().st_mode) & 0o077):
        raise ArbiterDenied("arbiter private file is missing or permissions are broad")


def bootstrap_state(path: Path, trust_root: Mapping) -> None:
    """Explicit first initialization only; never called by serve/restart."""
    safe_path(path)
    if not path.parent.is_dir():
        raise ArbiterDenied("private state directory is missing")
    if os.name == "posix" and stat.S_IMODE(path.parent.stat().st_mode) & 0o077:
        raise ArbiterDenied("arbiter state directory permissions are broad")
    _validate_trust_root(trust_root)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except OSError as exc:
        raise ArbiterDenied("existing or unavailable state cannot be initialized") from exc
    os.close(fd)
    # A failed initialization leaves the file for review; it is never silently reset.
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("CREATE TABLE authority (id INTEGER PRIMARY KEY CHECK(id=1), "
                     "schema TEXT NOT NULL, trust_digest TEXT NOT NULL, epoch INTEGER NOT NULL, "
                     "last_clock_ms INTEGER NOT NULL, permit_json TEXT)")
        conn.execute("CREATE TABLE used_nonces (nonce TEXT PRIMARY KEY)")
        conn.execute("INSERT INTO authority VALUES (1, ?, ?, 0, 0, NULL)",
                     (STATE_SCHEMA, digest(dict(trust_root))))


def unavailable_fence(previous: str, target: str, nonce: str, until_ms: int) -> Mapping:
    raise ArbiterDenied("external fencing controller is not provisioned")


class ExternalPaperArbiter:
    def __init__(self, state_path: Path, trust_root: Mapping,
                 signer: Callable[[bytes], str], *, fence: Callable = unavailable_fence,
                 clock_ms: Callable[[], int] | None = None):
        private_file(state_path)
        self.path = state_path
        self.trust = _validate_trust_root(trust_root)
        self.signer = signer
        self.fence = fence
        self.clock = clock_ms or (lambda: time.time_ns() // 1_000_000)
        with self.connection() as conn:
            self.state(conn)  # Corrupt/missing/reset ownership state fails at startup.

    @contextmanager
    def connection(self):
        private_file(self.path)
        conn = None
        try:
            conn = sqlite3.connect(self.path.as_uri() + "?mode=rw", uri=True,
                                   isolation_level=None, timeout=5)
            conn.execute("PRAGMA synchronous=FULL")
            yield conn
        except sqlite3.Error as exc:
            raise ArbiterDenied("durable arbiter state is unavailable") from exc
        finally:
            if conn is not None:
                conn.close()

    def state(self, conn) -> tuple:
        row = conn.execute("SELECT schema, trust_digest, epoch, last_clock_ms, permit_json "
                           "FROM authority WHERE id=1").fetchone()
        if (not row or row[0] != STATE_SCHEMA or row[1] != digest(self.trust)
                or type(row[2]) is not int or not 0 <= row[2] < 2**63 - 1
                or type(row[3]) is not int or row[3] < 0):
            raise ArbiterDenied("arbiter state identity or epoch is invalid")
        if row[4] is None:
            if row[2] != 0 or row[3] != 0:
                raise ArbiterDenied("persisted permit is missing")
        else:
            try:
                permit = json.loads(row[4])
                verify_writer_permit(permit, self.trust,
                    local_writer_id=permit["writer_id"],
                    local_journal_checkpoint_digest=permit["journal_checkpoint_digest"],
                    last_accepted_epoch=row[2] - 1, now_ms=permit["issued_at_ms"])
                if permit["epoch"] != row[2] or permit["issued_at_ms"] != row[3]:
                    raise ValueError("state binding")
            except (ValueError, KeyError, TypeError) as exc:
                raise ArbiterDenied("persisted permit integrity is invalid") from exc
        return row

    def now(self, last_ms: int) -> int:
        value = self.clock()
        if type(value) is not int or not 0 < value < 2**63 - MAX_TTL_MS - 5000 or value < last_ms:
            raise ArbiterDenied("arbiter clock is invalid or moved backwards")
        return value

    def current(self, writer_id: str) -> dict:
        if writer_id not in WRITERS:
            raise ArbiterDenied("unknown writer")
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")  # A hold check must not race a new takeover.
            row = self.state(conn)
            now = self.now(row[3])
            permit = json.loads(row[4]) if row[4] else None
            if not permit or permit["writer_id"] != writer_id or now >= permit["expires_at_ms"]:
                raise ArbiterDenied("no current permit for this writer")
            self.observe(permit["previous_writer_id"], writer_id, permit["nonce_sha256"],
                         permit["expires_at_ms"], now)
            return permit

    def observe(self, previous: str, target: str, nonce: str, expires: int, started: int):
        try:
            observation = dict(self.fence(previous, target, nonce, expires + 5000))
        except ArbiterDenied:
            raise
        except Exception as exc:
            raise ArbiterDenied("external fencing controller is unavailable") from exc
        now = self.now(started)
        obs_keys = {"schema", "writer_id", "target_writer_id", "controller_id",
                    "method", "fenced", "restart_inhibited", "observed_at_ms",
                    "hold_until_ms", "request_nonce"}
        if (set(observation) != obs_keys or observation.get("schema") != OBSERVATION_SCHEMA
                or observation.get("writer_id") != previous
                or observation.get("target_writer_id") != target
                or not isinstance(observation.get("controller_id"), str)
                or not observation["controller_id"]
                or observation["controller_id"].upper() in WRITERS
                or observation.get("method") not in ALLOWED_FENCE_METHODS
                or observation.get("fenced") is not True
                or observation.get("restart_inhibited") is not True
                or observation.get("request_nonce") != nonce
                or type(observation.get("observed_at_ms")) is not int
                or not started <= observation["observed_at_ms"] <= now
                or now - observation["observed_at_ms"] > 30_000
                or type(observation.get("hold_until_ms")) is not int
                or observation["hold_until_ms"] < expires + 5000
                or now >= expires):
            raise ArbiterDenied("positive external fencing observation is invalid")
        return observation, now

    def issue(self, request: Mapping) -> dict:
        expected = {"writer_id", "journal_checkpoint_digest", "request_nonce", "ttl_ms"}
        if not isinstance(request, Mapping) or set(request) != expected:
            raise ArbiterDenied("permit request contract is invalid")
        target, checkpoint, nonce, ttl = (request[k] for k in
            ("writer_id", "journal_checkpoint_digest", "request_nonce", "ttl_ms"))
        if (not isinstance(target, str) or target not in WRITERS
                or not isinstance(checkpoint, str) or not HEX64.fullmatch(checkpoint)
                or not isinstance(nonce, str) or not HEX64.fullmatch(nonce)
                or type(ttl) is not int or not 1000 <= ttl <= MAX_TTL_MS):
            raise ArbiterDenied("permit request identity, checkpoint or TTL is invalid")
        previous = PRIMARY_WRITER if target == FAILOVER_WRITER else FAILOVER_WRITER
        with self.connection() as conn:
            # Serialize fencing AND issuance across all service processes.
            conn.execute("BEGIN IMMEDIATE")
            row = self.state(conn)
            started = self.now(row[3])
            existing = json.loads(row[4]) if row[4] else None
            if existing and started < existing["expires_at_ms"]:
                raise ArbiterDenied("an existing writer lease is still active")
            if conn.execute("SELECT 1 FROM used_nonces WHERE nonce=?", (nonce,)).fetchone():
                raise ArbiterDenied("permit request nonce was already used")
            expires = started + ttl
            observation, now = self.observe(previous, target, nonce, expires, started)
            core = {"schema": PERMIT_SCHEMA, "arbiter_id": self.trust["arbiter_id"],
                    "key_id": self.trust["key_id"], "epoch": row[2] + 1,
                    "writer_id": target, "previous_writer_id": previous,
                    "previous_writer_fenced": True, "fence_method": observation["method"],
                    "fence_proof_sha256": digest(observation),
                    "journal_checkpoint_digest": checkpoint, "issued_at_ms": now,
                    "expires_at_ms": expires, "nonce_sha256": nonce, "paper_only": True,
                    "live_trading_authority": False, "protective_exit_authority": ["reduce", "close"]}
            permit = {**core, "permit_digest": digest(core), "signature_b64": self.signer(canonical(core))}
            verify_writer_permit(permit, self.trust, local_writer_id=target,
                local_journal_checkpoint_digest=checkpoint, last_accepted_epoch=row[2], now_ms=now)
            conn.execute("INSERT INTO used_nonces VALUES (?)", (nonce,))
            conn.execute("UPDATE authority SET epoch=?, last_clock_ms=?, permit_json=? WHERE id=1",
                         (core["epoch"], now, canonical(permit).decode("utf-8")))
            conn.commit()  # Never return a signed grant before it is durable.
            return permit


class OpenSSLSigner:
    def __init__(self, key: Path):
        private_file(key)
        self.key = key

    def run(self, args: list[str], data: bytes | None = None) -> bytes:
        private_file(self.key)
        try:
            result = subprocess.run(["openssl", *args], input=data, capture_output=True,
                                    timeout=10, check=True)
        except (OSError, subprocess.SubprocessError) as exc:
            raise ArbiterDenied("external private-key operation failed") from exc
        return result.stdout

    def __call__(self, data: bytes) -> str:
        return base64.b64encode(self.run(["dgst", "-sha256", "-sign", str(self.key),
                                         "-sigopt", "rsa_padding_mode:pkcs1"], data)).decode("ascii")

    def trust_root(self, arbiter_id: str) -> dict:
        raw = self.run(["rsa", "-in", str(self.key), "-noout", "-modulus"]).decode("ascii").strip()
        if not re.fullmatch(r"Modulus=[0-9A-Fa-f]+", raw):
            raise ArbiterDenied("external RSA public key is invalid")
        modulus = raw.split("=", 1)[1].lower()
        # Read the actual exponent too; an unexpected existing key fails closed.
        public_text = self.run(["pkey", "-in", str(self.key), "-text_pub", "-noout"]).decode("ascii")
        if not re.search(r"Exponent: 65537 \(0x10001\)", public_text):
            raise ArbiterDenied("external RSA public exponent is invalid")
        trust = {"schema": TRUST_SCHEMA, "arbiter_id": arbiter_id,
                 "key_id": "rsa-" + digest({"n": modulus})[:24],
                 "rsa_modulus_hex": modulus, "rsa_exponent": 65537, "enabled": True}
        return _validate_trust_root(trust)


def assert_external_host() -> None:
    actual = socket.gethostname().split(".", 1)[0].upper()
    computer = os.environ.get("COMPUTERNAME", "").upper()
    if (sys.platform != "linux" or "microsoft" in platform.release().lower()
            or actual in WRITERS or computer in WRITERS):
        raise ArbiterDenied("signing service must run on an independent Linux host")


def handler_for(arbiter: ExternalPaperArbiter, tokens: Mapping[str, str]):
    if set(tokens) != WRITERS or any(not isinstance(v, str) or len(v) < 64 for v in tokens.values()):
        raise ArbiterDenied("per-writer authentication tokens are invalid")
    if len(set(tokens.values())) != len(WRITERS):
        raise ArbiterDenied("writer credentials must be distinct")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Do not log authorization headers or private request details.

        def setup(self):
            super().setup()
            self.connection.settimeout(10)

        def reply(self, status: int, value: object):
            data = canonical(value)
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def writer(self):
            header = self.headers.get("Authorization", "")
            if not header.startswith("Bearer "):
                return None
            supplied = header[7:]
            return next((writer for writer, token in tokens.items()
                         if hmac.compare_digest(supplied.encode(), token.encode())), None)

        def do_GET(self):
            if self.path == "/healthz":
                try:
                    with arbiter.connection() as conn:
                        arbiter.state(conn)
                except (ArbiterDenied, OSError):
                    self.reply(503, {"status": "state_unavailable", "takeover_enabled": False})
                    return
                self.reply(200, {"status": "running", "fencing_configured": False,
                                 "takeover_enabled": False, "paper_only": True,
                                 "live_trading_authority": False})
                return
            writer = self.writer()
            if not writer:
                self.reply(401, {"error": "authentication_required"})
                return
            try:
                if self.path == "/v1/trust-root":
                    self.reply(200, arbiter.trust)
                elif self.path == "/v1/current-permit":
                    self.reply(200, arbiter.current(writer))
                else:
                    self.reply(404, {"error": "unknown_route"})
            except ArbiterDenied:
                self.reply(409, {"error": "current_authority_unavailable"})

        def do_POST(self):
            writer = self.writer()
            if not writer:
                self.reply(401, {"error": "authentication_required"})
                return
            if self.path != "/v1/permit":
                self.reply(404, {"error": "unknown_route"})
                return
            try:
                if self.headers.get("Transfer-Encoding"):
                    raise ArbiterDenied("unsupported transfer encoding")
                lengths = self.headers.get_all("Content-Length", [])
                if len(lengths) != 1 or not lengths[0].isdigit() or not 0 < int(lengths[0]) <= MAX_BODY:
                    raise ArbiterDenied("request size is invalid")
                raw = self.rfile.read(int(lengths[0]))
                if len(raw) != int(lengths[0]):
                    raise ArbiterDenied("request body is incomplete")
                request = json.loads(raw)
                if not isinstance(request, dict) or request.get("writer_id") != writer:
                    raise ArbiterDenied("writer credential does not match request")
                self.reply(200, arbiter.issue(request))
            except (ValueError, KeyError, TypeError):
                self.reply(409, {"error": "permit_denied", "takeover_enabled": False})
    return Handler


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["init", "serve"])
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--arbiter-id", default="nexus-external-paper-arbiter")
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8089)
    parser.add_argument("--tls-cert", type=Path)
    parser.add_argument("--tls-key", type=Path)
    args = parser.parse_args(argv)
    assert_external_host()
    root = args.state_root
    safe_path(root)
    if not root.is_dir() or stat.S_IMODE(root.stat().st_mode) & 0o077:
        raise ArbiterDenied("a private persistent state directory is required")
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", args.arbiter_id):
        raise ArbiterDenied("arbiter identity is invalid")
    key, state, token_file = root / "private-key.pem", root / "authority.sqlite3", root / "writer-tokens.json"
    if args.mode == "init":
        if any(root.iterdir()):
            raise ArbiterDenied("nonempty state root cannot be initialized")
        # Generated only on the independently selected deployment host. No key output.
        fd = os.open(key, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        subprocess.run(["openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt",
                        "rsa_keygen_bits:3072", "-out", str(key)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=60)
        signer = OpenSSLSigner(key)
        trust = signer.trust_root(args.arbiter_id)
        bootstrap_state(state, trust)
        with token_file.open("x", encoding="utf-8") as handle:
            os.chmod(token_file, 0o600)
            json.dump({writer: secrets.token_hex(32) for writer in sorted(WRITERS)}, handle)
        with (root / "trust-root.json").open("x", encoding="utf-8") as handle:
            os.chmod(handle.name, 0o600)
            handle.write(canonical(trust).decode("utf-8") + "\n")
        print("arbiter_initialized=true takeover_enabled=false live_trading_authority=false")
        return 0
    private_file(token_file)
    private_file(root / "trust-root.json")
    signer = OpenSSLSigner(key)
    trust = signer.trust_root(args.arbiter_id)
    if json.loads((root / "trust-root.json").read_text()) != trust:
        raise ArbiterDenied("pinned public trust root changed")
    if not 1 <= args.port <= 65535:
        raise ArbiterDenied("invalid listen port")
    if args.bind not in {"127.0.0.1", "::1", "localhost"} and not (args.tls_cert and args.tls_key):
        raise ArbiterDenied("non-loopback listening requires configured TLS")
    if bool(args.tls_cert) != bool(args.tls_key):
        raise ArbiterDenied("both TLS certificate and key are required")
    arbiter = ExternalPaperArbiter(state, trust, signer)
    server = ThreadingHTTPServer((args.bind, args.port),
                                handler_for(arbiter, json.loads(token_file.read_text())))
    if args.tls_cert:
        private_file(args.tls_key)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(args.tls_cert, args.tls_key)
        server.socket = context.wrap_socket(server.socket, server_side=True)
    print("arbiter_serving=true takeover_enabled=false live_trading_authority=false", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
