from __future__ import annotations

import base64
import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from nexus_paper_writer_fence import (
    FAILOVER_WRITER,
    PRIMARY_WRITER,
    PERMIT_SCHEMA,
    TRUST_SCHEMA,
    PaperWriterFenceError,
    digest,
    load_fence_state,
    verify_and_record_writer_permit,
    verify_writer_permit,
)

# Test-only RSA private exponent. Production writers receive only the public
# trust root; the external arbiter's private key must never live on either
# writer laptop.
N_HEX = (
    "d3ac34dbc7053cc478b5ba11d08826224f0a98ca445e3de2458dd4c1eda2ddc6"
    "9e91a6c66940550520da14fa6603de2a6097903023f4b1671073c4fc7f3d58a3"
    "a8e0c30b38ae38a968c092f678cff893c296423b916fca057c06ba0c588b1638"
    "fb0acdf447c75afe0d2d1faaaad7b26ef7f46f0d14a8a55a4aa384363675c83"
    "ac81b0ca365877af4c7ede07a0c5e8a39b290abd84ffa9fb9b048b721bef2ea6"
    "4011da0c82e8ba907ab256d1726188a6d5ab531f13b7b47d1986951fbbc2be1a"
    "d3327fd56e3aff7f82e3d5c7fe50b43480f9d5a917b056903f79e929ce84a94e"
    "dc47a8422e0e8b79e6ed88b3be8cbf282f42c220f23813a48a87c73c12cb0de1f"
)
N = int(N_HEX, 16)
E = 65537
D = 3554087789546061899960940412957884818291887526919057237124014465562997948181484251540652845748628131635956346568633609952106763445501583127714671059443972812364924675697917476854854878531728936178530647388044915481048783739801171654558124972554809665635978815975430899428532227503881824866849085098007270880392630006801189239386525098798744007765618517372213614017930368041512283320930051870528146844207461452165831718529288902386400802411483400138913240207415378827674993708183994035931124849637670555368796365463121448261502493439132743268940328951235002787479806587638918211312146423901766524872091791107338207261
DIGEST_INFO = bytes.fromhex("3031300d060960864801650304020105000420")
CHECKPOINT = "a" * 64
FENCE_PROOF = "b" * 64
NONCE = "c" * 64
NOW = 1_800_000_000_000


def _canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def _sign(core):
    hashed = hashlib.sha256(_canonical(core)).digest()
    width = (N.bit_length() + 7) // 8
    tail = DIGEST_INFO + hashed
    padding = b"\xff" * (width - len(tail) - 3)
    encoded = b"\x00\x01" + padding + b"\x00" + tail
    signature = pow(int.from_bytes(encoded, "big"), D, N).to_bytes(width, "big")
    return base64.b64encode(signature).decode("ascii")


def _trust():
    return {
        "schema": TRUST_SCHEMA,
        "arbiter_id": "nexus-external-fence-arbiter",
        "key_id": "arbiter-test-rsa-2048",
        "rsa_modulus_hex": N_HEX,
        "rsa_exponent": E,
        "enabled": True,
    }


def _permit(
    *,
    epoch=7,
    writer=FAILOVER_WRITER,
    previous=PRIMARY_WRITER,
    checkpoint=CHECKPOINT,
    fence_method="external_stonith",
    previous_fenced=True,
    live=False,
    protective=("reduce", "close"),
    issued=NOW - 10_000,
    expires=NOW + 60_000,
):
    core = {
        "schema": PERMIT_SCHEMA,
        "arbiter_id": "nexus-external-fence-arbiter",
        "key_id": "arbiter-test-rsa-2048",
        "epoch": epoch,
        "writer_id": writer,
        "previous_writer_id": previous,
        "previous_writer_fenced": previous_fenced,
        "fence_method": fence_method,
        "fence_proof_sha256": FENCE_PROOF,
        "journal_checkpoint_digest": checkpoint,
        "issued_at_ms": issued,
        "expires_at_ms": expires,
        "nonce_sha256": NONCE,
        "paper_only": True,
        "live_trading_authority": live,
        "protective_exit_authority": list(protective),
    }
    return {
        **core,
        "permit_digest": digest(core),
        "signature_b64": _sign(core),
    }


def test_valid_external_fence_permit_authorizes_only_exact_writer_and_checkpoint():
    receipt = verify_writer_permit(
        _permit(),
        _trust(),
        local_writer_id=FAILOVER_WRITER,
        local_journal_checkpoint_digest=CHECKPOINT,
        last_accepted_epoch=6,
        now_ms=NOW,
    )
    assert receipt["epoch"] == 7
    assert receipt["writer_id"] == FAILOVER_WRITER
    assert receipt["previous_writer_id"] == PRIMARY_WRITER
    assert receipt["paper_only"] is True
    assert receipt["live_trading_authority"] is False
    assert receipt["protective_exit_authority"] == ["reduce", "close"]


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda p: p.update(previous_writer_fenced=False), "positive fencing"),
        (lambda p: p.update(fence_method="network_timeout"), "reachability"),
        (lambda p: p.update(live_trading_authority=True), "Paper/Live"),
        (lambda p: p.update(protective_exit_authority=["reduce", "close", "open"]), "Protective Exit"),
    ],
)
def test_authority_widening_or_unproven_primary_fence_fails_closed(mutator, message):
    permit = _permit()
    core = {k: v for k, v in permit.items() if k not in {"permit_digest", "signature_b64"}}
    mutator(core)
    permit = {**core, "permit_digest": digest(core), "signature_b64": _sign(core)}
    with pytest.raises(PaperWriterFenceError, match=message):
        verify_writer_permit(
            permit,
            _trust(),
            local_writer_id=FAILOVER_WRITER,
            local_journal_checkpoint_digest=CHECKPOINT,
            last_accepted_epoch=6,
            now_ms=NOW,
        )


