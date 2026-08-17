from __future__ import annotations

import pytest

from paper_live_airgap import (
    AirGapViolation,
    IndependentSafetyGateFailure,
    SecretMaterialDetected,
    ToolAllowlist,
    ToolDenied,
    canonical_contract_bytes,
    independent_airgap_check,
    redact_for_egress,
    scan_text_for_secrets,
    validate_paper_contract,
)


def paper_command(**changes):
    value = {
        "operation": "open",
        "symbol": "BTCUSDT",
        "side": "long",
        "quantity": "0.01",
        "reference_price": "60000",
        "execution_mode": "paper",
        "paper_trading_only": True,
        "provenance": {"source": "validated-public", "correlation_id": "corr-1"},
    }
    value.update(changes)
    return value


def test_paper_contract_and_validated_paper_tool_pass_independent_gate():
    result = validate_paper_contract(paper_command())
    assert result.paper_only is True
    assert result.reason_code == "paper_airgap_valid"
    assert independent_airgap_check(
        contract=paper_command(), tool="paper.execute_validated"
    ) == "independent_paper_airgap_pass"
    assert b'"execution_mode":"paper"' in canonical_contract_bytes(paper_command())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("api_key", "not-allowed"),
        ("exchange_credentials", {"key": "x"}),
        ("live_order", True),
        ("real_order", {"symbol": "BTCUSDT"}),
        ("withdrawal_address", "wallet"),
        ("billing", {"plan": "paid"}),
        ("signing_key", "key"),
        ("production_deployment", True),
        ("raw_chat_transcript", "private transcript"),
    ],
)
def test_forbidden_authority_fields_fail_closed_even_when_nested(field, value):
    contract = paper_command()
    contract["nested"] = {"request": {field: value}}
    with pytest.raises(AirGapViolation, match="forbidden"):
        validate_paper_contract(contract)


def test_live_or_ambiguous_execution_mode_is_rejected():
    with pytest.raises(AirGapViolation, match="not paper"):
        validate_paper_contract(paper_command(execution_mode="live"))
    with pytest.raises(AirGapViolation, match="not paper"):
        validate_paper_contract(paper_command(execution_mode="auto"))
    with pytest.raises(AirGapViolation, match="paper-only assertion"):
        validate_paper_contract(paper_command(paper_trading_only=False))


def test_secret_material_is_detected_in_values_and_free_text():
    with pytest.raises(SecretMaterialDetected):
        validate_paper_contract(
            paper_command(notes="Authorization: Bearer super-secret-token-value")
        )
    with pytest.raises(SecretMaterialDetected):
        scan_text_for_secrets("-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----")
    with pytest.raises(SecretMaterialDetected):
        scan_text_for_secrets("api_key=1234567890abcdef")


def test_pre_egress_redaction_removes_explicit_and_pattern_secrets():
    output = redact_for_egress(
        "contact token-value and Authorization: Bearer abcdefghijklmnop",
        secret_values=("token-value",),
    )
    assert "token-value" not in output
    assert "Bearer abcdefghijklmnop" not in output
    assert output.count("[REDACTED_SECRET]") == 2


def test_tool_allowlist_denies_private_live_withdrawal_production_billing_signing_and_shell():
    allowlist = ToolAllowlist()
    assert allowlist.require("market.read_public") == "market.read_public"
    assert allowlist.require("paper.execute_validated") == "paper.execute_validated"

    for tool in (
        "exchange.private.place_order",
        "exchange.live.place_order",
        "wallet.withdraw.usdt",
        "production.deploy.release",
        "billing.change_plan",
        "signing.sign_release",
        "shell.exec",
    ):
        with pytest.raises(ToolDenied):
            allowlist.require(tool)

    with pytest.raises(ToolDenied, match="not explicitly allowlisted"):
        allowlist.require("network.post_arbitrary")


def test_forbidden_tool_cannot_be_smuggled_into_custom_allowlist():
    with pytest.raises(ToolDenied, match="cannot be allowlisted"):
        ToolAllowlist({"paper.execute_validated", "exchange.live.place_order"})


def test_independent_gate_cannot_be_disabled_by_upstream_policy_or_self_attestation():
    with pytest.raises(IndependentSafetyGateFailure, match="disabled"):
        independent_airgap_check(
            contract=paper_command(),
            tool="paper.execute_validated",
            trusted_gate_enabled=False,
        )

    unsafe = paper_command()
    unsafe["upstream_policy_says_allowed"] = True
    unsafe["live_order"] = True
    with pytest.raises(AirGapViolation, match="forbidden"):
        independent_airgap_check(contract=unsafe, tool="paper.execute_validated")


def test_bounded_parser_rejects_excessive_depth_and_binary_floats():
    value = paper_command()
    nested = value
    for index in range(12):
        child = {f"level_{index}": {}}
        nested["child"] = child
        nested = child[f"level_{index}"]
    with pytest.raises(AirGapViolation, match="nesting depth"):
        validate_paper_contract(value)

    with pytest.raises(AirGapViolation, match="binary floating point"):
        validate_paper_contract(paper_command(quantity=0.01))


def test_unknown_objects_and_secret_like_keys_are_rejected():
    class Unknown:
        pass

    with pytest.raises(AirGapViolation, match="unsupported"):
        validate_paper_contract(paper_command(extra=Unknown()))

    contract = paper_command()
    contract["provider_credential_bundle"] = {"opaque": "x"}
    with pytest.raises(AirGapViolation, match="forbidden"):
        validate_paper_contract(contract)
