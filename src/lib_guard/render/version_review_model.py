from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Mapping

from lib_guard.view_types import (
    USAGE_AREAS,
    canonical_file_type,
    canonical_view_type,
    usage_area_for_view,
    view_label,
    view_sort_key,
)

GROUP_LABELS = ["对比范围", "包根目录迁移", "文件匹配质量", "内容变化", "原始审计判断"]
STATUS_COPY = {
    "DIFF_NOT_RUN": "尚未生成更新详情；请运行 lg cat <LIB> --update-detail。",
    "NEEDS_BASE_CONFIRM": "无法确定基准版；请先确认当前有效版或上一有效版。",
    "FIRST_VERSION_REVIEW": "当前无可比基准版；按首版/单版本交付内容审查。",
    "NO_DIFF_SUMMARY": "找到对比输出目录，但缺少 diff_summary.json；请检查对比产物。",
    "CHANGED": "已完成比较，有变化。",
    "SAME": "已完成比较，无变化。",
}
BASE_REF_COPY = {
    "current_effective": "当前有效版",
    "previous_effective": "上一有效版",
    "latest_effective": "最新有效版",
    "base_full": "完整包基线",
    "review_window": "审查窗口基准",
    "explicit": "手动指定",
    "adjacent": "相邻版本",
    "adjacent_fallback": "相邻上一版",
    "recorded_base": "已记录对比基准",
    "recorded_base_fallback": "已记录对比基准",
    "NEEDS_BASE_CONFIRM": "待确认基准版",
}
BASE_SOURCE_COPY = {
    "current_effective_ref": "当前有效版引用",
    "previous_effective_version": "上一有效版",
    "base_full_version": "完整包基线",
    "catalog_recorded_base": "目录记录基线",
    "full_baseline": "完整包基线",
    "previous_full": "上一完整包",
    "latest_effective_ref": "最新有效版引用",
    "review_window.compare_old": "审查窗口对比对象",
    "explicit": "手动指定",
    "manual": "手动指定",
    "diff_summary": "对比记录",
    "diff.base_version:full_baseline": "对比记录：完整包基线",
    "diff.base_version:previous_full": "对比记录：上一完整包",
    "diff.base_version:explicit": "手动指定",
    "diff.base_version:current_effective": "当前有效版",
    "diff.base_version:previous_effective": "上一有效版",
    "diff.base_version:fallback": "已记录对比结果",
}
SEMANTICS_COPY = {
    "full": "全量",
    "incremental": "增量",
}
DELETE_COPY = {
    "real_delete": "缺失文件视为真实删除",
    "out_of_scope_missing": "缺失文件不视为删除",
}
DIFF_STATUS_COPY = {
    "CHANGED": "有变化",
    "SAME": "无变化",
    "DIFF_NOT_RUN": "未生成",
    "FIRST_VERSION_REVIEW": "首版审查",
    "NEEDS_BASE_CONFIRM": "基准版待确认",
    "NO_DIFF_SUMMARY": "缺少对比摘要",
    "UNKNOWN": "待确认",
}
USAGE_COPY = {
    "BLOCKED": "不可直接使用",
    "USAGE_REVIEW_REQUIRED": "需审查后使用",
    "READY": "可使用",
    "UNKNOWN": "待判断",
}
REASON_COPY = {
    "first_version_review": "首版/单版本需确认交付完整性",
    "diff_changed": "存在版本变化",
    "recommended_file_diff": "存在 P0/P1 重点文件",
    "release_note_missing": "缺少发布说明",
    "review_gate_blocking": "审查门禁有阻塞项",
    "review_gate_attention": "审查门禁需关注",
    "base_not_confirmed": "基准版未确认",
    "diff_incomplete": "缺少上一版对比证据",
}
ACTION_COPY = {
    "Review focused file evidence": "审查重点文件证据",
    "Open comparison review": "打开对比审查",
    "Confirm base version": "确认基准版本",
    "No action required": "无需动作",
}
EVIDENCE_LEVEL_COPY = {
    "Focused review": "重点审查",
    "Manual-review": "人工审查",
    "Summary-only": "摘要级证据（Summary-only）",
    "Metadata-only": "元数据级证据（Metadata-only）",
    "No delta": "无变化",
}
def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def _status_from_usage(decision: Any) -> str:
    key = str(decision or "").upper()
    if key in {"BLOCKED", "NEEDS_BASE_CONFIRM", "SCAN_BLOCKED", "DIFF_BLOCKED"}:
        return "BLOCKED"
    if key in {"USAGE_REVIEW_REQUIRED", "CHANGED", "DIFF", "REVIEW", "DIFF_REVIEW", "WARNING"}:
        return "WARNING"
    if key in {"READY", "PASS", "OK"}:
        return "PASS"
    return "INFO"


def _top_file_types(file_changes: list[Mapping[str, Any]], *, limit: int = 5) -> str:
    counts: Counter[str] = Counter()
    for item in file_changes:
        counts[str(item.get("file_type") or "unknown").lower()] += 1
    if not counts:
        return "无文件类型变化"
    return ", ".join(f"{name}:{count}" for name, count in counts.most_common(limit))


def _match_counts(file_changes: list[Mapping[str, Any]]) -> dict[str, int]:
    counts = {"matched_move": 0, "candidate_match": 0, "same_path": 0, "unmatched": 0}
    for item in file_changes:
        status = str(item.get("match_status") or "").lower()
        if status in {"matched_move", "candidate_match"}:
            counts[status] += 1
        elif status == "not_applicable":
            counts["same_path"] += 1
        elif status:
            counts["unmatched"] += 1
    return counts