def test_stale_or_replayed_epoch_is_rejected():
    with pytest.raises(PaperWriterFenceError, match="stale or replayed"):
        verify_writer_permit(
            _permit(epoch=7),
            _trust(),
            local_writer_id=FAILOVER_WRITER,
            local_journal_checkpoint_digest=CHECKPOINT,
            last_accepted_epoch=7,
            now_ms=NOW,
        )


def test_checkpoint_mismatch_is_rejected():
    with pytest.raises(PaperWriterFenceError, match="checkpoint"):
        verify_writer_permit(
            _permit(),
            _trust(),
            local_writer_id=FAILOVER_WRITER,
            local_journal_checkpoint_digest="d" * 64,
            last_accepted_epoch=6,
            now_ms=NOW,
        )


def test_expired_or_overlong_permit_is_rejected():
    with pytest.raises(PaperWriterFenceError, match="fresh and bounded"):
        verify_writer_permit(
            _permit(issued=NOW - 120_000, expires=NOW - 1),
            _trust(),
            local_writer_id=FAILOVER_WRITER,
            local_journal_checkpoint_digest=CHECKPOINT,
            last_accepted_epoch=6,
            now_ms=NOW,
        )
    with pytest.raises(PaperWriterFenceError, match="fresh and bounded"):
        verify_writer_permit(
            _permit(issued=NOW - 1, expires=NOW + 11 * 60 * 1000),
            _trust(),
            local_writer_id=FAILOVER_WRITER,
            local_journal_checkpoint_digest=CHECKPOINT,
            last_accepted_epoch=6,
            now_ms=NOW,
        )


def test_tampered_signature_or_missing_arbiter_fails_closed():
    permit = _permit()
    tampered = deepcopy(permit)
    tampered["signature_b64"] = base64.b64encode(b"0" * 256).decode("ascii")
    with pytest.raises(PaperWriterFenceError, match="signature"):
        verify_writer_permit(
            tampered,
            _trust(),
            local_writer_id=FAILOVER_WRITER,
            local_journal_checkpoint_digest=CHECKPOINT,
            last_accepted_epoch=6,
            now_ms=NOW,
        )
    trust = _trust()
    trust["enabled"] = False
    with pytest.raises(PaperWriterFenceError, match="trust root"):
        verify_writer_permit(
            permit,
            trust,
            local_writer_id=FAILOVER_WRITER,
            local_journal_checkpoint_digest=CHECKPOINT,
            last_accepted_epoch=6,
            now_ms=NOW,
        )


def test_permit_for_other_writer_cannot_create_split_brain():
    permit = _permit(writer=FAILOVER_WRITER, previous=PRIMARY_WRITER, epoch=8)
    with pytest.raises(PaperWriterFenceError, match="targets another machine"):
        verify_writer_permit(
            permit,
            _trust(),
            local_writer_id=PRIMARY_WRITER,
            local_journal_checkpoint_digest=CHECKPOINT,
            last_accepted_epoch=7,
            now_ms=NOW,
        )


def test_primary_recovery_cannot_reuse_lower_epoch_after_failover_ownership():
    primary = _permit(
        writer=PRIMARY_WRITER,
        previous=FAILOVER_WRITER,
        epoch=7,
    )
    with pytest.raises(PaperWriterFenceError, match="stale or replayed"):
        verify_writer_permit(
            primary,
            _trust(),
            local_writer_id=PRIMARY_WRITER,
            local_journal_checkpoint_digest=CHECKPOINT,
            last_accepted_epoch=8,
            now_ms=NOW,
        )


def test_epoch_state_is_persisted_atomically_and_blocks_replay(tmp_path: Path):
    path = tmp_path / "paper-writer-fence.json"
    permit = _permit(epoch=9)
    receipt = verify_and_record_writer_permit(
        permit,
        _trust(),
        local_writer_id=FAILOVER_WRITER,
        local_journal_checkpoint_digest=CHECKPOINT,
        state_path=path,
        now_ms=NOW,
    )
    state = load_fence_state(path)
    assert state["last_accepted_epoch"] == 9
    assert state["last_permit_digest"] == permit["permit_digest"]
    assert state["last_receipt_digest"] == receipt["receipt_digest"]

    with pytest.raises(PaperWriterFenceError, match="stale or replayed"):
        verify_and_record_writer_permit(
            permit,
            _trust(),
            local_writer_id=FAILOVER_WRITER,
            local_journal_checkpoint_digest=CHECKPOINT,
            state_path=path,
            now_ms=NOW,
        )
