from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Mapping
import json

from lib_guard.project_config import canonical_view_type


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

DEFAULT_REQUIRED_MODES = {
    "ip": [],
    "digital_ip": [],
    "hard_ip": [],
    "phy": [],
    "stdcell": [],
    "sram": [],
    "memory": [],
    "io": [],
    "pad": [],
    "package": [],
    "doc": [],
}

DEFAULT_REQUIRED_CORNERS = {key: [] for key in DEFAULT_REQUIRED_MODES}

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
    return json.loads(p.read_text(encoding="utf-8"))


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
    policy.setdefault("required_modes", DEFAULT_REQUIRED_MODES)
    policy.setdefault("required_corners", DEFAULT_REQUIRED_CORNERS)
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
    required_modes = _requirement_list((policy.get("required_modes") or {}).get(library_type, []))
    required_corners = _requirement_list((policy.get("required_corners") or {}).get(library_type, []))
    validation_levels = dict(policy.get("validation_levels") or DEFAULT_VALIDATION_LEVELS)
    parser_by_file = _parser_tasks_by_file(parser_manifest)
    quality_by_type = _quality_by_type(parser_quality)

    blocking_items: list[dict[str, Any]] = []
    warning_items: list[dict[str, Any]] = []
    manual_review_items: list[dict[str, Any]] = []
    required_view_results: dict[str, dict[str, Any]] = {}

    for view in required_views:
        result = _validate_view(view, required=True, files=files, parser_by_file=parser_by_file, scan_dir=scan, validation_levels=validation_levels)
        required_view_results[view] = result
        if result["status"] == "BLOCK":
            item = _item("blocker", "required_view", f"必需视图阻塞：{view}", result["message"], view)
            blocking_items.append(item)
            if result.get("parser_status") == "PASS_EMPTY":
                manual_review_items.append(_manual_review("required_view_pass_empty", component_id, view, result.get("files", []), "必需视图解析结果为空，需要人工确认。"))
        elif result["status"] == "WARNING":
            warning_items.append(_item("warning", "required_view", f"必需视图提示：{view}", result["message"], view))

    delivery_requirements = _build_delivery_requirements(
        files,
        scan_meta,
        required_views=required_views,
        required_modes=required_modes,
        required_corners=required_corners,
        required_view_results=required_view_results,
    )
    for kind, result in (("mode", delivery_requirements["modes"]), ("corner", delivery_requirements["corners"])):
        if result["status"] == "BLOCK":
            for missing in result["missing"]:
                blocking_items.append(
                    _item(
                        "blocker",
                        f"required_{kind}",
                        f"必需{('模式' if kind == 'mode' else '工艺角')}缺失：{missing}",
                        f"交付要求中声明了 {missing}，但扫描证据没有找到对应交付文件。",
                        missing,
                    )
                )

    optional_view_results: dict[str, dict[str, Any]] = {}
    for view in optional_views:
        optional_view_results[view] = _validate_view(view, required=False, files=files, parser_by_file=parser_by_file, scan_dir=scan, validation_levels=validation_levels)

    for file_type in sorted(file_types):
        level = validation_levels.get(file_type, "pass_through_allowed")
        if level == "metadata_required":
            manual_review_items.append(_manual_review("metadata_only_ack", component_id, file_type, _files_for_type(files, file_type), "元数据级交付需要人工确认。"))
        elif level == "manual_review":
            manual_review_items.append(_manual_review("manual_view_review", component_id, file_type, _files_for_type(files, file_type), "工艺或流程配置文件需要人工确认。"))
        elif level == "pass_through_allowed":
            manual_review_items.append(_manual_review("pass_through_approval", component_id, file_type, _files_for_type(files, file_type), "未纳入自动校验的文件需要人工确认。"))
            warning_items.append(_item("warning", "pass_through", f"未自动校验的文件类型：{file_type}", "该文件类型未纳入自动校验。", file_type))

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
        "required_modes": required_modes,
        "required_corners": required_corners,
        "optional_views": optional_views,
        "required_view_results": required_view_results,
        "optional_view_results": optional_view_results,
        "validation_status": component_status,
        "release_channel": release_channel,
        "parser_quality": quality_by_type,
        "issues": blocking_items + warning_items,
        "manual_review_items": manual_review_items,
        "delivery_requirements": delivery_requirements,
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
        "delivery_requirement_status": delivery_requirements["status"],
        "delivery_requirements": delivery_requirements,
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


