from pathlib import Path

from phase7_offline_network_proof import _read


def test_offline_network_proof_reader_accepts_windows_powershell_utf8_bom(tmp_path: Path) -> None:
    proof = tmp_path / "offline-network-proof.json"
    proof.write_bytes(b"\xef\xbb\xbf{\"schema_version\":\"example\",\"value\":1}")

    assert _read(proof) == {"schema_version": "example", "value": 1}
