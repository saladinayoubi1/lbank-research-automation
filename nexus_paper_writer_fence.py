"""Fail-closed Paper-writer fencing contract for NEXUS dual-laptop failover.

This module is intentionally not wired into the currently disabled failover
Scheduled Tasks.  It verifies a short-lived writer permit signed by an external
arbiter whose *private* key is not present on either laptop.  GitHub is not the
lock or runtime database.

A permit can authorize Paper writing only when:
- the previous writer is positively fenced by the external arbiter;
- a strictly monotonic epoch is newer than local accepted state;
- the exact ProductRuntime journal/checkpoint digest matches;
- the target writer identity matches this machine;
- the permit is fresh and bounded;
- Paper-only / Live=false and Protective Exit reduce/close-only authority hold.

The persistent epoch file is only a local replay guard.  Exclusivity comes from
the external arbiter signature/epoch, not from this file.
"""
from __future__ import annotations

import base64
from contextlib import contextmanager
import hashlib
import hmac
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Callable, Mapping

PERMIT_SCHEMA = "nexus.paper-writer-fence-permit.v1"
TRUST_SCHEMA = "nexus.paper-writer-fence-trust-root.v1"
STATE_SCHEMA = "nexus.paper-writer-fence-state.v1"
RECEIPT_SCHEMA = "nexus.paper-writer-fence-receipt.v1"
PRIMARY_WRITER = "DESKTOP-1R1081M"
FAILOVER_WRITER = "DESKTOP-F4SA4VL"
WRITERS = frozenset({PRIMARY_WRITER, FAILOVER_WRITER})
ALLOWED_FENCE_METHODS = frozenset({"external_stonith", "external_power_fence"})
PROTECTIVE_EXIT_AUTHORITY = ("reduce", "close")
MAX_TTL_MS = 10 * 60 * 1000
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_HEX = re.compile(r"^[0-9a-f]+$")
_SHA256_DIGEST_INFO_PREFIX = bytes.fromhex("3031300d060960864801650304020105000420")


class PaperWriterFenceError(ValueError):
    pass


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PaperWriterFenceError("fence payload is not canonical JSON") from exc


def digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _rsa_verify_pkcs1_v15_sha256(
    message: bytes,
    signature_b64: str,
    *,
    modulus_hex: str,
    exponent: int,
) -> bool:
    if (
        not isinstance(signature_b64, str)
        or not isinstance(modulus_hex, str)
        or not _HEX.fullmatch(modulus_hex)
        or isinstance(exponent, bool)
        or not isinstance(exponent, int)
        or exponent < 3
        or exponent % 2 == 0
    ):
        return False
    try:
        modulus = int(modulus_hex, 16)
        signature = base64.b64decode(signature_b64, validate=True)
    except (ValueError, TypeError):
        return False
    if modulus.bit_length() < 2048:
        return False
    width = (modulus.bit_length() + 7) // 8
    if len(signature) != width:
        return False
    sig_int = int.from_bytes(signature, "big")
    if sig_int <= 0 or sig_int >= modulus:
        return False
    encoded = pow(sig_int, exponent, modulus).to_bytes(width, "big")
    hashed = hashlib.sha256(message).digest()
    tail = _SHA256_DIGEST_INFO_PREFIX + hashed
    padding_len = width - len(tail) - 3
    if padding_len < 8:
        return False
    expected = b"\x00\x01" + (b"\xff" * padding_len) + b"\x00" + tail
    return hmac.compare_digest(encoded, expected)


def _validate_trust_root(value: Mapping[str, Any]) -> dict[str, Any]:
    trust = dict(value)
    expected = {
        "schema",
        "arbiter_id",
        "key_id",
        "rsa_modulus_hex",
        "rsa_exponent",
        "enabled",
    }
    if set(trust) != expected:
        raise PaperWriterFenceError("external arbiter trust-root schema mismatch")
    if (
        trust.get("schema") != TRUST_SCHEMA
        or trust.get("enabled") is not True
        or not isinstance(trust.get("arbiter_id"), str)
        or not trust["arbiter_id"]
        or not isinstance(trust.get("key_id"), str)
        or not trust["key_id"]
        or not isinstance(trust.get("rsa_modulus_hex"), str)
        or not _HEX.fullmatch(trust["rsa_modulus_hex"])
        or int(trust["rsa_modulus_hex"], 16).bit_length() < 2048
        or trust.get("rsa_exponent") != 65537
    ):
        raise PaperWriterFenceError("external arbiter trust root is invalid or disabled")
    return trust


