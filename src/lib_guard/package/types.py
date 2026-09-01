"""Canonical package type rules shared by catalog, window, review and CLI."""

from __future__ import annotations

from typing import Any, Mapping


PACKAGE_RULES_VERSION = "package_rules.v2"
FULL_PACKAGE_TYPES = frozenset({"FULL_PACKAGE"})
PARTIAL_PACKAGE_TYPES = frozenset({"PARTIAL_UPDATE", "HOTFIX"})
DOC_PACKAGE_TYPES = frozenset({"DOC_UPDATE", "DOC_ONLY"})
IGNORE_PACKAGE_TYPES = frozenset({"IGNORE"})
UNKNOWN_PACKAGE_TYPES = frozenset({"UNKNOWN_PACKAGE"})

_ALIASES = {
    "FULL": "FULL_PACKAGE",
    "BASE_FULL": "FULL_PACKAGE",
    "BASE": "FULL_PACKAGE",
    "COMPLETE": "FULL_PACKAGE",
    "FINAL": "FULL_PACKAGE",
    "STABLE": "FULL_PACKAGE",
    "INITIAL": "FULL_PACKAGE",
    "AD_HOC": "HOTFIX",
    "ADHOC": "HOTFIX",
    "FIX": "PARTIAL_UPDATE",
    "PARTIAL": "PARTIAL_UPDATE",
    "UPDATE": "PARTIAL_UPDATE",
    "DOC": "DOC_UPDATE",
    "UNKNOWN": "UNKNOWN_PACKAGE",
    "UNCLASSIFIED": "UNKNOWN_PACKAGE",
    "NEEDS_CONFIRM": "UNKNOWN_PACKAGE",
    "IGNORED": "IGNORE",
}


def normalize_package_type(value: Any) -> str:
    """Return one canonical package type; unknown values remain unknown."""

    text = str(value or "").strip().upper().replace("-", "_").replace(" ", "_")
    if not text:
        return "UNKNOWN_PACKAGE"
    if text in _ALIASES:
        return _ALIASES[text]
    if text in FULL_PACKAGE_TYPES | PARTIAL_PACKAGE_TYPES | DOC_PACKAGE_TYPES | IGNORE_PACKAGE_TYPES | UNKNOWN_PACKAGE_TYPES:
        return text
    return "UNKNOWN_PACKAGE"


def package_type_from_version(version: Mapping[str, Any]) -> str:
    """Read explicit package metadata, falling back to an explicit stage only."""

    return normalize_package_type(
        version.get("package_type")
        or version.get("delivery_type")
        or version.get("version_type")
        or version.get("stage")
    )


def package_kind(value: Any) -> str:
    """Map a canonical package type to the small set used by window resolution."""

    package_type = package_type_from_version(value) if isinstance(value, Mapping) else normalize_package_type(value)
    if package_type in FULL_PACKAGE_TYPES:
        return "FULL"
    if package_type in PARTIAL_PACKAGE_TYPES:
        return "FIX"
    if package_type in DOC_PACKAGE_TYPES:
        return "DOC"
    if package_type in IGNORE_PACKAGE_TYPES:
        return "IGNORE"
    return "UNKNOWN"


def is_full_package(value: Any) -> bool:
    return normalize_package_type(value) in FULL_PACKAGE_TYPES


def is_overlay_package(value: Any) -> bool:
    return normalize_package_type(value) in PARTIAL_PACKAGE_TYPES | DOC_PACKAGE_TYPES
