import json
from pathlib import Path

import pytest

from scripts.build_release_evidence import build_bundle, parse_build_parameter_args
from scripts.release_gate import verify


SOURCE_SHA = "a" * 40
BUILDER = "github-actions/nexus-build-verification/test"
PARAMETERS = {
    "platform": "test",
    "runtime": "python-3.12",
    "signing": "disabled",
}


def _bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    artifact = tmp_path / "artifact.bin"
    artifact.write_bytes(b"nexus-release-build-parameter-binding")
    monkeypatch.chdir(tmp_path)
    bundle = tmp_path / "release-evidence"
    build_bundle(
        bundle,
        ["artifact.bin"],
        SOURCE_SHA,
        BUILDER,
        PARAMETERS,
    )
    return bundle


def test_build_parameters_are_canonical_and_exactly_verified(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bundle = _bundle(tmp_path, monkeypatch)
    provenance = json.loads((bundle / "provenance.json").read_text(encoding="utf-8"))

    assert provenance["build_parameters"] == dict(sorted(PARAMETERS.items()))
    checks = verify(
        bundle,
        require_signature=False,
        expected_source_commit=SOURCE_SHA,
        expected_builder=BUILDER,
        expected_build_parameters=PARAMETERS,
    )
    assert "provenance-build-parameters" in checks


def test_build_parameter_mismatch_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bundle = _bundle(tmp_path, monkeypatch)
    expected = dict(PARAMETERS)
    expected["runtime"] = "python-3.13"

    with pytest.raises(ValueError, match="provenance build_parameters mismatch"):
        verify(bundle, require_signature=False, expected_build_parameters=expected)


def test_build_parameter_extra_actual_value_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bundle = _bundle(tmp_path, monkeypatch)
    expected = {"platform": "test", "runtime": "python-3.12"}

    with pytest.raises(ValueError, match="provenance build_parameters mismatch"):
        verify(bundle, require_signature=False, expected_build_parameters=expected)


def test_build_parameter_tampering_cannot_be_silently_accepted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bundle = _bundle(tmp_path, monkeypatch)
    provenance_path = bundle / "provenance.json"
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    provenance["build_parameters"]["signing"] = "enabled"
    provenance_path.write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="provenance build_parameters mismatch"):
        verify(bundle, require_signature=False, expected_build_parameters=PARAMETERS)


def test_build_parameter_cli_parser_rejects_duplicates_and_malformed_values() -> None:
    with pytest.raises(ValueError, match="duplicate build parameter"):
        parse_build_parameter_args(["platform=windows", "platform=android"])
    with pytest.raises(ValueError, match="key=value"):
        parse_build_parameter_args(["platform"])
    with pytest.raises(ValueError, match="non-empty string"):
        parse_build_parameter_args(["platform="])