def _facts(items: list[tuple[str, Any]]) -> list[dict[str, str]]:
    return [{"label": label, "value": str(value if value is not None else "-")} for label, value in items]


def _copy(mapping: Mapping[str, str], value: Any) -> str:
    text = str(value or "")
    return mapping.get(text, text or "-")


def _evidence_copy(value: Any) -> str:
    return _copy(EVIDENCE_LEVEL_COPY, value)


def _base_source_text(base_ref: Any, base_source: Any) -> str:
    return f"{_copy(BASE_REF_COPY, base_ref)} / {_copy(BASE_SOURCE_COPY, base_source)}"


def _reasons_text(reasons: Any) -> str:
    items = [str(item) for item in reasons or []]
    if not items:
        return "-"
    return "，".join(_copy(REASON_COPY, item) for item in items)


def _action_text(action: Any) -> str:
    label = _as_mapping(action).get("label")
    return _copy(ACTION_COPY, label)


def _status_message(model: Mapping[str, Any]) -> str:
    status = str(model.get("status") or "").upper()
    return str(model.get("status_message") or STATUS_COPY.get(status) or f"更新详情状态：{status or 'UNKNOWN'}。")


def _norm_type(value: Any) -> str:
    return canonical_file_type(value)


def _view_label(file_type: str) -> str:
    return view_label(file_type)


def _view_sort_key(file_type: str) -> tuple[int, str]:
    return view_sort_key(file_type)


def _current_type_counts(model: Mapping[str, Any]) -> Mapping[str, Any]:
    scan_evidence = _as_mapping(model.get("scan_evidence"))
    counts = _as_mapping(scan_evidence.get("counts"))
    if counts:
        return counts
    inventory = _as_mapping(scan_evidence.get("inventory"))
    files = inventory.get("files", []) or []
    if not isinstance(files, list):
        return {}
    inferred: Counter[str] = Counter()
    for item in files:
        if isinstance(item, Mapping):
            inferred[_norm_type(item.get("file_type"))] += 1
    return dict(inferred)


def _scan_file_count(model: Mapping[str, Any]) -> int:
    scan_evidence = _as_mapping(model.get("scan_evidence"))
    if _as_int(scan_evidence.get("file_count")):
        return _as_int(scan_evidence.get("file_count"))
    counts = _current_type_counts(model)
    return sum(_as_int(value) for value in counts.values())


def _unknown_file_count(model: Mapping[str, Any]) -> int:
    scan_evidence = _as_mapping(model.get("scan_evidence"))
    if _as_int(scan_evidence.get("unknown_count")):
        return _as_int(scan_evidence.get("unknown_count"))
    counts = _current_type_counts(model)
    return _as_int(counts.get("unknown"))


def _canonical_view_type(file_type: Any) -> str:
    return canonical_view_type(file_type)


def _aggregate_counts_by_view(raw_counts: Mapping[str, Any]) -> dict[str, int]:
    out: Counter[str] = Counter()
    for raw_type, count in raw_counts.items():
        out[_canonical_view_type(raw_type)] += _as_int(count)
    return dict(out)


def _raw_type_summary(raw_counts: Mapping[str, Any], *, limit: int = 5) -> str:
    pairs = [(str(key), _as_int(value)) for key, value in raw_counts.items() if _as_int(value)]
    if not pairs:
        return "-"
    pairs.sort(key=lambda item: (-item[1], item[0]))
    text = ", ".join(f"{key}:{value}" for key, value in pairs[:limit])
    if len(pairs) > limit:
        text += f" +{len(pairs) - limit}"
    return text


def build_ip_change_projection(
    model: Mapping[str, Any],
    file_changes: list[Mapping[str, Any]],
) -> dict[str, Any]:
    """Project raw diff facts into package-aware changes for IP review."""

    delete_semantics = str(model.get("delete_semantics") or "real_delete")
    visible_changes: list[dict[str, Any]] = []
    baseline_only_changes: list[dict[str, Any]] = []
    counts = {"added": 0, "removed": 0, "changed": 0}

    for source in file_changes:
        item = dict(source)
        kind = str(item.get("change") or item.get("status") or "").upper()
        if kind == "REMOVED" and delete_semantics == "out_of_scope_missing":
            item["display_change"] = "BASELINE_ONLY"
            baseline_only_changes.append(item)
            continue
        if kind == "ADDED":
            counts["added"] += 1
        elif kind == "REMOVED":
            counts["removed"] += 1
        elif kind in {"CHANGED", "MODIFIED"}:
            counts["changed"] += 1
        item["display_change"] = kind or "UNKNOWN"
        visible_changes.append(item)

    return {
        "schema_version": "ip_change_projection.v1",
        "comparison_semantics": str(model.get("comparison_semantics") or "full"),
        "delete_semantics": delete_semantics,
        "visible_counts": counts,
        "visible_changes": visible_changes,
        "baseline_only_count": len(baseline_only_changes),
        "baseline_only_changes": baseline_only_changes,
        "baseline_only_label": "基准存在、本包未携带（不代表删除）",
    }


def _change_counts_by_view(file_changes: list[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, int]] = defaultdict(lambda: {"added": 0, "removed": 0, "changed": 0})
    for item in file_changes:
        raw_type = _norm_type(item.get("file_type"))
        view_type = _canonical_view_type(raw_type)
        change = str(item.get("change") or "").lower()
        if change in {"added", "removed", "changed"}:
            out[view_type][change] += 1
            raw_counts = out[view_type].setdefault("raw_delta_counts", {})
            raw_counts[raw_type] = raw_counts.get(raw_type, 0) + 1
    return dict(out)