def _requirement_list(value: Any) -> list[str]:
    if value is None:
        return []
    values = value if isinstance(value, (list, tuple, set)) else [value]
    return [str(item).strip() for item in values if str(item).strip()]


def _normalise_corner(value: Any) -> str:
    if isinstance(value, Mapping):
        parts = [value.get("process"), value.get("voltage"), value.get("temperature")]
        text = "_".join(str(item).strip().lower() for item in parts if str(item or "").strip())
    else:
        text = str(value or "").strip().lower()
    text = text.replace(" ", "_").replace("-", "_")
    text = text.replace("p", ".")
    while "__" in text:
        text = text.replace("__", "_")
    return text.strip("_")


def _observed_delivery_modes(files: list[Mapping[str, Any]], scan_meta: Mapping[str, Any]) -> list[str]:
    values: set[str] = set()
    for key in ("delivery_modes", "required_modes_observed"):
        values.update(_requirement_list(scan_meta.get(key)))
    return sorted(values)


def _observed_delivery_corners(files: list[Mapping[str, Any]], scan_meta: Mapping[str, Any]) -> list[str]:
    values: set[str] = set()
    for key in ("delivery_corners", "required_corners_observed"):
        values.update(_normalise_corner(item) for item in _requirement_list(scan_meta.get(key)))
    return sorted(value for value in values if value)


def _candidate_delivery_hints(files: list[Mapping[str, Any]], *, kind: str) -> list[str]:
    values: set[str] = set()
    for item in files:
        if kind == "corner":
            value = _normalise_corner(item.get("corner"))
        else:
            value = str(item.get("delivery_mode") or item.get("operating_mode") or item.get("mode") or "").strip().lower()
        if value:
            values.add(value)
    return sorted(values)


def _requirement_result(required: list[str], observed: list[str], *, kind: str, normalizer=None, candidate_hints: list[str] | None = None) -> dict[str, Any]:
    candidate_hints = candidate_hints or []
    if not required:
        return {
            "status": "NOT_CONFIGURED",
            "required": [],
            "observed": observed,
            "candidate_hints": candidate_hints,
            "evidence_source": "explicit_scan_metadata" if observed else "filename_or_path_hint" if candidate_hints else "none",
            "matched": [],
            "missing": [],
            "message": f"未配置必需{('模式' if kind == 'mode' else '工艺角')}口径。",
        }
    observed_set = {str(item).strip().lower() for item in observed}
    candidate_set = {normalizer(item) if normalizer else str(item).strip().lower() for item in candidate_hints}
    matched: list[str] = []
    missing: list[str] = []
    hinted: list[str] = []
    for item in required:
        key = normalizer(item) if normalizer else str(item).strip().lower()
        if key in observed_set:
            matched.append(item)
        else:
            missing.append(item)
            if key in candidate_set:
                hinted.append(item)
    hint_message = f"；文件名/目录仅提示可能包含 {', '.join(hinted)}，尚未确认" if hinted else ""
    return {
        "status": "BLOCK" if missing else "PASS",
        "required": required,
        "observed": observed,
        "candidate_hints": candidate_hints,
        "hinted_required": hinted,
        "evidence_source": "explicit_scan_metadata" if observed else "filename_or_path_hint" if candidate_hints else "none",
        "matched": matched,
        "missing": missing,
        "message": "全部必需项已确认。" if not missing else f"缺少 {len(missing)} 项已确认的必需交付{('模式' if kind == 'mode' else '工艺角')}{hint_message}。",
    }


