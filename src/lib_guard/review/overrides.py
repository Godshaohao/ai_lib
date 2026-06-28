from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping
import json
import os
import tempfile

from .io import utc_now


ALLOWED_DECISIONS = {"accepted", "waived", "needs_info", "rejected", "revoked"}
CLOSING_DECISIONS = {"accepted", "waived"}
BLOCKING_DECISIONS = {"needs_info", "rejected"}


def read_review_overrides(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {"schema_version": "review_overrides.v1", "items": {}}
    p = Path(path)
    if not p.exists():
        return {"schema_version": "review_overrides.v1", "items": {}}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"schema_version": "review_overrides.v1", "items": {}}
    if not isinstance(data, dict):
        return {"schema_version": "review_overrides.v1", "items": {}}
    data.setdefault("schema_version", "review_overrides.v1")
    data.setdefault("items", {})
    return data


def _atomic_write_json(path: Path, data: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp_name, path)
    finally:
        try:
            if os.path.exists(tmp_name):
                os.remove(tmp_name)
        except OSError:
            pass


def write_review_override(
    path: str | Path,
    *,
    library: str,
    version: str,
    item_id: str,
    decision: str,
    by: str,
    reason: str,
    gate: str = "current",
) -> dict[str, Any]:
    decision = str(decision or "").strip().lower()
    if decision not in ALLOWED_DECISIONS:
        raise ValueError(f"unsupported review decision: {decision}")
    if not str(item_id or "").strip():
        raise ValueError("review override item_id is required")
    if decision != "revoked" and not str(reason or "").strip():
        raise ValueError("review override reason is required")
    if decision != "revoked" and not str(by or "").strip():
        raise ValueError("review override by is required")

    p = Path(path)
    data = read_review_overrides(p)
    data["library"] = library
    data["version"] = version
    data["updated_at"] = utc_now()
    items = data.setdefault("items", {})
    items[str(item_id)] = {
        "decision": decision,
        "by": by,
        "reason": reason,
        "gate": gate,
        "created_at": utc_now(),
    }
    _atomic_write_json(p, data)
    return data


def apply_overrides_to_gate(gate: Mapping[str, Any], overrides: Mapping[str, Any] | None) -> dict[str, Any]:
    result = dict(gate)
    override_items = (overrides or {}).get("items") if isinstance(overrides, Mapping) else {}
    override_items = override_items if isinstance(override_items, Mapping) else {}

    open_items: list[dict[str, Any]] = []
    accepted_items: list[dict[str, Any]] = []
    waived_items: list[dict[str, Any]] = []
    forced_blockers: list[dict[str, Any]] = []

    for item in result.get("blocking_items", []) or []:
        row = dict(item)
        override = override_items.get(str(row.get("id") or ""))
        if isinstance(override, Mapping):
            decision = str(override.get("decision") or "").lower()
            row["decision"] = decision
            row["decision_by"] = override.get("by")
            row["decision_reason"] = override.get("reason")
            row["decision_at"] = override.get("created_at")
            if decision in CLOSING_DECISIONS:
                if decision == "accepted":
                    accepted_items.append(row)
                else:
                    waived_items.append(row)
                continue
            if decision in BLOCKING_DECISIONS:
                row["blocking"] = True
        open_items.append(row)

    existing_ids = {str(item.get("id") or "") for item in open_items + accepted_items + waived_items}
    for item_id, override in override_items.items():
        if str(item_id) in existing_ids or not isinstance(override, Mapping):
            continue
        decision = str(override.get("decision") or "").lower()
        if decision not in BLOCKING_DECISIONS:
            continue
        forced_blockers.append(
            {
                "id": str(item_id),
                "severity": "blocker",
                "category": "manual_review",
                "title": f"Manual review marked {decision}",
                "message": str(override.get("reason") or ""),
                "blocking": True,
                "decision": decision,
                "decision_by": override.get("by"),
                "decision_reason": override.get("reason"),
                "decision_at": override.get("created_at"),
            }
        )

    open_items.extend(forced_blockers)
    result["blocking_items"] = open_items
    result["accepted_items"] = accepted_items
    result["waived_items"] = waived_items
    result["blocking_open"] = len(open_items)
    if result["blocking_open"]:
        result["status"] = "BLOCKED" if any(item.get("fatal") for item in open_items) else "REVIEW_REQUIRED"
    elif result.get("attention_items"):
        result["status"] = "ATTENTION"
    else:
        result["status"] = "READY"
    return result