def _cn_change_kind(value: Any) -> str:
    text = str(value or "").lower()
    if text == "added":
        return "新增"
    if text == "removed":
        return "删除"
    if text == "changed":
        return "修改"
    return text or "变化"


def _short_examples(values: list[str], *, limit: int = 8) -> list[str]:
    unique = {str(value or "").strip() for value in values if str(value or "").strip()}
    return sorted(unique)[:limit]


def _current_file_examples_by_view(model: Mapping[str, Any], *, limit: int = 8) -> dict[str, list[str]]:
    inventory = _as_mapping(_as_mapping(model.get("scan_evidence")).get("inventory"))
    grouped: dict[str, list[str]] = defaultdict(list)
    for item in inventory.get("files", []) or []:
        if not isinstance(item, Mapping):
            continue
        view_type = _canonical_view_type(item.get("file_type"))
        path = str(item.get("path") or item.get("relpath") or item.get("file") or "").strip()
        if path and len(grouped[view_type]) < limit:
            grouped[view_type].append(path)
    return grouped


def _changed_file_examples_by_view(file_changes: list[Mapping[str, Any]], *, limit: int = 8) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for item in file_changes:
        view_type = _canonical_view_type(item.get("file_type"))
        path = str(item.get("path") or "").strip()
        if not path:
            continue
        label = f"{_cn_change_kind(item.get('change'))}: {path}"
        if len(grouped[view_type]) < limit:
            grouped[view_type].append(label)
    return grouped


def _evidence_levels_for_view(file_changes: list[Mapping[str, Any]], view_type: str) -> list[str]:
    levels: set[str] = set()
    for item in file_changes:
        if _canonical_view_type(item.get("file_type")) != view_type:
            continue
        lane = str(item.get("review_lane") or "").strip()
        if lane == "Summary-only":
            levels.add("Summary-only")
        elif lane == "Metadata-only":
            levels.add("Metadata-only")
        elif lane in {"P0", "P1"}:
            levels.add("Focused review")
        elif lane:
            levels.add("Manual-review")
    ordered = sorted(levels, key=lambda item: ["Focused review", "Manual-review", "Summary-only", "Metadata-only"].index(item) if item in {"Focused review", "Manual-review", "Summary-only", "Metadata-only"} else 99)
    return [_evidence_copy(item) for item in ordered]


def _evidence_counts_for_view(file_changes: list[Mapping[str, Any]], view_type: str) -> dict[str, int]:
    """Keep mixed evidence explicit instead of collapsing it to one label."""
    counts = {"重点审查": 0, "人工审查": 0, "摘要级证据（Summary-only）": 0, "元数据级证据（Metadata-only）": 0}
    for item in file_changes:
        if _canonical_view_type(item.get("file_type")) != view_type:
            continue
        lane = str(item.get("review_lane") or "").strip()
        if lane == "Summary-only":
            counts["摘要级证据（Summary-only）"] += 1
        elif lane == "Metadata-only":
            counts["元数据级证据（Metadata-only）"] += 1
        elif lane in {"P0", "P1"}:
            counts["重点审查"] += 1
        elif lane:
            counts["人工审查"] += 1
    return {key: value for key, value in counts.items() if value}


def _review_meaning_for_view(view_type: str, evidence_level: str, delta_total: int) -> str:
    if not delta_total:
        return "当前扫描中存在该视图，本次相对基准未发现变化。"
    if view_type == "physical_abstract":
        return "检查宏、pin、层或物理抽象是否影响 floorplan、PD 接入和抽象库引用。"
    if view_type == "rtl_model":
        return "检查 RTL/SystemVerilog 接口、模型或集成引用是否变化。"
    if view_type == "timing":
        return "检查 timing view 数量和文件身份；摘要级证据是正常策略，不等于内容缺失。"
    if view_type == "layout":
        return "检查版图类文件是否新增/删除/替换；通常按元数据、哈希和发布证据确认。"
    if view_type == "parasitic":
        return "检查寄生/抽取视图是否影响时序签核场景；默认不做内容级展开。"
    if view_type == "constraint":
        return "检查约束、UPF/CPF/SDC 是否影响综合、实现或集成脚本。"
    if view_type == "spice_netlist":
        return "检查 CDL/SPICE 连接视图是否影响 LVS 或电路级验证。"
    if view_type == "doc_evidence":
        return "检查 release note、waiver 或说明文件是否能解释本次更新。"
    if view_type == "flow_config":
        return "检查脚本/config 变化是否影响现有 flow 引用。"
    if view_type == "unknown":
        return "需要补充分类规则或人工确认，避免未知文件绕过审查。"
    if "Summary-only" in evidence_level or "Metadata-only" in evidence_level:
        return "轻量证据只说明采用摘要/元数据策略，不自动代表不完整。"
    return "按视图变化和证据等级确认是否影响当前使用场景。"


def _usage_area_for_type(file_type: str) -> str:
    return usage_area_for_view(file_type)


