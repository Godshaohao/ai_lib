from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
import json


DEFAULT_REQUIRED_VIEWS = {
    "ip": ["verilog"],
    "digital_ip": ["verilog", "lef", "liberty"],
    "hard_ip": ["lef", "gds", "liberty", "verilog", "cdl"],
    "phy": ["lef", "gds", "liberty", "verilog", "cdl"],
    "stdcell": ["liberty", "db", "lef", "gds", "verilog", "cdl"],
    "sram": ["liberty", "db", "lef", "gds", "verilog", "cdl"],
    "memory": ["liberty", "db", "lef", "gds", "verilog", "cdl"],
    "io": ["liberty", "db", "lef", "gds", "verilog", "cdl"],
    "pad": ["liberty", "db", "lef", "gds", "verilog", "cdl"],
    "package": ["ibis", "touchstone"],
    "doc": ["doc"],
}

DEFAULT_OPTIONAL_VIEWS = {
    "ip": ["cdl", "db", "sdc", "upf", "sdf", "flow_config", "tech_config", "waiver", "doc"],
    "hard_ip": ["sdc", "upf", "sdf", "spef", "db", "ibis", "package", "flow_config", "tech_config", "waiver", "doc"],
    "stdcell": ["flow_config", "tech_config", "doc", "waiver"],
    "sram": ["sdf", "flow_config", "tech_config", "doc", "waiver"],
    "package": ["pwl", "spice", "doc"],
}

DEFAULT_VALIDATION_LEVELS = {
    "lef": "parsed_required",
    "liberty": "parsed_required",
    "verilog": "metadata_required",
    "systemverilog": "metadata_required",
    "cdl": "parsed_required",
    "spice": "parsed_required",
    "sdc": "parsed_required",
    "upf": "parsed_required",
    "cpf": "parsed_required",
    "sdf": "parsed_preferred",
    "spef": "parsed_preferred",
    "ibis": "parsed_preferred",
    "touchstone": "parsed_preferred",
    "pwl": "parsed_preferred",
    "package": "parsed_preferred",
    "flow_config": "manual_review",
    "tech_config": "manual_review",
    "waiver": "parsed_preferred",
    "db": "metadata_required",
    "gds": "metadata_required",
    "oas": "metadata_required",
    "ndm": "metadata_required",
    "milkyway": "metadata_required",
    "doc": "doc_review_required",
    "unknown": "pass_through_allowed",
}

LEVEL_ORDER = {"L0": 0, "L1": 1, "L2": 2}
ALIAS_REQUIRED_LEVEL = {"stage": "L0", "current": "L1", "approved": "L2"}


def utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")


def read_json(path: str | Path, default: Any = None) -> Any:
    p = Path(path)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: str | Path, data: Any) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")


def load_release_policy(policy_path: str | Path | Mapping[str, Any] | None = None) -> dict[str, Any]:
    if isinstance(policy_path, Mapping):
        policy = dict(policy_path)
    else:
        policy = read_json(policy_path, default={}) if policy_path else {}
    policy = dict(policy or {})
    if "required_file_types" in policy and "required_views" not in policy:
        policy["required_views"] = policy["required_file_types"]
    policy.setdefault("required_views", DEFAULT_REQUIRED_VIEWS)
    policy.setdefault("optional_views", DEFAULT_OPTIONAL_VIEWS)
    policy.setdefault("validation_levels", DEFAULT_VALIDATION_LEVELS)
    policy.setdefault("required_docs", ["readme", "release_note"])
    policy.setdefault(
        "alias_gate",
        {
            "stage": {"required_release_level": "L0", "allow_warning": True, "require_diff": False},
            "current": {"required_release_level": "L1", "allow_warning": True, "require_diff": True},
            "approved": {"required_release_level": "L2", "allow_warning": False, "require_p2_deep_diff": True, "require_manual_review_closed": True},
        },
    )
    policy.setdefault(
        "doc_policy",
        {
            "always_parse": True,
            "l0_missing_doc_severity": "warning",
            "l1_missing_release_note_severity": "error",
            "l2_missing_release_note_severity": "blocker",
            "require_hotfix_release_note": True,
        },
    )
    return policy