def _permit_core(value: Mapping[str, Any]) -> dict[str, Any]:
    permit = dict(value)
    signature = permit.pop("signature_b64", None)
    claimed_digest = permit.pop("permit_digest", None)
    if not isinstance(signature, str) or not signature:
        raise PaperWriterFenceError("external arbiter signature is missing")
    if not isinstance(claimed_digest, str) or not _HEX64.fullmatch(claimed_digest):
        raise PaperWriterFenceError("permit digest is invalid")
    expected = {
        "schema",
        "arbiter_id",
        "key_id",
        "epoch",
        "writer_id",
        "previous_writer_id",
        "previous_writer_fenced",
        "fence_method",
        "fence_proof_sha256",
        "journal_checkpoint_digest",
        "issued_at_ms",
        "expires_at_ms",
        "nonce_sha256",
        "paper_only",
        "live_trading_authority",
        "protective_exit_authority",
    }
    if set(permit) != expected:
        raise PaperWriterFenceError("writer permit schema mismatch")
    if digest(permit) != claimed_digest:
        raise PaperWriterFenceError("writer permit digest mismatch")
    return {
        "core": permit,
        "signature_b64": signature,
        "permit_digest": claimed_digest,
    }


def verify_writer_permit(
    permit: Mapping[str, Any],
    trust_root: Mapping[str, Any],
    *,
    local_writer_id: str,
    local_journal_checkpoint_digest: str,
    last_accepted_epoch: int,
    now_ms: int,
) -> dict[str, Any]:
    trust = _validate_trust_root(trust_root)
    parts = _permit_core(permit)
    core = parts["core"]

    if local_writer_id not in WRITERS:
        raise PaperWriterFenceError("local writer identity is not a protected NEXUS writer")
    if core.get("schema") != PERMIT_SCHEMA:
        raise PaperWriterFenceError("writer permit schema version is invalid")
    if (
        core.get("arbiter_id") != trust["arbiter_id"]
        or core.get("key_id") != trust["key_id"]
    ):
        raise PaperWriterFenceError("writer permit is signed for another arbiter/key")
    if core.get("writer_id") != local_writer_id:
        raise PaperWriterFenceError("writer permit targets another machine")
    previous = core.get("previous_writer_id")
    if previous not in WRITERS or previous == local_writer_id:
        raise PaperWriterFenceError("previous writer identity is invalid")
    if core.get("previous_writer_fenced") is not True:
        raise PaperWriterFenceError("previous writer lacks positive fencing proof")
    if core.get("fence_method") not in ALLOWED_FENCE_METHODS:
        raise PaperWriterFenceError("network reachability is not valid fencing proof")
    if not _HEX64.fullmatch(str(core.get("fence_proof_sha256", ""))):
        raise PaperWriterFenceError("external fencing proof digest is invalid")
    checkpoint = core.get("journal_checkpoint_digest")
    if (
        not isinstance(local_journal_checkpoint_digest, str)
        or not _HEX64.fullmatch(local_journal_checkpoint_digest)
        or checkpoint != local_journal_checkpoint_digest
    ):
        raise PaperWriterFenceError("ProductRuntime journal/checkpoint identity mismatch")

    epoch = core.get("epoch")
    if (
        isinstance(epoch, bool)
        or not isinstance(epoch, int)
        or epoch <= 0
        or isinstance(last_accepted_epoch, bool)
        or not isinstance(last_accepted_epoch, int)
        or last_accepted_epoch < 0
        or epoch <= last_accepted_epoch
    ):
        raise PaperWriterFenceError("writer permit epoch is stale or replayed")

    issued = core.get("issued_at_ms")
    expires = core.get("expires_at_ms")
    if (
        isinstance(now_ms, bool)
        or not isinstance(now_ms, int)
        or isinstance(issued, bool)
        or not isinstance(issued, int)
        or isinstance(expires, bool)
        or not isinstance(expires, int)
        or issued <= 0
        or expires <= issued
        or expires - issued > MAX_TTL_MS
        or now_ms < issued
        or now_ms >= expires
    ):
        raise PaperWriterFenceError("writer permit is not fresh and bounded")
    if not _HEX64.fullmatch(str(core.get("nonce_sha256", ""))):
        raise PaperWriterFenceError("writer permit nonce binding is invalid")
    if core.get("paper_only") is not True or core.get("live_trading_authority") is not False:
        raise PaperWriterFenceError("writer permit attempts to widen Paper/Live authority")
    if tuple(core.get("protective_exit_authority") or ()) != PROTECTIVE_EXIT_AUTHORITY:
        raise PaperWriterFenceError("Protective Exit authority must remain reduce/close only")

    if not _rsa_verify_pkcs1_v15_sha256(
        _canonical(core),
        parts["signature_b64"],
        modulus_hex=trust["rsa_modulus_hex"],
        exponent=trust["rsa_exponent"],
    ):
        raise PaperWriterFenceError("external arbiter signature verification failed")

    receipt_core = {
        "schema": RECEIPT_SCHEMA,
        "arbiter_id": trust["arbiter_id"],
        "key_id": trust["key_id"],
        "epoch": epoch,
        "writer_id": local_writer_id,
        "previous_writer_id": previous,
        "permit_digest": parts["permit_digest"],
        "journal_checkpoint_digest": checkpoint,
        "fence_proof_sha256": core["fence_proof_sha256"],
        "expires_at_ms": expires,
        "paper_only": True,
        "live_trading_authority": False,
        "protective_exit_authority": list(PROTECTIVE_EXIT_AUTHORITY),
    }
    return {**receipt_core, "receipt_digest": digest(receipt_core)}


