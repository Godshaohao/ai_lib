from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Mapping

from lib_guard.package.types import DOC_PACKAGE_TYPES, PARTIAL_PACKAGE_TYPES, normalize_package_type
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
    "Summary-only": "摘要级证据",
    "Metadata-only": "元数据级证据",
    "No delta": "无变化",
    "Same-content path evidence": "内容一致证据",
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
    return str(model.get("status_message") or STATUS_COPY.get(status) or f"更新详情状态：{status or '待确认'}。")


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
    counts = {"added": 0, "removed": 0, "changed": 0, "unmatched_new": 0, "unmatched_base": 0}
    path_restructure = _as_mapping(model.get("path_restructure"))
    package_root_unmatched = _as_mapping(model.get("package_root_unmatched"))
    unmatched_new_budget = _as_int(package_root_unmatched.get("new"))
    unmatched_base_budget = _as_int(package_root_unmatched.get("base"))
    new_root = str(path_restructure.get("new_root") or "").strip("/")
    old_root = str(path_restructure.get("old_root") or "").strip("/")
    raw_diff = _as_mapping(model.get('file_diff'))
    explicit_new = raw_diff.get('unmatched_added_under_package_root')
    explicit_base = raw_diff.get('unmatched_removed_under_package_root')

    def under_root(path: Any, root: str) -> bool:
        text = str(path or "").strip("/")
        return bool(root) and text.startswith(root + "/")

    for source in file_changes:
        item = dict(source)
        kind = str(item.get("change") or item.get("status") or "").upper()
        display_kind = str(item.get("display_change") or "").upper()
        if display_kind in {"UNMATCHED_NEW", "UNMATCHED_BASE"}:
            counts[display_kind.lower()] += 1
            visible_changes.append(item)
            continue
        if kind == "REMOVED" and delete_semantics == "out_of_scope_missing":
            item["display_change"] = "BASELINE_ONLY"
            baseline_only_changes.append(item)
            continue
        if kind == "ADDED":
            if (item.get('path') in explicit_new if isinstance(explicit_new, list) else unmatched_new_budget and under_root(item.get("path"), new_root)):
                item["display_change"] = "UNMATCHED_NEW"
                item["review_label"] = "未匹配新侧文件"
                item["review_meaning"] = "处于新包根下，但当前基准证据没有唯一旧侧匹配；不能直接当作真实新增。"
                counts["unmatched_new"] += 1
            else:
                counts["added"] += 1
        elif kind == "REMOVED":
            if (item.get('path') in explicit_base if isinstance(explicit_base, list) else unmatched_base_budget and under_root(item.get("path"), old_root)):
                item["display_change"] = "UNMATCHED_BASE"
                item["review_label"] = "未匹配基准侧文件"
                item["review_meaning"] = "处于旧包根下，但当前目标证据没有唯一新侧匹配；不能直接当作真实删除。"
                counts["unmatched_base"] += 1
            else:
                counts["removed"] += 1
        elif kind in {"CHANGED", "MODIFIED"}:
            counts["changed"] += 1
        item.setdefault("display_change", kind or "UNKNOWN")
        visible_changes.append(item)

    path_changes_same_content = [
        dict(item)
        for item in model.get("path_changes_same_content", []) or []
        if isinstance(item, Mapping)
    ]
    if path_changes_same_content:
        counts["path_changed_same_content"] = len(path_changes_same_content)

    return {
        "schema_version": "ip_change_projection.v1",
        "comparison_semantics": str(model.get("comparison_semantics") or "full"),
        "delete_semantics": delete_semantics,
        "visible_counts": counts,
        "visible_changes": visible_changes,
        "path_changes_same_content": path_changes_same_content,
        "baseline_only_count": len(baseline_only_changes),
        "baseline_only_changes": baseline_only_changes,
        "baseline_only_label": "基准存在、本包未携带（不代表删除）",
    }


def _change_counts_by_view(file_changes: list[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, int]] = defaultdict(
        lambda: {"added": 0, "removed": 0, "changed": 0, "unmatched_new": 0, "unmatched_base": 0}
    )
    for item in file_changes:
        raw_type = _norm_type(item.get("file_type"))
        view_type = _canonical_view_type(raw_type)
        change = str(item.get("change") or "").lower()
        display_change = str(item.get("display_change") or "").lower()
        if display_change in {"unmatched_new", "unmatched_base"}:
            out[view_type][display_change] += 1
            raw_counts = out[view_type].setdefault("raw_delta_counts", {})
            raw_counts[raw_type] = raw_counts.get(raw_type, 0) + 1
            continue
        if change in {"added", "removed", "changed"}:
            out[view_type][change] += 1
            raw_counts = out[view_type].setdefault("raw_delta_counts", {})
            raw_counts[raw_type] = raw_counts.get(raw_type, 0) + 1
    return dict(out)