def build_release_readiness(scan_dir: str | Path, policy_path: str | Path | Mapping[str, Any] | None = None) -> dict[str, Any]:
    scan = Path(scan_dir)
    policy = load_release_policy(policy_path)
    scan_meta = read_json(scan / "scan_meta.json", default={}) or {}
    inventory = read_json(scan / "file_inventory.json", default={"files": []}) or {"files": []}
    parser_manifest = read_json(scan / "parser_manifest.json", default={"files": []}) or {"files": []}
    parser_quality = read_json(scan / "summary" / "parser_quality.json", default={}) or {}
    scan_issues = read_json(scan / "scan_issues.json", default={"issues": []}) or {"issues": []}

    files = list(inventory.get("files") or [])
    file_types = Counter(str(item.get("file_type", "unknown")) for item in files)
    library_type = str(scan_meta.get("library_type") or "unknown")
    component_id = str(scan_meta.get("library_id") or f"{library_type}/{scan_meta.get('library_name', 'unknown')}/{scan_meta.get('release_version', 'unknown')}")

    required_views = list((policy.get("required_views") or {}).get(library_type, []))
    optional_views = list((policy.get("optional_views") or {}).get(library_type, []))
    validation_levels = dict(policy.get("validation_levels") or DEFAULT_VALIDATION_LEVELS)
    parser_by_type = _parser_status_by_type(parser_manifest)
    quality_by_type = _quality_by_type(parser_quality)

    blocking_items: list[dict[str, Any]] = []
    warning_items: list[dict[str, Any]] = []
    manual_review_items: list[dict[str, Any]] = []
    required_view_results: dict[str, dict[str, Any]] = {}

    for view in required_views:
        result = _validate_view(view, required=True, file_types=file_types, parser_by_type=parser_by_type, validation_levels=validation_levels)
        required_view_results[view] = result
        if result["status"] == "BLOCK":
            item = _item("blocker", "required_view", f"Required view blocked: {view}", result["message"], view)
            blocking_items.append(item)
            if result.get("parser_status") == "PASS_EMPTY":
                manual_review_items.append(_manual_review("required_view_pass_empty", component_id, view, result.get("files", []), "Required parsed view returned PASS_EMPTY."))
        elif result["status"] == "WARNING":
            warning_items.append(_item("warning", "required_view", f"Required view warning: {view}", result["message"], view))

    optional_view_results: dict[str, dict[str, Any]] = {}
    for view in optional_views:
        optional_view_results[view] = _validate_view(view, required=False, file_types=file_types, parser_by_type=parser_by_type, validation_levels=validation_levels)

    for file_type in sorted(file_types):
        level = validation_levels.get(file_type, "pass_through_allowed")
        if level == "metadata_required":
            manual_review_items.append(_manual_review("metadata_only_ack", component_id, file_type, _files_for_type(files, file_type), "Metadata-only release channel requires acknowledgement."))
        elif level == "manual_review":
            manual_review_items.append(_manual_review("manual_view_review", component_id, file_type, _files_for_type(files, file_type), "Flow/technology setup files require manual approval."))
        elif level == "pass_through_allowed":
            manual_review_items.append(_manual_review("pass_through_approval", component_id, file_type, _files_for_type(files, file_type), "Pass-through files require manual approval."))
            warning_items.append(_item("warning", "pass_through", f"Pass-through file type: {file_type}", "File type is not automatically validated.", file_type))

    component_status = _rollup_status(blocking_items, warning_items, scan_issues)
    release_channel = _release_channel(component_status, file_types, validation_levels, manual_review_items)
    doc_summary = _doc_summary(files, scan_meta)
    required_view_status = _required_view_status(required_view_results)
    release_level_candidate = _release_level_candidate(scan_meta, component_status, parser_quality, required_view_status)
    allowed_aliases, blocked_aliases = _aliases_for_level(release_level_candidate, policy)
    limitations = _limitations_for_level(release_level_candidate, doc_summary, required_view_status)
    component = {
        "component_id": component_id,
        "component_type": library_type,
        "library_type": library_type,
        "component_name": scan_meta.get("library_name"),
        "version": scan_meta.get("release_version"),
        "root_path": scan_meta.get("root_path"),
        "required_views": required_views,
        "optional_views": optional_views,
        "required_view_results": required_view_results,
        "optional_view_results": optional_view_results,
        "validation_status": component_status,
        "release_channel": release_channel,
        "parser_quality": quality_by_type,
        "issues": blocking_items + warning_items,
        "manual_review_items": manual_review_items,
    }

    bundle_status = component_status
    components = [component]
    readiness = {
        "schema_version": "1.0",
        "generated_at": utc_now(),
        "bundle_id": component_id,
        "project": scan_meta.get("project") or scan_meta.get("library_name"),
        "release_version": scan_meta.get("release_version"),
        "scan_id": scan_meta.get("scan_id"),
        "bundle_status": bundle_status,
        "release_channel": release_channel if bundle_status != "BLOCK" else "blocked",
        "release_level_candidate": release_level_candidate,
        "validation_depth": {"L0": "inventory", "L1": "readiness", "L2": "verified"}.get(release_level_candidate, "inventory"),
        "doc_parse_status": "PASS" if doc_summary.get("doc_count", 0) > 0 else "WARNING",
        "doc_summary": doc_summary,
        "required_view_status": required_view_status,
        "diff_level": "NONE",
        "deep_diff_completed": False,
        "allowed_aliases": allowed_aliases,
        "blocked_aliases": blocked_aliases,
        "limitations": limitations,
        "components": components,
        "bundle_docs": _bundle_docs(files),
        "manual_review_items": manual_review_items,
        "blocking_items": blocking_items,
        "warning_items": warning_items,
        "recommended_actions": _recommended_actions(component_id, blocking_items, warning_items),
        "summary": {
            "total_components": len(components),
            "passed_components": len([c for c in components if c["validation_status"] == "PASS"]),
            "warning_components": len([c for c in components if c["validation_status"] == "PASS_WITH_WARNING"]),
            "blocked_components": len([c for c in components if c["validation_status"] == "BLOCK"]),
            "manual_review_count": len(manual_review_items),
        },
        "validation_levels": validation_levels,
    }
    return readiness


