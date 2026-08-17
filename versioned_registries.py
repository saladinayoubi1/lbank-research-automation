from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

REGISTRY_SCHEMA_VERSION = "nexus.registry.v1"
GENESIS_DIGEST = "0" * 64
REGISTRY_TYPES = {
    "strategies",
    "datasets",
    "risk_policies",
    "ai_providers",
    "agent_capabilities",
    "feature_flags",
    "api_compatibility",
    "experiments",
}
AUTHORITY_LEVELS = {"observe": 0, "propose": 1, "bounded_execute": 2}
FORBIDDEN_TERMS = {
    "api_key", "api_secret", "credential", "private_key", "withdrawal",
    "live_order", "production", "billing", "signing",
}
ROOT_KEYS = {
    "schema_version", "registry_type", "registry_version", "status",
    "previous_digest", "entries", "registry_digest",
}
ENTRY_KEYS = {"id", "version", "enabled", "authority", "config"}
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


class RegistryError(ValueError):
    pass


@dataclass(frozen=True)
class RegistrySelection:
    registry_type: str
    registry_version: str
    entry_id: str
    entry_version: str
    authority: str
    config: Mapping[str, Any]
    registry_digest: str


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise RegistryError("registry is not canonically serializable") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 128:
        raise RegistryError(f"{field} must be a non-empty bounded string")
    return value


def _version(value: Any, field: str) -> str:
    if not isinstance(value, str) or SEMVER.fullmatch(value) is None:
        raise RegistryError(f"{field} must use semantic versioning")
    return value


def _version_tuple(value: str) -> tuple[int, int, int]:
    return tuple(int(part) for part in value.split("."))


def _reject_forbidden(value: Any, path: str = "registry") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).lower()
            if any(term in normalized for term in FORBIDDEN_TERMS):
                raise RegistryError(f"{path}.{key} is forbidden")
            _reject_forbidden(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_forbidden(child, f"{path}[{index}]")


def _normalize_entry(entry: Any) -> dict[str, Any]:
    if not isinstance(entry, dict) or set(entry) != ENTRY_KEYS:
        raise RegistryError("registry entry schema mismatch")
    entry_id = _identifier(entry["id"], "entry.id")
    entry_version = _version(entry["version"], "entry.version")
    if not isinstance(entry["enabled"], bool):
        raise RegistryError("entry.enabled must be boolean")
    if entry["authority"] not in AUTHORITY_LEVELS:
        raise RegistryError("entry.authority exceeds bounded paper authority")
    if not isinstance(entry["config"], dict):
        raise RegistryError("entry.config must be an object")
    _reject_forbidden(entry["config"], f"entry[{entry_id}].config")
    _canonical(entry["config"])
    return {
        "id": entry_id,
        "version": entry_version,
        "enabled": entry["enabled"],
        "authority": entry["authority"],
        "config": dict(entry["config"]),
    }


def build_registry(
    *,
    registry_type: str,
    registry_version: str,
    entries: Iterable[dict[str, Any]],
    previous_digest: str = GENESIS_DIGEST,
    status: str = "active",
) -> dict[str, Any]:
    if registry_type not in REGISTRY_TYPES:
        raise RegistryError("unknown registry type")
    _version(registry_version, "registry_version")
    if status not in {"draft", "active", "suspended"}:
        raise RegistryError("unsupported registry status")
    if not isinstance(previous_digest, str) or len(previous_digest) != 64:
        raise RegistryError("previous_digest must be a SHA-256 digest")
    try:
        int(previous_digest, 16)
    except ValueError as exc:
        raise RegistryError("previous_digest must be hexadecimal") from exc
    normalized = [_normalize_entry(entry) for entry in entries]
    identities = [(entry["id"], entry["version"]) for entry in normalized]
    if len(identities) != len(set(identities)):
        raise RegistryError("duplicate registry entry identity")
    normalized.sort(key=lambda item: (item["id"], _version_tuple(item["version"])))
    core = {
        "schema_version": REGISTRY_SCHEMA_VERSION,
        "registry_type": registry_type,
        "registry_version": registry_version,
        "status": status,
        "previous_digest": previous_digest,
        "entries": normalized,
    }
    return {**core, "registry_digest": _digest(core)}


def validate_registry(registry: Any) -> dict[str, Any]:
    if not isinstance(registry, dict) or set(registry) != ROOT_KEYS:
        raise RegistryError("registry envelope schema mismatch")
    if registry["schema_version"] != REGISTRY_SCHEMA_VERSION:
        raise RegistryError("unsupported registry schema")
    rebuilt = build_registry(
        registry_type=registry["registry_type"],
        registry_version=registry["registry_version"],
        entries=registry["entries"],
        previous_digest=registry["previous_digest"],
        status=registry["status"],
    )
    if rebuilt != registry:
        raise RegistryError("registry digest or canonical content mismatch")
    return rebuilt


def validate_registry_set(registries: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for registry in registries:
        validated = validate_registry(registry)
        kind = validated["registry_type"]
        if kind in result:
            raise RegistryError("duplicate registry type")
        result[kind] = validated
    missing = REGISTRY_TYPES - set(result)
    if missing:
        raise RegistryError(f"missing required registries: {sorted(missing)}")
    return result


def validate_transition(previous: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    old = validate_registry(previous)
    new = validate_registry(candidate)
    if old["registry_type"] != new["registry_type"]:
        raise RegistryError("registry type cannot change")
    if _version_tuple(new["registry_version"]) <= _version_tuple(old["registry_version"]):
        raise RegistryError("registry version must increase")
    if new["previous_digest"] != old["registry_digest"]:
        raise RegistryError("registry digest chain mismatch")

    old_entries = {entry["id"]: entry for entry in old["entries"]}
    for entry in new["entries"]:
        prior = old_entries.get(entry["id"])
        if prior is None:
            continue
        if _version_tuple(entry["version"]) < _version_tuple(prior["version"]):
            raise RegistryError("entry version downgrade")
        if (
            entry["version"] == prior["version"]
            and (
                entry["config"] != prior["config"]
                or entry["authority"] != prior["authority"]
                or entry["enabled"] != prior["enabled"]
            )
        ):
            raise RegistryError("mutable configuration requires a new entry version")
        if AUTHORITY_LEVELS[entry["authority"]] > AUTHORITY_LEVELS[prior["authority"]]:
            raise RegistryError("authority escalation requires separately governed policy")

    return new


def select_entry(registry: dict[str, Any], entry_id: str, entry_version: str) -> RegistrySelection:
    validated = validate_registry(registry)
    if validated["status"] != "active":
        raise RegistryError("registry is not active")
    for entry in validated["entries"]:
        if entry["id"] == entry_id and entry["version"] == entry_version:
            if not entry["enabled"]:
                raise RegistryError("registry entry is disabled")
            return RegistrySelection(
                registry_type=validated["registry_type"],
                registry_version=validated["registry_version"],
                entry_id=entry_id,
                entry_version=entry_version,
                authority=entry["authority"],
                config=dict(entry["config"]),
                registry_digest=validated["registry_digest"],
            )
    raise RegistryError("exact registry entry version not found")
