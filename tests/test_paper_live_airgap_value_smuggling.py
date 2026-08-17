from __future__ import annotations

import pytest

from paper_live_airgap import AirGapViolation, independent_airgap_check, validate_paper_contract


def paper_contract(**changes):
    contract = {
        "operation": "open",
        "symbol": "BTCUSDT",
        "execution_mode": "paper",
        "paper_trading_only": True,
    }
    contract.update(changes)
    return contract


@pytest.mark.parametrize(
    "smuggled",
    [
        "exchange.live.place_order",
        "exchange.private.place_order",
        "wallet.withdraw.usdt",
        "production.deploy.release",
        "billing.change_plan",
        "signing.sign_release",
        "shell.exec",
        "live_order",
        "real_order",
        "live_trading",
        "withdrawal",
        "production_deployment",
        "billing_authority",
        "signing_authority",
    ],
)
def test_sensitive_authority_values_fail_closed_under_benign_keys(smuggled: str) -> None:
    contract = paper_contract(metadata={"requested_route": smuggled})
    with pytest.raises(AirGapViolation, match="forbidden authority"):
        validate_paper_contract(contract)
    with pytest.raises(AirGapViolation, match="forbidden authority"):
        independent_airgap_check(contract=contract, tool="paper.execute_validated")


def test_benign_paper_and_public_values_still_pass() -> None:
    contract = paper_contract(metadata={"requested_route": "market.read_public"})
    assert validate_paper_contract(contract).paper_only is True
    assert independent_airgap_check(
        contract=contract, tool="paper.execute_validated"
    ) == "independent_paper_airgap_pass"