def _parser_status_by_type(parser_manifest: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for file_entry in parser_manifest.get("files", []) or []:
        file_type = str(file_entry.get("file_type", "unknown"))
        for task in file_entry.get("parser_tasks", []) or []:
            if not task.get("parser_name"):
                continue
            out.setdefault(file_type, []).append({**task, "file": file_entry.get("file")})
    return out


def _quality_by_type(parser_quality: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for item in parser_quality.get("parsers", []) or []:
        file_types = item.get("file_types") or [item.get("file_type")]
        for file_type in file_types:
            if file_type:
                out[str(file_type)] = item
    return out


def _validate_view(
    view: str,
    *,
    required: bool,
    file_types: Counter,
    parser_by_type: dict[str, list[dict[str, Any]]],
    validation_levels: dict[str, str],
) -> dict[str, Any]:
    level = validation_levels.get(view, "pass_through_allowed")
    found = file_types.get(view, 0) > 0
    tasks = parser_by_type.get(view, [])
    parser_statuses = [str(t.get("result_status", t.get("status", "UNKNOWN"))).upper() for t in tasks]
    worst_status = _worst_parser_status(parser_statuses)
    files = [str(t.get("file")) for t in tasks if t.get("file")]

    if not found:
        return {"view": view, "found": False, "validation_level": level, "parser_status": None, "status": "BLOCK" if required else "INFO", "message": "Required view missing." if required else "Optional view missing.", "files": []}
    if level == "metadata_required":
        return {"view": view, "found": True, "validation_level": level, "parser_status": "METADATA_ONLY", "status": "PASS", "message": "Metadata recorded; deep parser is not required.", "files": files}
    if level == "doc_review_required":
        return {"view": view, "found": True, "validation_level": level, "parser_status": "DOC_REVIEW", "status": "WARNING" if required else "INFO", "message": "Document requires manual review.", "files": files}
    if level == "manual_review":
        return {"view": view, "found": True, "validation_level": level, "parser_status": "MANUAL_REVIEW", "status": "WARNING", "message": "Flow/technology setup requires manual review.", "files": files}
    if level == "pass_through_allowed":
        return {"view": view, "found": True, "validation_level": level, "parser_status": "PASS_THROUGH", "status": "WARNING", "message": "Pass-through file requires manual approval.", "files": files}
    if worst_status in {"FAILED", "PASS_EMPTY"}:
        return {"view": view, "found": True, "validation_level": level, "parser_status": worst_status, "status": "BLOCK" if required and level == "parsed_required" else "WARNING", "message": f"Parser status is {worst_status}.", "files": files}
    return {"view": view, "found": True, "validation_level": level, "parser_status": worst_status or "PASS", "status": "PASS", "message": "View validated.", "files": files}


def _worst_parser_status(statuses: list[str]) -> str | None:
    order = ["FAILED", "PASS_EMPTY", "UNSUPPORTED", "SKIPPED", "METADATA_ONLY", "PASS"]
    for status in order:
        if status in statuses:
            return status
    return statuses[0] if statuses else None


def _rollup_status(blocking_items: list[dict[str, Any]], warning_items: list[dict[str, Any]], scan_issues: Mapping[str, Any]) -> str:
    if blocking_items:
        return "BLOCK"
    if any(str(i.get("severity", "")).lower() in {"error", "blocker"} for i in scan_issues.get("issues", []) or []):
        return "FAILED"
    if warning_items:
        return "PASS_WITH_WARNING"
    return "PASS"


def _release_channel(status: str, file_types: Counter, validation_levels: dict[str, str], manual_review_items: list[dict[str, Any]]) -> str:
    if status == "BLOCK":
        return "blocked"
    levels = {validation_levels.get(ft, "pass_through_allowed") for ft in file_types}
    if "pass_through_allowed" in levels:
        return "pass_through"
    if levels and levels.issubset({"metadata_required", "doc_review_required"}):
        return "metadata_only"
    if manual_review_items:
        return "pass_through"
    return "verified"


def _files_for_type(files: list[Mapping[str, Any]], file_type: str) -> list[str]:
    return [str(f.get("path")) for f in files if str(f.get("file_type")) == file_type]


def _bundle_docs(files: list[Mapping[str, Any]]) -> dict[str, Any]:
    docs = [f for f in files if str(f.get("file_type")) == "doc" or f.get("is_key_doc")]
    roles = Counter(str(f.get("doc_type") or f.get("role") or "doc") for f in docs)
    return {"doc_count": len(docs), "roles": dict(sorted(roles.items())), "files": docs[:100]}


def _doc_summary(files: list[Mapping[str, Any]], scan_meta: Mapping[str, Any]) -> dict[str, Any]:
    docs = [f for f in files if str(f.get("file_type")) == "doc" or f.get("is_key_doc")]
    roles = {str(f.get("doc_type") or f.get("role") or "doc") for f in docs}
    lowered = [" ".join(str(f.get(k, "")) for k in ["path", "abs_path", "name", "role", "doc_type"]).lower() for f in docs]

    def has_role(*names: str) -> bool:
        return bool(roles.intersection(names)) or any(any(name in text for name in names) for text in lowered)

    version = str(scan_meta.get("release_version") or scan_meta.get("version") or "")
    version_match = True
    if version and docs:
        version_match = any(version.lower() in text for text in lowered) or len(docs) > 0
    return {
        "doc_count": len(docs),
        "readme_found": has_role("readme"),
        "release_note_found": has_role("release_note", "release note", "releasenote"),
        "changelog_found": has_role("changelog", "change_log", "change log", "update_note"),
        "integration_guide_found": has_role("integration_guide", "integration", "guide"),
        "waiver_found": has_role("waiver"),
        "known_issue_found": has_role("known_issue", "known issue", "errata"),
        "delivery_note_found": has_role("delivery_note", "delivery note"),
        "version_note_found": has_role("version_note", "version note"),
        "version_match": version_match,
        "files": docs[:100],
    }


def _required_view_status(required_view_results: Mapping[str, Mapping[str, Any]]) -> str:
    statuses = {str(item.get("status")) for item in required_view_results.values()}
    if "BLOCK" in statuses:
        return "BLOCK"
    if "WARNING" in statuses:
        return "WARNING"
    return "PASS"


def _release_level_candidate(
    scan_meta: Mapping[str, Any],
    component_status: str,
    parser_quality: Mapping[str, Any],
    required_view_status: str,
) -> str:
    mode = str(scan_meta.get("scan_mode") or "inventory")
    if mode in {"quick", "inventory"}:
        return "L0"
    if component_status in {"BLOCK", "FAILED"} or required_view_status == "BLOCK":
        return "L0"
    if parser_quality.get("parsers") is not None:
        return "L1"
    return "L0"


def _aliases_for_level(level: str, policy: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    alias_gate = policy.get("alias_gate") or {}
    allowed: list[str] = []
    blocked: list[str] = []
    actual = LEVEL_ORDER.get(level, 0)
    for alias in ["stage", "current", "approved"]:
        required = (alias_gate.get(alias) or {}).get("required_release_level") or ALIAS_REQUIRED_LEVEL[alias]
        (allowed if actual >= LEVEL_ORDER.get(required, 0) else blocked).append(alias)
    return allowed, blocked


def _limitations_for_level(level: str, doc_summary: Mapping[str, Any], required_view_status: str) -> list[str]:
    limitations: list[str] = []
    if level == "L0":
        limitations.append("Content parser validation not completed")
    if level in {"L0", "L1"}:
        limitations.append("P2 deep diff not completed")
    if required_view_status != "PASS":
        limitations.append(f"Required view status is {required_view_status}")
    if not doc_summary.get("release_note_found"):
        limitations.append("Release note not found")
    return limitations


def _item(severity: str, category: str, title: str, message: str, file_type: str) -> dict[str, Any]:
    return {"severity": severity, "category": category, "title": title, "message": message, "file_type": file_type}


def _manual_review(scope: str, component_id: str, file_type: str, files: list[str], reason: str) -> dict[str, Any]:
    return {
        "review_id": f"MR-{abs(hash((scope, component_id, file_type))) % 1000000:06d}",
        "approval_scope": scope,
        "component_id": component_id,
        "file_type": file_type,
        "files": files[:20],
        "reason": reason,
        "risk_level": "medium" if scope != "required_view_pass_empty" else "high",
        "allowed_release_channel": "staging" if scope != "metadata_only_ack" else "metadata_only",
    }


def _recommended_actions(component_id: str, blocking_items: list[dict[str, Any]], warning_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    actions = []
    for item in blocking_items:
        actions.append({"title": item["title"], "component_id": component_id, "command": f"lib_guard update type --library-id {component_id} --type {item.get('file_type')} --scope parser-summary --skip-cache"})
    for item in warning_items:
        actions.append({"title": item["title"], "component_id": component_id, "command": f"lib_guard console review --library-id {component_id} --latest"})
    return actions
