from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping


def canonical_digest(value: Any) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def build_snapshot_identity(
    *,
    input_fingerprint: Mapping[str, Any],
    policy_identity: Mapping[str, Any],
    tool_version: str,
    strength: str,
) -> dict[str, Any]:
    payload = {
        "input_fingerprint": dict(input_fingerprint),
        "policy": dict(policy_identity),
        "tool_version": tool_version,
    }
    return {
        "schema_version": "delivery_snapshot_identity.v1",
        "digest": canonical_digest(payload),
        "strength": strength,
        "payload": payload,
    }


def build_diff_identity(old_digest: str, new_digest: str, policy_version: str) -> dict[str, Any]:
    payload = {
        "old_snapshot_digest": old_digest,
        "new_snapshot_digest": new_digest,
        "policy_version": policy_version,
    }
    return {
        "schema_version": "diff_identity.v1",
        "digest": canonical_digest(payload),
        **payload,
    }


def build_effective_identity(manifest: Mapping[str, Any]) -> dict[str, Any]:
    components = [
        {
            key: item.get(key)
            for key in (
                "role",
                "version_id",
                "snapshot_digest",
                "evidence_strength",
                "scope",
                "order",
            )
        }
        for item in manifest.get("components", []) or []
    ]
    payload = {
        "library_id": manifest.get("library_id"),
        "base_full_version": manifest.get("base_full_version"),
        "components": components,
        "tombstones": sorted((manifest.get("tombstones") or {}).keys()),
        "resolver_version": "effective.v1",
    }
    return {
        "schema_version": "effective_identity.v1",
        "digest": canonical_digest(payload),
        "payload": payload,
    }
