from copy import deepcopy

import pytest

from versioned_registries import (
    GENESIS_DIGEST,
    REGISTRY_TYPES,
    RegistryError,
    build_registry,
    select_entry,
    validate_registry,
    validate_registry_set,
    validate_transition,
)


def entry(identifier="alpha", version="1.0.0", authority="observe", enabled=True, **config):
    return {
        "id": identifier,
        "version": version,
        "enabled": enabled,
        "authority": authority,
        "config": config or {"mode": "paper"},
    }


def registry(kind="strategies", version="1.0.0", entries=None, previous=GENESIS_DIGEST, status="active"):
    return build_registry(
        registry_type=kind,
        registry_version=version,
        entries=entries or [entry()],
        previous_digest=previous,
        status=status,
    )


def test_registry_digest_is_deterministic_and_entries_are_sorted():
    first = registry(entries=[entry("zeta"), entry("alpha")])
    second = registry(entries=[entry("alpha"), entry("zeta")])
    assert first == second
    assert [item["id"] for item in first["entries"]] == ["alpha", "zeta"]
    assert validate_registry(first) == first


def test_complete_registry_set_requires_every_frozen_gate_type():
    registries = [registry(kind=kind) for kind in sorted(REGISTRY_TYPES)]
    result = validate_registry_set(registries)
    assert set(result) == REGISTRY_TYPES

    with pytest.raises(RegistryError, match="missing required"):
        validate_registry_set(registries[:-1])
    with pytest.raises(RegistryError, match="duplicate registry type"):
        validate_registry_set(registries + [registries[0]])


def test_exact_version_selection_returns_provenance_bound_contract():
    built = registry(entries=[entry("alpha", "1.0.0", leverage="1"), entry("alpha", "1.1.0", leverage="2")])
    selected = select_entry(built, "alpha", "1.1.0")
    assert selected.registry_type == "strategies"
    assert selected.registry_version == "1.0.0"
    assert selected.entry_version == "1.1.0"
    assert selected.config == {"leverage": "2"}
    assert selected.registry_digest == built["registry_digest"]


def test_disabled_or_suspended_contracts_fail_closed():
    disabled = registry(entries=[entry(enabled=False)])
    with pytest.raises(RegistryError, match="disabled"):
        select_entry(disabled, "alpha", "1.0.0")
    suspended = registry(status="suspended")
    with pytest.raises(RegistryError, match="not active"):
        select_entry(suspended, "alpha", "1.0.0")


def test_transition_requires_monotonic_version_and_digest_chain():
    old = registry()
    new = registry(
        version="1.1.0",
        entries=[entry(version="1.1.0", risk="bounded")],
        previous=old["registry_digest"],
    )
    assert validate_transition(old, new) == new

    wrong_chain = registry(version="1.1.0", entries=[entry(version="1.1.0")])
    with pytest.raises(RegistryError, match="digest chain"):
        validate_transition(old, wrong_chain)

    same_version = registry(version="1.0.0", entries=[entry(version="1.1.0")], previous=old["registry_digest"])
    with pytest.raises(RegistryError, match="must increase"):
        validate_transition(old, same_version)


def test_unversioned_mutation_and_downgrade_are_rejected():
    old = registry(entries=[entry(version="2.0.0", limit="1")])
    mutated = registry(
        version="2.1.0",
        entries=[entry(version="2.0.0", limit="2")],
        previous=old["registry_digest"],
    )
    with pytest.raises(RegistryError, match="mutable configuration"):
        validate_transition(old, mutated)

    downgraded = registry(
        version="2.1.0",
        entries=[entry(version="1.9.0", limit="1")],
        previous=old["registry_digest"],
    )
    with pytest.raises(RegistryError, match="downgrade"):
        validate_transition(old, downgraded)


def test_authority_cannot_self_promote_through_configuration():
    old = registry(entries=[entry(authority="observe")])
    promoted = registry(
        version="1.1.0",
        entries=[entry(version="1.1.0", authority="bounded_execute")],
        previous=old["registry_digest"],
    )
    with pytest.raises(RegistryError, match="authority escalation"):
        validate_transition(old, promoted)


@pytest.mark.parametrize("key", ["api_key", "live_order_route", "production_target", "billing_plan", "signing_key"])
def test_sensitive_or_stronger_authority_fields_are_rejected(key):
    with pytest.raises(RegistryError, match="forbidden"):
        registry(entries=[entry(**{key: "forbidden"})])


def test_unknown_fields_tamper_and_invalid_versions_are_rejected():
    built = registry()
    tampered = deepcopy(built)
    tampered["entries"][0]["config"]["mode"] = "changed"
    with pytest.raises(RegistryError, match="digest"):
        validate_registry(tampered)

    unknown = deepcopy(built)
    unknown["extra"] = True
    with pytest.raises(RegistryError, match="schema mismatch"):
        validate_registry(unknown)

    with pytest.raises(RegistryError, match="semantic versioning"):
        registry(version="latest")
    with pytest.raises(RegistryError, match="unknown registry type"):
        registry(kind="secrets")


def test_exact_version_is_required_no_implicit_latest_fallback():
    built = registry(entries=[entry(version="1.0.0"), entry(version="2.0.0")])
    with pytest.raises(RegistryError, match="exact registry entry version not found"):
        select_entry(built, "alpha", "3.0.0")