def load_fence_state(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise PaperWriterFenceError("fence state path is unsafe")
    if not path.exists():
        return {
            "schema": STATE_SCHEMA,
            "last_accepted_epoch": 0,
            "last_permit_digest": None,
            "last_receipt_digest": None,
        }
    if path.is_symlink() or not path.is_file():
        raise PaperWriterFenceError("fence state path is unsafe")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PaperWriterFenceError("fence state is unreadable") from exc
    expected = {
        "schema",
        "last_accepted_epoch",
        "last_permit_digest",
        "last_receipt_digest",
    }
    if (
        not isinstance(value, dict)
        or set(value) != expected
        or value.get("schema") != STATE_SCHEMA
        or isinstance(value.get("last_accepted_epoch"), bool)
        or not isinstance(value.get("last_accepted_epoch"), int)
        or value["last_accepted_epoch"] < 0
        or (
            value.get("last_permit_digest") is not None
            and not _HEX64.fullmatch(str(value["last_permit_digest"]))
        )
        or (
            value.get("last_receipt_digest") is not None
            and not _HEX64.fullmatch(str(value["last_receipt_digest"]))
        )
    ):
        raise PaperWriterFenceError("fence state contract is invalid")
    return dict(value)


def verify_and_record_writer_permit(
    permit: Mapping[str, Any],
    trust_root: Mapping[str, Any],
    *,
    local_writer_id: str,
    local_journal_checkpoint_digest: str,
    state_path: Path,
    now_ms: int,
) -> dict[str, Any]:
    with _exclusive_fence_state(state_path):
        state = load_fence_state(state_path)
        receipt = verify_writer_permit(
            permit, trust_root, local_writer_id=local_writer_id,
            local_journal_checkpoint_digest=local_journal_checkpoint_digest,
            last_accepted_epoch=state["last_accepted_epoch"], now_ms=now_ms,
        )
        next_state = {
            "schema": STATE_SCHEMA, "last_accepted_epoch": receipt["epoch"],
            "last_permit_digest": receipt["permit_digest"],
            "last_receipt_digest": receipt["receipt_digest"],
        }
        tmp = state_path.with_name(state_path.name + ".tmp")
        # A prior/crashed/linked temporary file is not ours to overwrite.
        try:
            handle = tmp.open("x", encoding="utf-8", newline="\n")
        except OSError as exc:
            raise PaperWriterFenceError("fence temporary state requires review") from exc
        try:
            with handle:
                handle.write(json.dumps(next_state, sort_keys=True, indent=2)+"\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, state_path)
        finally:
            if tmp.exists():
                tmp.unlink()
        return receipt


@contextmanager
def _exclusive_fence_state(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_name(path.name + ".lock")
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise PaperWriterFenceError("fence acceptance is active or stale lock requires review") from exc
    try:
        os.close(fd)
        yield
    finally:
        lock.unlink()


def acquire_writer_guard(
    permit_loader: Callable[[], Mapping[str, Any]],
    trust_loader: Callable[[], Mapping[str, Any]],
    *,
    local_writer_id: str,
    takeover_checkpoint_digest: str,
    state_path: Path,
    clock_ms: Callable[[], int] | None = None,
) -> Callable[[], bool]:
    """Acquire once, then revalidate current external proof at every write.

    Loaders must obtain the real current arbiter proof/trust root and raise if
    unavailable. This API does not provision an arbiter or enable failover.
    The checkpoint is the immutable takeover checkpoint, not a later journal
    head. Startup/reboot must acquire a NEW epoch; persisted receipts are not
    accepted as a startup grant. A newer accepted epoch retires this guard.
    """
    clock = clock_ms or (lambda: time.time_ns() // 1_000_000)

    def current_proof():
        try:
            permit, trust = permit_loader(), trust_loader()
            if not isinstance(permit, Mapping) or not isinstance(trust, Mapping):
                raise ValueError("invalid proof")
            return permit, trust
        except Exception as exc:
            raise PaperWriterFenceError("current external arbiter proof is unavailable") from exc

    permit, trust = current_proof()
    receipt = verify_and_record_writer_permit(
        permit, trust, local_writer_id=local_writer_id,
        local_journal_checkpoint_digest=takeover_checkpoint_digest,
        state_path=state_path, now_ms=clock(),
    )

    def assert_authority() -> bool:
        permit, trust = current_proof()
        state = load_fence_state(state_path)
        if (state["last_accepted_epoch"] != receipt["epoch"]
                or state["last_permit_digest"] != receipt["permit_digest"]
                or state["last_receipt_digest"] != receipt["receipt_digest"]):
            raise PaperWriterFenceError("active writer ownership has changed")
        current = verify_writer_permit(
            permit, trust, local_writer_id=local_writer_id,
            local_journal_checkpoint_digest=takeover_checkpoint_digest,
            last_accepted_epoch=receipt["epoch"]-1, now_ms=clock(),
        )
        if current != receipt:
            raise PaperWriterFenceError("active writer permit has changed")
        return True

    return assert_authority