def _build_delivery_requirements(
    files: list[Mapping[str, Any]],
    scan_meta: Mapping[str, Any],
    *,
    required_views: list[str],
    required_modes: list[str],
    required_corners: list[str],
    required_view_results: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    observed_modes = _observed_delivery_modes(files, scan_meta)
    observed_corners = _observed_delivery_corners(files, scan_meta)
    candidate_modes = _candidate_delivery_hints(files, kind="mode")
    candidate_corners = _candidate_delivery_hints(files, kind="corner")
    mode_result = _requirement_result(required_modes, observed_modes, kind="mode", candidate_hints=candidate_modes)
    corner_result = _requirement_result(required_corners, observed_corners, kind="corner", normalizer=_normalise_corner, candidate_hints=candidate_corners)
    view_missing = [view for view in required_views if str((required_view_results.get(view) or {}).get("status")) not in {"PASS", "FOUND"}]
    view_result = {
        "status": "BLOCK" if view_missing else "PASS" if required_views else "NOT_CONFIGURED",
        "required": required_views,
        "observed": [view for view in required_views if view not in view_missing],
        "matched": [view for view in required_views if view not in view_missing],
        "missing": view_missing,
        "message": "全部必需视图已发现。" if not view_missing else f"缺少 {len(view_missing)} 项必需视图。",
    }
    statuses = {view_result["status"], mode_result["status"], corner_result["status"]}
    overall = "BLOCK" if "BLOCK" in statuses else "PASS" if statuses == {"PASS"} else "NOT_CONFIGURED" if statuses == {"NOT_CONFIGURED"} else "PASS"
    return {
        "status": overall,
        "views": view_result,
        "modes": mode_result,
        "corners": corner_result,
        "message": "交付要求已满足。" if overall == "PASS" else "存在未满足的交付要求。" if overall == "BLOCK" else "未配置 Mode/Corner 交付口径。",
    }


def _parser_tasks_by_file(parser_manifest: Mapping[str, Any]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    out: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for file_entry in parser_manifest.get("files", []) or []:
        file_type = canonical_view_type(str(file_entry.get("file_type", "unknown")))
        file_path = _normalize_evidence_path(file_entry.get("file"))
        if not file_path:
            continue
        for task in file_entry.get("parser_tasks", []) or []:
            out.setdefault((file_type, file_path), []).append({**task, "file": file_entry.get("file")})
    return out


def _normalize_evidence_path(value: Any) -> str:
    raw = str(value or "").replace("\\", "/").strip()
    if not raw:
        return ""
    normalized = str(PurePosixPath(raw))
    return normalized[2:] if normalized.startswith("./") else normalized


def _parser_result_exists(scan_dir: Path, result_path: Any) -> bool:
    if not result_path:
        return False
    scan_root = scan_dir.resolve()
    result = (scan_dir / str(result_path)).resolve()
    try:
        result.relative_to(scan_root)
    except ValueError:
        return False
    return result.is_file()


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
    files: list[Mapping[str, Any]],
    parser_by_file: dict[tuple[str, str], list[dict[str, Any]]],
    scan_dir: Path,
    validation_levels: dict[str, str],
) -> dict[str, Any]:
    view = canonical_view_type(view)
    level = validation_levels.get(view, "pass_through_allowed")
    candidates = [item for item in files if canonical_view_type(str(item.get("file_type", "unknown"))) == view]
    unique_files: dict[str, Mapping[str, Any]] = {}
    for index, item in enumerate(candidates):
        path_key = _normalize_evidence_path(item.get("path")) or f"<missing-path:{index}>"
        unique_files.setdefault(path_key, item)
    view_files = [unique_files[key] for key in sorted(unique_files)]
    found = bool(view_files)
    file_names = [str(item.get("path") or "") for item in view_files if item.get("path")]

    if not found:
        return {"view": view, "found": False, "validation_level": level, "parser_status": None, "status": "BLOCK" if required else "INFO", "message": "必需视图缺失。" if required else "可选视图未发现。", "files": [], "evidence_counts": {"total": 0, "satisfied": 0, "incomplete": 0}, "incomplete_files": []}
    if level == "metadata_required":
        return {"view": view, "found": True, "validation_level": level, "parser_status": "METADATA_ONLY", "status": "PASS", "message": "已记录文件元数据；不代表完成内容或语义解析。", "files": file_names, "evidence_counts": {"total": len(view_files), "satisfied": len(view_files), "incomplete": 0}, "incomplete_files": []}
    if level == "doc_review_required":
        return {"view": view, "found": True, "validation_level": level, "parser_status": "DOC_REVIEW", "status": "WARNING" if required else "INFO", "message": "文档需要人工审查。", "files": file_names, "evidence_counts": {"total": len(view_files), "satisfied": 0, "incomplete": len(view_files)}, "incomplete_files": file_names}
    if level == "manual_review":
        return {"view": view, "found": True, "validation_level": level, "parser_status": "MANUAL_REVIEW", "status": "WARNING", "message": "工艺或流程配置需要人工审查。", "files": file_names, "evidence_counts": {"total": len(view_files), "satisfied": 0, "incomplete": len(view_files)}, "incomplete_files": file_names}
    if level == "pass_through_allowed":
        return {"view": view, "found": True, "validation_level": level, "parser_status": "PASS_THROUGH", "status": "WARNING", "message": "未纳入自动校验的文件需要人工确认。", "files": file_names, "evidence_counts": {"total": len(view_files), "satisfied": 0, "incomplete": len(view_files)}, "incomplete_files": file_names}

    evidence_rows: list[dict[str, Any]] = []
    for inventory_file in view_files:
        path = str(inventory_file.get("path") or "")
        tasks = parser_by_file.get((view, _normalize_evidence_path(path)), [])
        statuses = [str(task.get("result_status", task.get("status", "UNKNOWN"))).upper() for task in tasks]
        missing_task = not any(task.get("parser_name") for task in tasks)
        missing_result = [
            str(task.get("parser_name") or "unknown")
            for task in tasks
            if task.get("parser_name") and (
                not task.get("result_path")
                or not _parser_result_exists(scan_dir, task.get("result_path"))
            )
        ]
        failed_statuses = [status for status in statuses if status != "PASS"]
        if missing_task:
            reason = "无解析任务" if not tasks else "解析任务被跳过或未声明解析器"
            if statuses:
                reason += "（状态=" + ",".join(sorted(set(statuses))) + "）"
        elif failed_statuses:
            reason = "解析状态=" + ",".join(sorted(set(failed_statuses)))
        elif missing_result:
            reason = "缺少解析结果文件(" + ",".join(sorted(set(missing_result))) + ")"
        else:
            reason = ""
        evidence_rows.append({"file": path, "status": statuses, "reason": reason})

    incomplete_files = [row["file"] for row in evidence_rows if row["reason"]]
    satisfied_count = len(evidence_rows) - len(incomplete_files)
    counts = {"total": len(evidence_rows), "satisfied": satisfied_count, "incomplete": len(incomplete_files)}
    parser_statuses = [status for row in evidence_rows for status in row["status"]]
    worst_status = _worst_parser_status(parser_statuses)
    if incomplete_files:
        status = "BLOCK" if required and level == "parsed_required" else "WARNING"
        reasons = [f"{row['file']}：{row['reason']}" for row in evidence_rows if row["reason"]]
        message = f"解析证据不完整（{satisfied_count}/{len(evidence_rows)} 个文件通过）：" + "；".join(reasons)
        return {"view": view, "found": True, "validation_level": level, "parser_status": worst_status or "UNVERIFIED", "status": status, "message": message, "files": file_names, "evidence_counts": counts, "incomplete_files": incomplete_files}
    return {"view": view, "found": True, "validation_level": level, "parser_status": "PASS", "status": "PASS", "message": f"全部 {len(evidence_rows)} 个文件均有成功解析结果。", "files": file_names, "evidence_counts": counts, "incomplete_files": []}


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
        limitations.append("内容解析验证尚未完成")
    if level in {"L0", "L1"}:
        limitations.append("深度文件对比尚未完成")
    if required_view_status != "PASS":
        limitations.append(f"必需视图状态为 {required_view_status}")
    if not doc_summary.get("release_note_found"):
        limitations.append("未找到发布说明")
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
        actions.append({"title": item["title"], "component_id": component_id, "command": "lg.csh scan <library> <version> --rescan"})
    for item in warning_items:
        actions.append({"title": item["title"], "component_id": component_id, "command": "打开版本详情页；如有需要，记录负责人决定。"})
    return actions