def _path_changes_by_view(path_changes: list[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = defaultdict(lambda: {"count": 0, "examples": []})
    for item in path_changes:
        view_type = _canonical_view_type(item.get("file_type"))
        out[view_type]["count"] += 1
        if len(out[view_type]["examples"]) < 8:
            out[view_type]["examples"].append(
                {
                    "old": str(item.get("old") or "-"),
                    "new": str(item.get("new") or "-"),
                    "reason": str(item.get("reason") or "confirmed_same_content"),
                }
            )
    return dict(out)


def _cn_change_kind(value: Any) -> str:
    text = str(value or "").lower()
    if text == "unmatched_new":
        return "未匹配新侧"
    if text == "unmatched_base":
        return "未匹配基准侧"
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
        label = f"{_cn_change_kind(item.get('display_change') or item.get('change'))}: {path}"
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
    counts = {"重点审查": 0, "人工审查": 0, "摘要级证据": 0, "元数据级证据": 0}
    for item in file_changes:
        if _canonical_view_type(item.get("file_type")) != view_type:
            continue
        lane = str(item.get("review_lane") or "").strip()
        if lane == "Summary-only":
            counts["摘要级证据"] += 1
        elif lane == "Metadata-only":
            counts["元数据级证据"] += 1
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
    path_changes = [
        item
        for item in projection.get("path_changes_same_content", []) or []
        if isinstance(item, Mapping)
    ]
    baseline_only_changes = [item for item in projection.get("baseline_only_changes", []) or [] if isinstance(item, Mapping)]
    raw_current_counts = _current_type_counts(model)
    current_counts = _aggregate_counts_by_view(raw_current_counts)
    base_types = _as_mapping(_as_mapping(model.get('file_diff')).get('by_type')).get('old')
    base_counts = _aggregate_counts_by_view(_as_mapping(base_types))
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
    path_delta = _path_changes_by_view(path_changes)
    baseline_only = _change_counts_by_view(baseline_only_changes)
    keys = set(delta)
    keys.update(path_delta)
    keys.update(baseline_only)
    keys.update(key for key, value in current_counts.items() if _as_int(value))
    keys.update(key for key, value in candidate_counts.items() if _as_int(value))
    rows: list[dict[str, Any]] = []
    for view_type in sorted(keys, key=_view_sort_key):
        counts = delta.get(view_type, {"added": 0, "removed": 0, "changed": 0, "raw_delta_counts": {}})
        baseline_only_count = _as_int(baseline_only.get(view_type, {}).get("removed"))
        unmatched_new_count = _as_int(counts.get("unmatched_new"))
        unmatched_base_count = _as_int(counts.get("unmatched_base"))
        delta_total = counts["added"] + counts["removed"] + counts["changed"] + unmatched_new_count + unmatched_base_count
        path_changed_same_content = _as_int(path_delta.get(view_type, {}).get("count"))
        evidence_levels = _evidence_levels_for_view(visible_changes, view_type)
        evidence_counts = _evidence_counts_for_view(visible_changes, view_type)
        current_total = _as_int(current_counts.get(view_type))
        current_total = max(current_total, counts["added"] + counts["changed"])
        candidate_total = _as_int(candidate_counts.get(view_type)) if candidate_available else None
        if delta_total or baseline_only_count or path_changed_same_content:
            full_evidence_href = str(trace_links.get("file_diff") or trace_links.get("diff_report") or "")
        elif view_type == "unknown":
            full_evidence_href = str(scan_review_links.get("unknown_files") or scan_review_links.get("files_by_view") or "")
        else:
            full_evidence_href = str(scan_review_links.get("files_by_view") or "")
        current_row_examples = _short_examples(current_examples.get(view_type, []), limit=8)
        changed_row_examples = _short_examples(changed_examples.get(view_type, []), limit=8)
        baseline_row_examples = _short_examples(baseline_only_examples.get(view_type, []), limit=8)
        sample_count = len(set(current_row_examples + changed_row_examples + baseline_row_examples))
        if unmatched_new_count or unmatched_base_count:
            status = "WARNING"
            status_label = "需确认匹配"
        elif delta_total:
            status = "INFO"
            status_label = "有更新"
        elif path_changed_same_content:
            status = "PASS"
            status_label = "路径变化，内容相同"
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
                "base_count": _as_int(base_counts.get(view_type)) if isinstance(base_types, Mapping) and not first_version else None,
                "candidate_effective_count": candidate_total,
                "added": counts["added"],
                "removed": counts["removed"],
                "changed": counts["changed"],
                "unmatched_new": unmatched_new_count,
                "unmatched_base": unmatched_base_count,
                "path_changed_same_content": path_changed_same_content,
                "delta_total": delta_total,
                "baseline_only_count": baseline_only_count,
                "evidence_level": (
                    " / ".join(evidence_levels)
                    if evidence_levels
                    else _evidence_copy("Same-content path evidence")
                    if path_changed_same_content
                    else _evidence_copy("No delta")
                ),
                "evidence_counts": evidence_counts,
                "current_examples": current_row_examples,
                "changed_examples": changed_row_examples,
                "baseline_only_examples": baseline_row_examples,
                "path_change_examples": list(path_delta.get(view_type, {}).get("examples", [])),
                "sample_count": sample_count,
                "total_evidence_count": max(
                    current_total,
                    delta_total + baseline_only_count + path_changed_same_content,
                ),
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
                "summary": "未识别到相对基准版的视图关联变化。",
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
            "delivery_requirements": {},
            "delivery_requirement_status": "UNKNOWN",
        }

    required: dict[str, Mapping[str, Any]] = {}
    optional: dict[str, Mapping[str, Any]] = {}
    required_view_evidence: dict[str, dict[str, Any]] = {}
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
            key = canonical_view_type(view)
            result_map = _as_mapping(result)
            required[key] = result_map
            counts = _as_mapping(result_map.get("evidence_counts"))
            incomplete = [str(item) for item in result_map.get("incomplete_files", []) or [] if str(item).strip()]
            required_view_evidence[key] = {
                "view": key,
                "status": str(result_map.get("status") or "UNKNOWN"),
                "validation_level": str(result_map.get("validation_level") or "unknown"),
                "parser_status": str(result_map.get("parser_status") or "UNKNOWN"),
                "total": counts.get("total", 0),
                "satisfied": counts.get("satisfied", 0),
                "incomplete": counts.get("incomplete", 0),
                "incomplete_file_count": len(incomplete),
                "incomplete_files": incomplete[:20],
                "message": str(result_map.get("message") or ""),
            }
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
    delivery_requirements = _as_mapping(readiness.get("delivery_requirements"))
    requirement_status = str(readiness.get("delivery_requirement_status") or delivery_requirements.get("status") or "").upper()
    contract_missing: list[str] = []
    for key, label_text in (("modes", "模式"), ("corners", "工艺角")):
        result = _as_mapping(delivery_requirements.get(key))
        contract_missing.extend(f"{label_text}：{item}" for item in result.get("missing", []) or [])
    if requirement_status == "BLOCK":
        status = "BLOCKED"
        label = "交付要求不满足"
    return {
        "status": status,
        "label": label,
        "required_total": len(required),
        "required_present": required_present,
        "required_views": [view_label(key) for key in required],
        "required_view_evidence": [required_view_evidence[key] for key in sorted(required_view_evidence)],
        "present": [view_label(key) for key, result in required.items() if is_present(result)],
        "missing": [view_label(key) for key in missing_keys],
        "optional_present": optional_present,
        "optional_total": len(optional),
        "release_level": str(readiness.get("release_level_candidate") or ""),
        "delivery_requirements": delivery_requirements,
        "delivery_requirement_status": requirement_status or "NOT_CONFIGURED",
        "contract_missing": contract_missing,
    }


def _review_gate_counts(model: Mapping[str, Any]) -> tuple[int, int, str]:
    gate = _as_mapping(model.get("review_gate"))
    return (
        len(gate.get("blocking_items", []) or []),
        len(gate.get("attention_items", []) or []),
        str(gate.get("status") or "NOT_BUILT").upper(),
    )


def _ip_next_action(
    model: Mapping[str, Any],
    *,
    base_blocked: bool,
    diff_missing: bool,
    required_view_missing: bool,
    required_delivery_missing: bool = False,
    package_type: str = "UNKNOWN_PACKAGE",
    combination_recorded: bool = False,
    interface_conflict: bool = False,
    first_version: bool,
    p0p1: int,
    removed: int,
    unknown_count: int,
) -> dict[str, str]:
    """Return the one action that belongs on the primary decision surface.

    The action is deliberately a small structured projection. It is not a
    command planner; it tells the reviewer what fact must be resolved next.
    """
    if base_blocked:
        return {
            "kind": "confirm_base",
            "label": "确认基准版",
            "detail": "补充当前有效版、上一有效版或手动基准，再重新生成更新详情。",
        }
    if diff_missing:
        return {
            "kind": "generate_diff",
            "label": "生成可信对比",
            "detail": "补齐当前版本相对基准版的 diff 证据，再判断变化和使用影响。",
        }
    if interface_conflict:
        return {
            "kind": "review_interface_conflict",
            "label": "核对组合接口冲突",
            "detail": "核对完整有效组合中的单元、Pin 或端口冲突及来源文件，再确认接入影响。",
        }
    if package_type == "UNKNOWN_PACKAGE" and model.get("package_type") is not None:
        return {
            "kind": "confirm_package_type",
            "label": "确认包类型",
            "detail": "先确认包类型和交付范围，再核对目标有效组合；不能把本包未带的视图直接判为组合缺失。",
        }
    if required_view_missing or required_delivery_missing:
        if package_type in PARTIAL_PACKAGE_TYPES | DOC_PACKAGE_TYPES:
            return {
                "kind": "confirm_effective_scope",
                "label": "核对有效组合",
                "detail": (
                    "核对候选组合清单中的继承文件来源和本次更新范围，再检查受影响接口。"
                    if combination_recorded else
                    "确认目标有效组合及继承文件来源，再检查本次更新范围；无需在增量包内重复交付全部视图。"
                ),
            }
        return {
            "kind": "complete_required_view",
            "label": "确认必需视图" if required_view_missing else "确认必需交付项",
            "detail": "核对完整包的必需视图和解析证据，缺口确认前不要判定可用。" if required_view_missing and not required_delivery_missing else "核对必需 View、Mode、Corner 的交付证据，缺口确认前不要判定可用。",
        }
    if first_version:
        return {
            "kind": "review_first_version",
            "label": "核对首版交付",
            "detail": "按视图变化矩阵和文件结构核对版本自身的交付覆盖与证据等级。",
        }
    if package_type in PARTIAL_PACKAGE_TYPES | DOC_PACKAGE_TYPES:
        return {
            "kind": "confirm_effective_scope",
            "label": "核对有效组合",
            "detail": "核对本包更新范围和目标有效组合的继承来源，按需检查受影响接口。",
        }
    if p0p1 or removed or unknown_count:
        return {
            "kind": "review_changes",
            "label": "核对变化和待分类文件",
            "detail": "查看视图变化矩阵、重点文件和未知路径；重点级别不自动等同于阻塞。",
        }
    existing = _as_mapping(model.get("primary_next_action"))
    return {
        "kind": str(existing.get("kind") or "review_evidence"),
        "label": str(existing.get("label") or "查看变化证据"),
        "detail": "按视图变化矩阵和文件结构核对当前版本事实。",
    }


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
    path_changed_same_content = _as_int(visible_counts.get("path_changed_same_content"))
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
    required_view_missing = bool(delivery_completeness.get("missing")) or delivery_completeness["status"] == "MISSING"
    delivery_requirement_missing = delivery_completeness.get("delivery_requirement_status") == "BLOCK"
    package_type = normalize_package_type(model.get("package_type"))
    overlay = package_type in PARTIAL_PACKAGE_TYPES | DOC_PACKAGE_TYPES
    candidate_inventory = _as_mapping(model.get("candidate_effective_inventory"))
    combination_recorded = bool(candidate_inventory.get("manifest") and
                                _as_mapping(candidate_inventory.get("file_type_counts")))
    semantic = _as_mapping(model.get("semantic_check"))
    interface_conflict = str(semantic.get("status") or "").upper() == "CURRENT" and any(
        str(item.get("status") or "").upper() == "FAIL" and
        str(item.get("check_id") or "").upper() in {
            "MACRO_BINDING", "SIGNAL_PORT_SET", "SIGNAL_PORT_DIRECTION", "PG_PORT_LEF_LIB",
            "LEF_PIN_DELTA", "LEF_INTERFACE_DELTA", "PORT_DECLARATION_DELTA", "LIB_PORT_DELTA",
        }
        for group in (semantic.get("checks") or [], semantic.get("delta") or [])
        for item in group
        if isinstance(item, Mapping)
    )

    if base_blocked:
        ip_decision = "BLOCKED"
        ip_label = "暂不可判断"
        main_reason = "基准版、扫描、对比基础证据不可信，不能作为版本更新判断。"
    elif diff_missing:
        ip_decision = "BLOCKED"
        ip_label = "暂不可判断"
        main_reason = f"尚未生成相对{base_noun}的可信对比，当前不能判断版本变化。"
    elif interface_conflict:
        ip_decision = "USAGE_REVIEW_REQUIRED"
        ip_label = "接口冲突待核对"
        main_reason = "完整有效组合的技术检查发现单元、Pin 或端口接口冲突；先核对对象、来源和接入影响。"
    elif package_type == "UNKNOWN_PACKAGE" and model.get("package_type") is not None:
        ip_decision = "USAGE_REVIEW_REQUIRED"
        ip_label = "包范围待确认"
        main_reason = "包类型尚未确认；当前扫描仅说明本包交付范围，不能判断完整有效组合是否齐备。"
    elif required_view_missing or delivery_requirement_missing:
        ip_decision = "USAGE_REVIEW_REQUIRED"
        ip_label = "组合待核对" if overlay else "交付缺口待核对"
        missing = "、".join((delivery_completeness.get("missing", []) or []) + (delivery_completeness.get("contract_missing", []) or []))
        if overlay:
            main_reason = (
                f"本包未交付 {missing or '部分必需视图'}；"
                + ("候选组合清单已记录，继承来源及技术覆盖仍须核对。" if combination_recorded
                   else "完整有效组合与继承来源尚未确认，不能据此判断技术可用性。")
            )
        else:
            main_reason = f"完整包的必需交付项存在缺口：{missing or '未标明'}；需核对后判断技术使用条件。"
    elif first_version:
        ip_decision = "USAGE_REVIEW_REQUIRED"
        ip_label = "首版需审查"
        main_reason = "当前无可比基准版；不做变化判断，先审查版本自身 view 覆盖、文件分类和证据等级。"
    elif overlay:
        ip_decision = "USAGE_REVIEW_REQUIRED"
        ip_label = "组合待核对"
        main_reason = (
            "当前为增量或文档交付；候选组合清单已记录，继承来源和技术覆盖仍须核对。"
            if combination_recorded else
            "当前为增量或文档交付；目标有效组合尚未确认，不能仅凭单包扫描判断可用性。"
        )
    elif p0p1 or removed or unknown_count:
        ip_decision = "USAGE_REVIEW_REQUIRED"
        ip_label = "需审查后使用"
        reasons = []
        if p0p1:
            reasons.append(f"{p0p1} 个重点文件")
        if removed:
            reasons.append(f"{removed} 个删除文件")
        if unknown_count:
            reasons.append(f"{unknown_count} 个未知文件待分类")
        main_reason = f"相对{base_noun}有变化，包含" + "、".join(reasons) + "；请查看变化矩阵。"
    elif added or changed:
        ip_decision = "READY"
        ip_label = "可接入"
        main_reason = f"相对{base_noun}检测到交付变化；当前采用的证据策略未发现自动阻塞条件。"
    elif path_changed_same_content:
        ip_decision = "READY"
        ip_label = "可接入"
        main_reason = (
            f"相对{base_noun}检测到 {path_changed_same_content} 个路径变化；"
            "内容一致证据已确认，这些事件不计入内容修改。"
        )
    else:
        ip_decision = "READY"
        ip_label = "可接入"
        main_reason = f"未识别到相对{base_noun}的可见变化；当前证据等级不自动构成阻塞。"

    next_action = _ip_next_action(
        model,
        base_blocked=base_blocked,
        diff_missing=diff_missing,
        required_view_missing=required_view_missing,
        required_delivery_missing=delivery_requirement_missing,
        package_type=package_type,
        combination_recorded=combination_recorded,
        interface_conflict=interface_conflict,
        first_version=first_version,
        p0p1=p0p1,
        removed=removed,
        unknown_count=unknown_count,
    )

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
                "summary": "当前无可比基准版，需确认这是完整交付包并核对自身视图覆盖。",
                "file_count": _scan_file_count(model),
            }
        )
        if unknown_count:
            pending_facts.append(
                {
                    "kind": "UNKNOWN_FILES",
                    "label": "待分类文件",
                    "summary": f"当前交付包存在 {unknown_count} 个未知文件。",
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
                    "summary": f"当前交付包存在 {unknown_count} 个未知文件。",
                    "file_count": unknown_count,
                }
            )
    if required_view_missing:
        missing = "、".join(delivery_completeness.get("missing", []) or [])
        pending_facts.insert(
            0,
            {
                "kind": "REQUIRED_VIEW_MISSING",
                "label": "本包未交付必需视图" if overlay else "完整包必需视图缺失",
                "summary": (
                    f"本包未交付：{missing or '未标明'}；需从有效组合核对继承来源，不能据此认定组合缺失。"
                    if overlay else f"完整包缺少必需视图：{missing or '未标明'}；需核对交付要求。"
                ),
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
    changed_rows = [
        row
        for row in view_rows
        if _as_int(row.get("delta_total")) or _as_int(row.get("path_changed_same_content"))
    ]
    changed_areas = []
    for row in changed_rows:
        area = str(row.get("usage_area") or "其他")
        if area not in changed_areas:
            changed_areas.append(area)
    if first_version:
        impact_summary = "首版交付范围：没有基准版，不作新增/删除/修改判断；当前页面展示交付包自身的视图覆盖。"
    elif base_blocked or diff_missing:
        impact_summary = "对比证据尚未完成；当前不作使用影响判断。"
    elif added or removed or changed:
        impact_summary = "影响场景：" + "、".join(changed_areas[:5]) + "；变化只描述交付差异，不等同于不可使用。"
    elif path_changed_same_content:
        impact_summary = (
            f"检测到 {path_changed_same_content} 个路径变化且内容相同的文件；"
            "该类别单独展示，不计入内容修改。"
        )
    else:
        scope_unconfirmed = overlay or (model.get("package_type") is not None and package_type == "UNKNOWN_PACKAGE")
        impact_summary = (
            "未识别到本包视图变化；完整组合使用范围仍待核对。" if scope_unconfirmed
            else "未识别到视图变化；当前交付可按既有使用场景接入。"
        )
    change_status = "FIRST_VERSION_REVIEW" if first_version else "UNKNOWN" if base_blocked or diff_missing else "CHANGED" if added or removed or changed or path_changed_same_content else "SAME"
    change_label = _copy(DIFF_STATUS_COPY, change_status)
    base_source = str(model.get("base_source") or "")
    scan_context = _as_mapping(_as_mapping(model.get("scan_evidence")).get("context"))
    scan_status = str(scan_context.get("scan_status") or "NOT_SCANNED").upper()
    diff_status = str(_as_mapping(model.get("comparison_context")).get("diff_status") or status_key or "UNKNOWN").upper()
    delivery_view_counts = _aggregate_counts_by_view(_current_type_counts(model))
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
        "decision": {
            "status": ip_decision,
            "label": ip_label,
            "reason": main_reason,
            "next_action": next_action,
        },
        "next_action": next_action,
        "change_summary": {
            "status": change_status,
            "label": change_label,
            "counts": {
                "added": added,
                "removed": removed,
                "changed": changed,
                "path_changed_same_content": path_changed_same_content,
            },
            "content_total": added + removed + changed,
            "total": added + removed + changed + path_changed_same_content,
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
            "首版没有变化判断；证据等级只描述检查深度。单包未交付的视图不等于有效组合缺失；正式放行另行检查。"
            if first_version
            else "摘要级证据、元数据级证据和 P0/P1 只描述证据等级；单包未交付的视图不等于有效组合缺失，正式放行另行检查。"
        ),
    }


def _report_file_changes(model: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [item for item in model.get("file_changes", []) or [] if isinstance(item, Mapping)]


def _report_count(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _report_change_counts(items: list[Mapping[str, Any]]) -> dict[str, int]:
    counts = {"added": 0, "removed": 0, "changed": 0, "unmatched_new": 0, "unmatched_base": 0}
    for item in items:
        change = str(item.get("change") or item.get("status") or "").upper()
        display_change = str(item.get("display_change") or "").upper()
        if display_change == "UNMATCHED_NEW":
            counts["unmatched_new"] += 1
        elif display_change == "UNMATCHED_BASE":
            counts["unmatched_base"] += 1
        elif change == "ADDED":
            counts["added"] += 1
        elif change == "REMOVED":
            counts["removed"] += 1
        elif change in {"CHANGED", "MODIFIED"}:
            counts["changed"] += 1
    return counts


def _report_unique(items: list[str]) -> list[str]:
    result: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def build_review_report(model: Mapping[str, Any], ip_user_view: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Build the formal, bounded review report from the existing review model.

    This is deliberately a projection builder, not another fact collector. It
    only consumes fields already assembled by scan/diff/review state and keeps
    large raw payloads out of the report used by Version Detail.
    """
    ip_view = ip_user_view if isinstance(ip_user_view, Mapping) else build_ip_user_view_model(model)
    comparison = _as_mapping(ip_view.get("comparison"))
    delivery = _as_mapping(ip_view.get("delivery_completeness"))
    scan_evidence = _as_mapping(model.get("scan_evidence"))
    scan_context = _as_mapping(scan_evidence.get("context"))
    comparison_context = _as_mapping(model.get("comparison_context"))
    evidence_state = _as_mapping(model.get("evidence_state"))
    file_changes = _report_file_changes(model)
    first_version = str(model.get("review_mode") or "").lower() == "first_version"
    status = str(model.get("status") or "UNKNOWN").upper()
    base_status = str(model.get("base_trust_status") or "UNKNOWN").upper()
    base_version = str(model.get("base_version") or "")
    base_ref = str(model.get("base_ref") or "")
    base_analysis_status = "INFO" if first_version else "BLOCKED" if base_status in {"BLOCKED", "BLOCKING"} or not base_version else "PASS"
    base_analysis = {
        "status": base_analysis_status,
        "target_version": str(model.get("target_version") or model.get("version_id") or ""),
        "base_ref": base_ref,
        "base_version": base_version,
        "base_source": str(model.get("base_source") or ""),
        "comparison_semantics": str(model.get("comparison_semantics") or ""),
        "reason": "首版/单版本没有可比基准，以下报告只描述自身交付事实。" if first_version else str(model.get("base_trust_note") or ""),
    }

    missing_views = [str(item) for item in delivery.get("missing", []) or [] if str(item).strip()]
    delivery_status = str(delivery.get("status") or "UNKNOWN").upper()
    delivery_requirements = _as_mapping(delivery.get("delivery_requirements"))
    mode_requirements = _as_mapping(delivery_requirements.get("modes"))
    corner_requirements = _as_mapping(delivery_requirements.get("corners"))
    delivery_analysis = {
        "status": "MISSING" if missing_views or delivery_status in {"MISSING", "INCOMPLETE", "BLOCKED"} else delivery_status,
        "package_type": str(model.get("package_type") or "UNKNOWN_PACKAGE"),
        "file_count": _report_count(ip_view.get("inventory_scope", {}).get("delivery_file_count")),
        "required_total": _report_count(delivery.get("required_total")),
        "required_present": _report_count(delivery.get("required_present")),
        "missing_views": missing_views,
        "present_views": [str(item) for item in delivery.get("present", []) or []],
        "requirement_status": str(delivery.get("delivery_requirement_status") or delivery_requirements.get("status") or "NOT_CONFIGURED"),
        "required_modes": [str(item) for item in mode_requirements.get("required", []) or []],
        "observed_modes": [str(item) for item in mode_requirements.get("observed", []) or []],
        "candidate_modes": [str(item) for item in mode_requirements.get("candidate_hints", []) or []],
        "hinted_required_modes": [str(item) for item in mode_requirements.get("hinted_required", []) or []],
        "mode_evidence_source": str(mode_requirements.get("evidence_source") or "none"),
        "missing_modes": [str(item) for item in mode_requirements.get("missing", []) or []],
        "required_corners": [str(item) for item in corner_requirements.get("required", []) or []],
        "observed_corners": [str(item) for item in corner_requirements.get("observed", []) or []],
        "candidate_corners": [str(item) for item in corner_requirements.get("candidate_hints", []) or []],
        "hinted_required_corners": [str(item) for item in corner_requirements.get("hinted_required", []) or []],
        "corner_evidence_source": str(corner_requirements.get("evidence_source") or "none"),
        "missing_corners": [str(item) for item in corner_requirements.get("missing", []) or []],
        "view_evidence": [dict(item) for item in delivery.get("required_view_evidence", []) or [] if isinstance(item, Mapping)],
        "package_composition": [
            str(item) for item in model.get("package_composition", []) or [] if str(item).strip()
        ],
    }

    visible_counts = _as_mapping(comparison.get("visible_counts"))
    change_projection = build_ip_change_projection(model, file_changes)
    visible_file_changes = [
        item for item in change_projection.get("visible_changes", []) or [] if isinstance(item, Mapping)
    ]
    raw_file_counts = _report_change_counts(file_changes)
    visible_file_counts = _report_change_counts(visible_file_changes)
    file_diff = _as_mapping(model.get("file_diff"))
    declared_counts_raw = _as_mapping(file_diff.get("counts"))
    declared_counts = {
        key: _report_count(declared_counts_raw.get(key))
        for key in ("added", "removed", "changed")
    }
    path_change_items = [
        item
        for item in model.get("path_changes_same_content", []) or []
        if isinstance(item, Mapping)
    ]
    declared_path_change_count = _report_count(declared_counts_raw.get("renamed_or_moved"))
    has_declared_counts = any(key in declared_counts_raw for key in ("added", "removed", "changed"))
    view_rows = [dict(row) for row in ip_view.get("view_rows", []) or [] if isinstance(row, Mapping)]
    row_totals = {"added": 0, "removed": 0, "changed": 0, "unmatched_new": 0, "unmatched_base": 0}
    if any(_report_count(row.get("path_changed_same_content")) for row in view_rows):
        row_totals["path_changed_same_content"] = 0
    for row in view_rows:
        for key in row_totals:
            row_totals[key] += _report_count(row.get(key))
    visible_totals = {key: _report_count(visible_counts.get(key)) for key in row_totals}
    matrix_status = "NOT_AVAILABLE" if first_version or status in {"DIFF_NOT_RUN", "NO_DIFF_SUMMARY", "NEEDS_BASE_CONFIRM"} else "RECONCILED" if row_totals == visible_totals else "MISMATCH"
    view_delta_analysis = {
        "status": matrix_status,
        "base_label": str(comparison.get("base_label") or ""),
        "rows": view_rows,
        "totals": visible_totals,
        "row_totals": row_totals,
        "reconciliation": "视图行汇总与对比总计一致" if matrix_status == "RECONCILED" else "当前没有可用对比，或视图行与总计需要复核",
    }

    focus_items = [item for item in model.get("recommended_file_diff", []) or [] if isinstance(item, Mapping)]
    if not focus_items:
        focus_items = [item for item in file_changes if str(item.get("review_lane") or "").upper() in {"P0", "P1"}]
    file_paths = {str(item.get("path") or "") for item in file_changes if str(item.get("path") or "")}
    focus_paths = {str(item.get("path") or "") for item in focus_items if str(item.get("path") or "")}
    content_row_totals = {
        key: _report_count(row_totals.get(key))
        for key in ("added", "removed", "changed", "unmatched_new", "unmatched_base")
    }
    reconciliation_checks = {
        "file_diff_items_match_view_matrix": visible_file_counts == content_row_totals,
        "declared_file_diff_matches_items": not has_declared_counts
        or declared_counts == {
            key: _report_count(raw_file_counts.get(key)) + (len(model.get('confirmed_unchanged_files') or []) if key == 'changed' else 0)
            for key in ("added", "removed", "changed")},
        "path_changes_match_view_matrix": (
            len(path_change_items) == _report_count(row_totals.get("path_changed_same_content"))
            and (
                "renamed_or_moved" not in declared_counts_raw
                or declared_path_change_count == len(path_change_items)
            )
        ),
        "focus_files_are_file_diff_subset": focus_paths.issubset(file_paths),
        "file_tree_status_matches_file_diff": visible_file_counts == content_row_totals,
    }
    has_file_diff_evidence = bool(file_changes) or bool(file_diff) or bool(model.get("diff_summary"))
    if first_version or status in {"DIFF_NOT_RUN", "NO_DIFF_SUMMARY", "NEEDS_BASE_CONFIRM"} or not has_file_diff_evidence:
        evidence_reconciliation_status = "NOT_AVAILABLE"
    elif all(reconciliation_checks.values()):
        evidence_reconciliation_status = "RECONCILED"
    else:
        evidence_reconciliation_status = "MISMATCH"
    evidence_reconciliation = {
        "status": evidence_reconciliation_status,
        "source": "文件变化证据 -> 审查模型 -> 视图变化矩阵 -> 重点文件 -> 文件树",
        "file_diff_declared": (
            {
                **declared_counts,
                **(
                    {"path_changed_same_content": declared_path_change_count}
                    if "renamed_or_moved" in declared_counts_raw
                    else {}
                ),
            }
            if has_declared_counts or "renamed_or_moved" in declared_counts_raw
            else {}
        ),
        "file_diff_items": {
            **raw_file_counts,
            **(
                {"path_changed_same_content": len(path_change_items)}
                if path_change_items
                else {}
            ),
        },
        "visible_file_diff_items": visible_file_counts,
        "view_matrix": row_totals,
        "focus_files": _report_change_counts(focus_items),
        "file_tree_changes": visible_file_counts,
        "checks": reconciliation_checks,
        "reader_corrections": [{'path': path, 'reason': '同一源快照的完整文件 Hash 确认相同'}
                               for path in model.get('confirmed_unchanged_files', [])],
    }
    view_delta_analysis["evidence_reconciliation"] = evidence_reconciliation
    visible_by_path = {str(item.get('path') or ''): item for item in visible_file_changes}
    focus_file_analysis = {
        "count": len(focus_items),
        "shown_count": min(len(focus_items), 120),
        "truncated": len(focus_items) > 120,
        "items": [
            {**{key: item.get(key) for key in ("change", "file_type", "path", "review_lane", "match_status", "evidence_mode") if item.get(key) is not None},
             'display_change': visible_by_path.get(str(item.get('path') or ''), item).get('display_change') or item.get('change')}
            for item in focus_items[:120]
        ],
    }

    inventory = _as_mapping(scan_evidence.get("inventory"))
    unknown_paths = [
        str(item.get("path") or item.get("relpath") or item.get("file") or "")
        for item in inventory.get("files", []) or []
        if isinstance(item, Mapping) and str(item.get("file_type") or "").lower() == "unknown"
    ]
    unknown_count = max(_report_count(scan_evidence.get("unknown_total")), len(unknown_paths))
    unknown_analysis = {
        "count": unknown_count,
        "examples": _report_unique(unknown_paths)[:20],
        "status": "NEEDS_CLASSIFICATION" if unknown_count else "NONE",
        "reason": "文件尚未归入统一 view_type；需确认是否属于交付视图、说明文件或可忽略产物。" if unknown_count else "当前没有未知文件。",
    }

    scan_status = str(scan_context.get("scan_status") or "").upper()
    diff_status = str(comparison_context.get("diff_status") or status).upper()
    evidence_status = str(evidence_state.get("status") or "").upper()
    evidence_bad = scan_status in {"FAILED", "SCAN_EMPTY", "NOT_SCANNED", "STALE"} or diff_status in {"DIFF_NOT_RUN", "NO_DIFF_SUMMARY", "NEEDS_BASE_CONFIRM"}
    evidence_assessment = {
        "status": "STALE" if scan_status == "STALE" or evidence_status == "STALE" else "INCOMPLETE" if evidence_bad or not scan_status else "PASS",
        "scan_status": scan_status or "NOT_SCANNED",
        "scan_id": str(scan_context.get("scan_id") or ""),
        "diff_status": diff_status or "UNKNOWN",
        "diff_dir": str(model.get("diff_dir") or ""),
        "evidence_state": evidence_status or "UNKNOWN",
        "sources": _report_unique([str(scan_context.get("scan_dir") or ""), str(model.get("diff_summary_path") or "")]),
    }

    open_questions: list[str] = []
    if base_analysis_status == "BLOCKED":
        open_questions.append("基准版或基准证据尚未确认，不能把当前页面当作可信变化结论。")
    if evidence_assessment["status"] in {"INCOMPLETE", "STALE"}:
        open_questions.append("扫描/对比证据尚未完成或已过期，需要重新生成对应事实。")
    if missing_views:
        package_type = normalize_package_type(model.get("package_type"))
        if package_type in PARTIAL_PACKAGE_TYPES | DOC_PACKAGE_TYPES:
            open_questions.append("本包未交付：" + "、".join(missing_views) + "；核对有效组合的继承来源。")
        elif package_type == "UNKNOWN_PACKAGE":
            open_questions.append("包类型待确认；本包未交付：" + "、".join(missing_views) + "。")
        else:
            open_questions.append("完整包必需视图尚未满足：" + "、".join(missing_views) + "。")
    if unknown_count:
        open_questions.append(f"还有 {unknown_count} 个未知文件需要分类。")
    if not first_version and not model.get("release_notes"):
        open_questions.append("当前版本没有发现发布说明证据。")
    recommended_actions = _report_unique([str(item) for item in model.get("recommended_actions", []) or []])
    if not recommended_actions:
        recommended_actions = list(open_questions)
    return {
        "schema_version": "version_review_report.v1",
        "base_analysis": base_analysis,
        "delivery_analysis": delivery_analysis,
        "view_delta_analysis": view_delta_analysis,
        "focus_file_analysis": focus_file_analysis,
        "unknown_analysis": unknown_analysis,
        "evidence_assessment": evidence_assessment,
        "open_questions": open_questions,
        "recommended_actions": recommended_actions,
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
    ip_user_view = build_ip_user_view_model(model)
    return {
        "schema_version": "version_review_model.v1",
        "source_model": "version_update_detail.v1",
        "groups": groups,
        "ip_user_view": ip_user_view,
        "review_report": build_review_report(model, ip_user_view),
    }