def _build_view_delta_rows(
    model: Mapping[str, Any],
    file_changes: list[Mapping[str, Any]],
    *,
    change_projection: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    review_mode = str(model.get("review_mode") or "").lower()
    first_version = review_mode == "first_version"
    projection = change_projection or build_ip_change_projection(model, file_changes)
    visible_changes = [item for item in projection.get("visible_changes", []) or [] if isinstance(item, Mapping)]
    baseline_only_changes = [item for item in projection.get("baseline_only_changes", []) or [] if isinstance(item, Mapping)]
    raw_current_counts = _current_type_counts(model)
    current_counts = _aggregate_counts_by_view(raw_current_counts)
    candidate_inventory = _as_mapping(model.get("candidate_effective_inventory"))
    candidate_counts = _aggregate_counts_by_view(_as_mapping(candidate_inventory.get("file_type_counts")))
    candidate_available = bool(candidate_inventory.get("manifest"))
    scan_review_links = _as_mapping(_as_mapping(model.get("scan_evidence")).get("review_links"))
    trace_links = _as_mapping(model.get("trace_links"))
    current_examples = _current_file_examples_by_view(model)
    changed_examples = _changed_file_examples_by_view(visible_changes)
    baseline_only_examples = _changed_file_examples_by_view(baseline_only_changes)
    raw_counts_by_view: dict[str, Counter[str]] = defaultdict(Counter)
    for raw_type, count in raw_current_counts.items():
        raw_counts_by_view[_canonical_view_type(raw_type)][_norm_type(raw_type)] += _as_int(count)
    delta = _change_counts_by_view(visible_changes)
    baseline_only = _change_counts_by_view(baseline_only_changes)
    keys = set(delta)
    keys.update(baseline_only)
    keys.update(key for key, value in current_counts.items() if _as_int(value))
    keys.update(key for key, value in candidate_counts.items() if _as_int(value))
    rows: list[dict[str, Any]] = []
    for view_type in sorted(keys, key=_view_sort_key):
        counts = delta.get(view_type, {"added": 0, "removed": 0, "changed": 0, "raw_delta_counts": {}})
        baseline_only_count = _as_int(baseline_only.get(view_type, {}).get("removed"))
        delta_total = counts["added"] + counts["removed"] + counts["changed"]
        evidence_levels = _evidence_levels_for_view(visible_changes, view_type)
        evidence_counts = _evidence_counts_for_view(visible_changes, view_type)
        current_total = _as_int(current_counts.get(view_type))
        current_total = max(current_total, counts["added"] + counts["changed"])
        candidate_total = _as_int(candidate_counts.get(view_type)) if candidate_available else None
        if delta_total or baseline_only_count:
            full_evidence_href = str(trace_links.get("file_diff") or trace_links.get("diff_report") or "")
        elif view_type == "unknown":
            full_evidence_href = str(scan_review_links.get("unknown_files") or scan_review_links.get("files_by_view") or "")
        else:
            full_evidence_href = str(scan_review_links.get("files_by_view") or "")
        current_row_examples = _short_examples(current_examples.get(view_type, []), limit=8)
        changed_row_examples = _short_examples(changed_examples.get(view_type, []), limit=8)
        baseline_row_examples = _short_examples(baseline_only_examples.get(view_type, []), limit=8)
        sample_count = len(set(current_row_examples + changed_row_examples + baseline_row_examples))
        if delta_total:
            status = "INFO"
            status_label = "有更新"
        elif baseline_only_count:
            status = "INFO"
            status_label = "本包未携带"
        elif first_version and current_total:
            status = "PASS"
            status_label = "已扫描"
        elif current_total:
            status = "PASS"
            status_label = "无变化"
        else:
            status = "INFO"
            status_label = "未发现"
        rows.append(
            {
                "file_type": view_type,
                "view_type": view_type,
                "view": _view_label(view_type),
                "usage_area": _usage_area_for_type(view_type),
                "current_count": current_total,
                "delivery_count": current_total,
                "candidate_effective_count": candidate_total,
                "added": counts["added"],
                "removed": counts["removed"],
                "changed": counts["changed"],
                "delta_total": delta_total,
                "baseline_only_count": baseline_only_count,
                "evidence_level": " / ".join(evidence_levels) if evidence_levels else _evidence_copy("No delta"),
                "evidence_counts": evidence_counts,
                "current_examples": current_row_examples,
                "changed_examples": changed_row_examples,
                "baseline_only_examples": baseline_row_examples,
                "sample_count": sample_count,
                "total_evidence_count": max(current_total, delta_total + baseline_only_count),
                "full_evidence_href": full_evidence_href,
                "raw_types": _raw_type_summary(raw_counts_by_view.get(view_type, {})),
                "raw_delta_types": _raw_type_summary(_as_mapping(counts.get("raw_delta_counts"))),
                "status": status,
                "status_label": status_label,
            }
        )
        rows[-1]["review_meaning"] = _review_meaning_for_view(
            view_type,
            str(rows[-1].get("evidence_level") or ""),
            delta_total,
        )
    return rows


def _build_related_usage_sections(view_rows: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    for area in list(USAGE_AREAS) + ["其他 / 证据"]:
        rows = [
            row
            for row in view_rows
            if row.get("usage_area") == area
            and (_as_int(row.get("delta_total")) or _as_int(row.get("current_count")))
        ]
        if not rows:
            continue
        types = ", ".join(str(row.get("view")) for row in rows[:5])
        delta_total = sum(_as_int(row.get("delta_total")) for row in rows)
        current_total = sum(_as_int(row.get("current_count")) for row in rows)
        evidence = sorted({str(row.get("evidence_level") or "-") for row in rows})
        if delta_total:
            summary = f"{delta_total} 个更新；涉及 {types or '-'}。"
        else:
            summary = f"当前覆盖 {current_total} 个文件；涉及 {types or '-'}。"
        sections.append(
            {
                "area": area,
                "relation_kind": "VIEW_ASSOCIATION",
                "status": "INFO",
                "summary": f"关联 {types or '-'}；本次可见变化 {delta_total} 个。" if delta_total else summary,
                "evidence": "；".join(evidence[:3]) if evidence else "-",
                "rows": rows,
            }
        )
    if not sections:
        sections.append(
            {
                "area": "其他 / 证据",
                "relation_kind": "VIEW_ASSOCIATION",
                "status": "PASS",
                "summary": "未识别到相对基准版的 View 关联变化。",
                "evidence": "-",
                "rows": [],
            }
        )
    return sections


def _delivery_completeness(model: Mapping[str, Any]) -> dict[str, Any]:
    """Project existing readiness evidence into user-facing delivery facts."""
    scan_evidence = _as_mapping(model.get("scan_evidence"))
    readiness = _as_mapping(scan_evidence.get("release_readiness"))
    if not readiness:
        return {
            "status": "UNKNOWN",
            "label": "未生成",
            "required_total": 0,
            "required_present": 0,
            "missing": [],
            "optional_present": 0,
            "release_level": "",
        }

    required: dict[str, Mapping[str, Any]] = {}
    optional: dict[str, Mapping[str, Any]] = {}
    for component in readiness.get("components", []) or []:
        if not isinstance(component, Mapping):
            continue
        required_results = _as_mapping(component.get("required_view_results"))
        optional_results = _as_mapping(component.get("optional_view_results"))
        for view in component.get("required_views", []) or []:
            key = canonical_view_type(view)
            required[key] = _as_mapping(required_results.get(view))
        for view in component.get("optional_views", []) or []:
            key = canonical_view_type(view)
            optional.setdefault(key, _as_mapping(optional_results.get(view)))
        for view, result in required_results.items():
            required[canonical_view_type(view)] = _as_mapping(result)
        for view, result in optional_results.items():
            optional.setdefault(canonical_view_type(view), _as_mapping(result))

    def is_present(result: Mapping[str, Any]) -> bool:
        if result.get("found") is True:
            return True
        return str(result.get("status") or "").upper() in {"PASS", "FOUND", "PRESENT"}

    missing_keys = [key for key, result in required.items() if not is_present(result)]
    required_present = len(required) - len(missing_keys)
    optional_present = sum(1 for result in optional.values() if is_present(result))
    readiness_status = str(readiness.get("required_view_status") or readiness.get("bundle_status") or "UNKNOWN").upper()
    if missing_keys:
        status = "MISSING"
        label = "存在缺失"
    elif required:
        status = "PASS" if readiness_status in {"PASS", "READY", "OK"} else readiness_status
        label = "已满足" if status in {"PASS", "READY", "OK"} else "待确认"
    else:
        status = "UNCONFIGURED"
        label = "未配置口径"
    return {
        "status": status,
        "label": label,
        "required_total": len(required),
        "required_present": required_present,
        "required_views": [view_label(key) for key in required],
        "missing": [view_label(key) for key in missing_keys],
        "optional_present": optional_present,
        "optional_total": len(optional),
        "release_level": str(readiness.get("release_level_candidate") or ""),
    }


def _review_gate_counts(model: Mapping[str, Any]) -> tuple[int, int, str]:
    gate = _as_mapping(model.get("review_gate"))
    return (
        len(gate.get("blocking_items", []) or []),
        len(gate.get("attention_items", []) or []),
        str(gate.get("status") or "NOT_BUILT").upper(),
    )


def build_ip_user_view_model(model: Mapping[str, Any]) -> dict[str, Any]:
    """Build the default IP-user surface from the richer update-detail model.

    This adapter deliberately hides management/debug details by default. It keeps
    the user's first screen focused on previous-effective delta, view impact, and
    evidence level. Gate/release/debug data may still exist in the source model,
    but it is rendered as hidden evidence instead of the primary story.
    """

    file_changes = [item for item in model.get("file_changes", []) or [] if isinstance(item, Mapping)]
    change_projection = build_ip_change_projection(model, file_changes)
    visible_counts = _as_mapping(change_projection.get("visible_counts"))
    lane_counts = _as_mapping(model.get("lane_counts"))
    view_rows = _build_view_delta_rows(model, file_changes, change_projection=change_projection)
    added = _as_int(visible_counts.get("added"))
    removed = _as_int(visible_counts.get("removed"))
    changed = _as_int(visible_counts.get("changed"))
    p0p1 = _as_int(lane_counts.get("recommended_file_diff"))
    if not p0p1:
        p0p1 = sum(1 for item in file_changes if str(item.get("review_lane") or "").upper() in {"P0", "P1"})
    summary_only = _as_int(lane_counts.get("summary_only"))
    metadata_only = _as_int(lane_counts.get("metadata_only"))
    status_key = str(model.get("status") or "").upper()
    review_mode = str(model.get("review_mode") or "baseline").lower()
    first_version = review_mode == "first_version"
    unknown_count = _unknown_file_count(model)
    base_key = str(model.get("base_trust_status") or "").upper()
    base_noun = _copy(BASE_REF_COPY, model.get("base_ref"))
    base_blocked = status_key in {"NEEDS_BASE_CONFIRM", "SCAN_BLOCKED", "DIFF_BLOCKED"} or base_key in {"BLOCK", "BLOCKING", "BLOCKED"}
    diff_missing = status_key in {"DIFF_NOT_RUN", "NO_DIFF_SUMMARY"}
    gate_blocking, gate_attention, gate_status = _review_gate_counts(model)
    delivery_completeness = _delivery_completeness(model)
    required_view_missing = delivery_completeness["status"] == "MISSING"

    if base_blocked:
        ip_decision = "BLOCKED"
        ip_label = "暂不可判断"
        main_reason = "基准版、扫描、对比基础证据不可信，不能作为版本更新判断。"
    elif diff_missing:
        ip_decision = "BLOCKED"
        ip_label = "暂不可判断"
        main_reason = f"尚未生成相对{base_noun}的可信对比，当前不能判断版本变化。"
    elif required_view_missing:
        ip_decision = "BLOCKED"
        ip_label = "不可接入"
        missing = "、".join(delivery_completeness.get("missing", []) or [])
        main_reason = f"当前交付缺少必需 View：{missing or '未标明'}；在补齐前不可接入。"
    elif first_version:
        ip_decision = "USAGE_REVIEW_REQUIRED"
        ip_label = "首版需审查"
        main_reason = "当前无可比基准版；不做变化判断，先审查版本自身 view 覆盖、文件分类和证据等级。"
    elif p0p1 or removed or unknown_count:
        ip_decision = "USAGE_REVIEW_REQUIRED"
        ip_label = "需审查后使用"
        reasons = []
        if p0p1:
            reasons.append(f"{p0p1} 个重点文件")
        if removed:
            reasons.append(f"{removed} 个删除文件")
        if unknown_count:
            reasons.append(f"{unknown_count} 个 Unknown 待分类文件")
        main_reason = f"相对{base_noun}有变化，包含" + "、".join(reasons) + "；请查看变化矩阵。"
    elif added or changed:
        ip_decision = "READY"
        ip_label = "可接入"
        main_reason = f"相对{base_noun}检测到交付变化；当前采用的证据策略未发现自动阻塞条件。"
    else:
        ip_decision = "READY"
        ip_label = "可接入"
        main_reason = f"未识别到相对{base_noun}的可见变化；当前证据等级不自动构成阻塞。"

    if gate_blocking:
        release_decision = "INFO"
        release_label = "待发布负责人处理"
        release_reason = f"正式放行有 {gate_blocking} 个管理阻塞项；IP 技术审查仍按视图变化矩阵判断。"
    elif gate_status in {"REVIEW_REQUIRED", "NEEDS_REVIEW", "ATTENTION"} or gate_attention:
        release_decision = "INFO"
        release_label = "正式放行待确认"
        release_reason = f"审查门禁有 {gate_attention} 个关注项。"
    elif gate_status in {"READY", "PASS", "OK"}:
        release_decision = "PASS"
        release_label = "正式放行通过"
        release_reason = "审查门禁已关闭。"
    else:
        release_decision = "INFO"
        release_label = "正式放行未建立"
        release_reason = "未发现可展示的审查门禁证据。"

    pending_facts: list[dict[str, Any]] = []
    if first_version:
        pending_facts.append(
            {
                "kind": "FIRST_VERSION_SCOPE",
                "label": "首版交付范围",
                "summary": "当前无可比基准版，需确认这是完整交付包并核对自身 View 覆盖。",
                "file_count": _scan_file_count(model),
            }
        )
        if unknown_count:
            pending_facts.append(
                {
                    "kind": "UNKNOWN_FILES",
                    "label": "待分类文件",
                    "summary": f"当前交付包存在 {unknown_count} 个 Unknown 文件。",
                    "file_count": unknown_count,
                }
            )
    else:
        if base_blocked:
            pending_facts.append(
                {
                    "kind": "BASE_EVIDENCE_UNTRUSTED",
                    "label": "基准或基础证据待确认",
                    "summary": "当前 Base、scan 或 diff 基础证据不可信，不能形成版本变化结论。",
                    "file_count": 0,
                }
            )
        if removed:
            pending_facts.append(
                {
                    "kind": "REAL_REMOVAL",
                    "label": "真实删除",
                    "summary": f"全量对比语义下识别到 {removed} 个真实删除文件。",
                    "file_count": removed,
                }
            )
        if unknown_count:
            pending_facts.append(
                {
                    "kind": "UNKNOWN_FILES",
                    "label": "待分类文件",
                    "summary": f"当前交付包存在 {unknown_count} 个 Unknown 文件。",
                    "file_count": unknown_count,
                }
            )
    if required_view_missing:
        missing = "、".join(delivery_completeness.get("missing", []) or [])
        pending_facts.insert(
            0,
            {
                "kind": "REQUIRED_VIEW_MISSING",
                "label": "必需视图缺失",
                "summary": f"当前交付缺少必需 View：{missing or '未标明'}；补齐前不可接入。",
                "file_count": 0,
            },
        )
    if diff_missing and not base_blocked:
        pending_facts.append(
            {
                "kind": "DIFF_MISSING",
                "label": "对比证据缺失",
                "summary": f"尚未生成相对{base_noun}的 diff。",
                "file_count": 0,
            }
        )

    related_usage_sections = _build_related_usage_sections(view_rows)
    changed_rows = [row for row in view_rows if _as_int(row.get("delta_total"))]
    changed_areas = []
    for row in changed_rows:
        area = str(row.get("usage_area") or "其他")
        if area not in changed_areas:
            changed_areas.append(area)
    if first_version:
        impact_summary = "首版交付范围：没有基准版，不作新增/删除/修改判断；当前页面展示交付包自身的视图覆盖。"
    elif base_blocked or diff_missing:
        impact_summary = "对比证据尚未完成；当前不作使用影响判断。"
    elif changed_rows:
        impact_summary = "影响场景：" + "、".join(changed_areas[:5]) + "；变化只描述交付差异，不等同于不可使用。"
    else:
        impact_summary = "未识别到视图变化；当前交付可按既有使用场景接入。"
    change_status = "FIRST_VERSION_REVIEW" if first_version else "UNKNOWN" if base_blocked or diff_missing else "CHANGED" if added or removed or changed else "SAME"
    change_label = _copy(DIFF_STATUS_COPY, change_status)
    base_source = str(model.get("base_source") or "")
    scan_context = _as_mapping(_as_mapping(model.get("scan_evidence")).get("context"))
    scan_status = str(scan_context.get("scan_status") or "NOT_SCANNED").upper()
    diff_status = str(_as_mapping(model.get("comparison_context")).get("diff_status") or status_key or "UNKNOWN").upper()
    delivery_view_counts = _aggregate_counts_by_view(_current_type_counts(model))
    candidate_inventory = _as_mapping(model.get("candidate_effective_inventory"))
    candidate_manifest = str(candidate_inventory.get("manifest") or "")
    candidate_view_counts = _aggregate_counts_by_view(_as_mapping(candidate_inventory.get("file_type_counts")))
    trace_links = _as_mapping(model.get("trace_links"))
    scan_dir = str(scan_context.get("scan_dir") or "")
    provenance_source = str(scan_context.get("raw_path") or "")
    base_label = "无基准：首版/单版本审查" if first_version else f"{_copy(BASE_REF_COPY, model.get('base_ref'))} / {model.get('base_version') or '-'}"

    return {
        "schema_version": "ip_user_view.v2",
        "source_model": "version_update_detail.v1",
        "review_mode": review_mode,
        "decision": {"status": ip_decision, "label": ip_label, "reason": main_reason},
        "change_summary": {
            "status": change_status,
            "label": change_label,
            "counts": {"added": added, "removed": removed, "changed": changed},
            "total": added + removed + changed,
        },
        "comparison": {
            "scope": str(change_projection.get("comparison_semantics") or "full"),
            "delete_semantics": str(change_projection.get("delete_semantics") or "real_delete"),
            "visible_counts": dict(visible_counts),
            "baseline_only_count": _as_int(change_projection.get("baseline_only_count")),
            "baseline_only_label": str(change_projection.get("baseline_only_label") or ""),
            "base_label": "无基准：首版/单版本审查" if first_version else f"{_copy(BASE_REF_COPY, model.get('base_ref'))} / {model.get('base_version') or '-'}",
            "base_source": base_source,
            "base_source_label": _copy(BASE_SOURCE_COPY, base_source),
        },
        "inventory_scope": {
            "delivery_file_count": _scan_file_count(model),
            "delivery_view_counts": delivery_view_counts,
            "candidate_effective_file_count": _as_int(candidate_inventory.get("file_count")) if candidate_manifest else None,
            "candidate_effective_view_counts": candidate_view_counts if candidate_manifest else {},
            "candidate_effective_available": bool(candidate_manifest),
        },
        "view_rows": view_rows,
        "related_usage_sections": related_usage_sections,
        "pending_fact_items": pending_facts,
        "release_summary": {
            "status": release_decision,
            "label": release_label,
            "reason": release_reason,
        },
        "evidence_summary": {
            "focused_review": p0p1,
            "summary_only": summary_only,
            "metadata_only": metadata_only,
        },
        "usage_impact": {
            "areas": changed_areas,
            "summary": impact_summary,
            "changed_view_count": len(changed_rows),
        },
        "delivery_completeness": delivery_completeness,
        "lineage": {
            "base_version": "" if first_version else str(model.get("base_version") or ""),
            "base_label": "首版交付" if first_version else base_label,
            "target_version": str(model.get("version_id") or model.get("target_version") or ""),
            "relation": "首版交付" if first_version else "基准版 -> 当前版本",
        },
        "provenance": {
            "base": {
                "ref": str(model.get("base_ref") or ""),
                "version": str(model.get("base_version") or ""),
                "source": base_source,
                "source_label": _copy(BASE_SOURCE_COPY, base_source),
            },
            "scan": {"status": scan_status, "scan_id": str(scan_context.get("scan_id") or "")},
            "diff": {"status": diff_status, "directory": str(model.get("diff_dir") or "")},
            "target": {"version": str(model.get("version_id") or model.get("target_version") or ""), "source": provenance_source},
        },
        "evidence_links": {
            "scan_dir": scan_dir,
            "diff_summary": str(trace_links.get("diff_summary") or ""),
            "diff_file_changes": str(trace_links.get("file_diff") or ""),
            "candidate_effective_manifest": candidate_manifest,
        },
        "non_blocker_note": (
            "首版没有变化判断；证据等级只描述检查深度，不自动代表不完整。只有缺少可信基准/对比、扫描证据不可信、必需 View 缺失或明确门禁阻塞项才升级为阻塞。"
            if first_version
            else "摘要级证据、元数据级证据和 P0/P1 只描述证据等级，不自动构成阻塞；只有缺少可信基准/对比、扫描证据不可信、必需 View 缺失或明确门禁阻塞项才升级为阻塞。"
        ),
    }


def build_version_review_model(model: Mapping[str, Any]) -> dict[str, Any]:
    file_changes = [item for item in model.get("file_changes", []) or [] if isinstance(item, Mapping)]
    path_restructure = _as_mapping(model.get("path_restructure"))
    lane_counts = _as_mapping(model.get("lane_counts"))
    match_counts = _match_counts(file_changes)
    usage_decision = str(model.get("usage_decision") or "UNKNOWN")
    added = _as_int(model.get("added_files"))
    removed = _as_int(model.get("removed_files"))
    changed = _as_int(model.get("changed_files"))
    p0p1 = _as_int(lane_counts.get("recommended_file_diff"))
    summary_only = _as_int(lane_counts.get("summary_only"))
    metadata_only = _as_int(lane_counts.get("metadata_only"))
    blocking_issues = _as_int(lane_counts.get("blocking_issues"))
    release_notes = len(model.get("release_notes", []) or [])
    unknown_files = sum(1 for item in file_changes if str(item.get("file_type") or "").lower() == "unknown")
    migration_suspected = bool(path_restructure.get("suspected"))
    migration_matched = _as_int(path_restructure.get("package_root_migration_matched_files"))
    moved = _as_int(path_restructure.get("renamed_or_moved"))
    matched_by_root = max(migration_matched, moved)
    matched_move = max(match_counts["matched_move"], matched_by_root)
    unmatched_added_removed = max(0, added + removed - matched_by_root)
    evidence_label = "混合证据" if summary_only or metadata_only else "内容级证据"
    usage_text = _copy(USAGE_COPY, usage_decision)
    reasons_text = _reasons_text(model.get("usage_decision_reasons"))

    groups = [
        {
            "key": "comparison_scope",
            "label": "对比范围",
            "status": str(model.get("base_trust_status") or "WARNING"),
            "summary": (
                f"{_status_message(model)} "
                f"{model.get('base_trust_note') or '基准版和对比口径需要确认。'}"
            ).strip(),
            "facts": _facts(
                [
                    ("基准来源", _base_source_text(model.get("base_ref"), model.get("base_source"))),
                    ("基准版本", model.get("base_version") or "-"),
                    ("目标版本", model.get("target_version") or model.get("version_id") or "-"),
                    ("对比语义", _copy(SEMANTICS_COPY, model.get("comparison_semantics"))),
                    ("删除语义", _copy(DELETE_COPY, model.get("delete_semantics"))),
                    ("对比状态", _copy(DIFF_STATUS_COPY, model.get("status"))),
                ]
            ),
        },
        {
            "key": "package_root_migration",
            "label": "包根目录迁移",
            "status": "WARNING" if migration_suspected else "PASS",
            "summary": (
                "检测到包装目录变化；系统已按逻辑路径做上一版匹配。该信息用于解释新增/删除统计，不默认代表 IP 使用风险。"
                if migration_suspected
                else "未识别到包根目录迁移。"
            ),
            "facts": _facts(
                [
                    ("旧包根", path_restructure.get("old_root") or "-"),
                    ("新包根", path_restructure.get("new_root") or "-"),
                    ("逻辑路径匹配", migration_matched),
                    ("文件级一一匹配", moved),
                    ("旧包根文件数", _as_int(path_restructure.get("old_root_file_count"))),
                    ("新包根文件数", _as_int(path_restructure.get("new_root_file_count"))),
                    ("真实修改文件", changed),
                    ("新增/删除", f"{added}/{removed}"),
                ]
            ),
        },
        {
            "key": "file_match_quality",
            "label": "文件匹配质量",
            "status": "WARNING" if unmatched_added_removed else "PASS",
            "summary": (
                f"匹配质量：包根/文件级匹配 {matched_move}，候选匹配 {match_counts['candidate_match']}，"
                f"同路径修改 {match_counts['same_path']}，未匹配新增/删除 {unmatched_added_removed}。"
            ),
            "facts": _facts(
                [
                    ("包根/文件级匹配", matched_move),
                    ("候选匹配", match_counts["candidate_match"]),
                    ("同路径修改", match_counts["same_path"]),
                    ("未匹配新增/删除", unmatched_added_removed),
                    ("匹配依据", "文件名 / 哈希 / 解析签名 / 逻辑路径"),
                ]
            ),
        },
        {
            "key": "content_changes",
            "label": "内容变化",
            "status": "WARNING" if p0p1 or blocking_issues else "PASS",
            "summary": (
                f"变化风险：新增 {added} / 删除 {removed} / 修改 {changed}；"
                f"P0/P1={p0p1}，证据分层：{evidence_label}，摘要级={summary_only}，元数据级={metadata_only}。"
            ),
            "facts": _facts(
                [
                    ("新增文件", added),
                    ("删除文件", removed),
                    ("修改文件", changed),
                    ("P0/P1", p0p1),
                    ("证据分层", f"{evidence_label}；摘要级 {summary_only} / 元数据级 {metadata_only}"),
                    ("未知文件", unknown_files),
                    ("主要类型", _top_file_types(file_changes)),
                ]
            ),
        },
        {
            "key": "usage_impact",
            "label": "原始审计判断",
            "status": _status_from_usage(usage_decision),
            "summary": f"原始门禁/审计判断：{usage_text}；原因：{reasons_text}。",
            "facts": _facts(
                [
                    ("审计决策", usage_text),
                    ("发布说明", "已发现" if release_notes else "缺失"),
                    ("对比阻塞问题", blocking_issues),
                    ("主动作", _action_text(model.get("primary_next_action"))),
                ]
            ),
        },
    ]
    return {
        "schema_version": "version_review_model.v1",
        "source_model": "version_update_detail.v1",
        "groups": groups,
        "ip_user_view": build_ip_user_view_model(model),
    }
