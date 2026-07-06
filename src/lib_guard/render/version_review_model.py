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
    "NO_DIFF_SUMMARY": "找到对比输出目录，但缺少 diff_summary.json；请检查对比产物。",
    "CHANGED": "已完成比较，有变化。",
    "SAME": "已完成比较，无变化。",
}
BASE_REF_COPY = {
    "current_effective": "当前有效版",
    "previous_effective": "上一有效版",
    "latest_effective": "最新有效版",
    "base_full": "完整包基线",
    "explicit": "手动指定",
    "adjacent": "相邻版本",
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
    "explicit": "手动指定",
    "manual": "手动指定",
    "diff_summary": "对比记录",
    "diff.base_version:full_baseline": "对比记录：完整包基线",
    "diff.base_version:previous_full": "对比记录：上一完整包",
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
    "NEEDS_BASE_CONFIRM": "基准版待确认",
    "NO_DIFF_SUMMARY": "缺少对比摘要",
}
USAGE_COPY = {
    "BLOCKED": "不可直接使用",
    "USAGE_REVIEW_REQUIRED": "需审查后使用",
    "READY": "可使用",
    "UNKNOWN": "待判断",
}
REASON_COPY = {
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


def _usage_area_for_type(file_type: str) -> str:
    return usage_area_for_view(file_type)


def _build_view_delta_rows(model: Mapping[str, Any], file_changes: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    raw_current_counts = _current_type_counts(model)
    current_counts = _aggregate_counts_by_view(raw_current_counts)
    raw_counts_by_view: dict[str, Counter[str]] = defaultdict(Counter)
    for raw_type, count in raw_current_counts.items():
        raw_counts_by_view[_canonical_view_type(raw_type)][_norm_type(raw_type)] += _as_int(count)
    delta = _change_counts_by_view(file_changes)
    keys = set(delta)
    keys.update(key for key, value in current_counts.items() if _as_int(value))
    rows: list[dict[str, Any]] = []
    for view_type in sorted(keys, key=_view_sort_key):
        counts = delta.get(view_type, {"added": 0, "removed": 0, "changed": 0, "raw_delta_counts": {}})
        delta_total = counts["added"] + counts["removed"] + counts["changed"]
        evidence_levels = _evidence_levels_for_view(file_changes, view_type)
        current_total = _as_int(current_counts.get(view_type))
        current_total = max(current_total, counts["added"] + counts["changed"])
        if delta_total:
            status = "INFO"
            status_label = "有更新"
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
                "added": counts["added"],
                "removed": counts["removed"],
                "changed": counts["changed"],
                "delta_total": delta_total,
                "evidence_level": " / ".join(evidence_levels) if evidence_levels else _evidence_copy("No delta"),
                "raw_types": _raw_type_summary(raw_counts_by_view.get(view_type, {})),
                "raw_delta_types": _raw_type_summary(_as_mapping(counts.get("raw_delta_counts"))),
                "status": status,
                "status_label": status_label,
            }
        )
    return rows


def _build_usage_area_sections(view_rows: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    for area in list(USAGE_AREAS) + ["其他 / 证据"]:
        rows = [row for row in view_rows if row.get("usage_area") == area and _as_int(row.get("delta_total"))]
        if not rows:
            continue
        types = ", ".join(str(row.get("view")) for row in rows[:5])
        delta_total = sum(_as_int(row.get("delta_total")) for row in rows)
        evidence = sorted({str(row.get("evidence_level") or "-") for row in rows})
        sections.append(
            {
                "area": area,
                "status": "INFO",
                "summary": f"{delta_total} 个更新；涉及 {types or '-'}。",
                "evidence": "；".join(evidence[:3]) if evidence else "-",
                "rows": rows,
            }
        )
    if not sections:
        sections.append(
            {
                "area": "使用场景影响",
                "status": "PASS",
                "summary": "未识别到相对基准版的 view 变化。",
                "evidence": "-",
                "rows": [],
            }
        )
    return sections


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
    lane_counts = _as_mapping(model.get("lane_counts"))
    view_rows = _build_view_delta_rows(model, file_changes)
    changed_view_rows = [row for row in view_rows if _as_int(row.get("delta_total"))]
    added = _as_int(model.get("added_files"))
    removed = _as_int(model.get("removed_files"))
    changed = _as_int(model.get("changed_files"))
    p0p1 = _as_int(lane_counts.get("recommended_file_diff"))
    summary_only = _as_int(lane_counts.get("summary_only"))
    metadata_only = _as_int(lane_counts.get("metadata_only"))
    status_key = str(model.get("status") or "").upper()
    base_key = str(model.get("base_trust_status") or "").upper()
    base_noun = _copy(BASE_REF_COPY, model.get("base_ref"))
    base_blocked = status_key in {"NEEDS_BASE_CONFIRM", "SCAN_BLOCKED", "DIFF_BLOCKED"} or base_key in {"BLOCK", "BLOCKING", "BLOCKED"}
    diff_missing = status_key in {"DIFF_NOT_RUN", "NO_DIFF_SUMMARY"}
    gate_blocking, gate_attention, gate_status = _review_gate_counts(model)

    if base_blocked:
        ip_decision = "BLOCKED"
        ip_label = "不可接入"
        main_reason = "基准版、扫描、对比基础证据不可信，不能作为版本更新判断。"
    elif diff_missing:
        ip_decision = "USAGE_REVIEW_REQUIRED"
        ip_label = "缺少基准对比"
        main_reason = f"需要先生成相对{base_noun}的更新详情。"
    elif added or removed or changed or p0p1 or summary_only or metadata_only:
        ip_decision = "USAGE_REVIEW_REQUIRED"
        ip_label = "需审查更新后使用"
        main_reason = f"相对{base_noun}存在视图更新；按使用场景查看影响。"
    else:
        ip_decision = "READY"
        ip_label = "可接入"
        main_reason = f"未识别到相对{base_noun}的使用影响。"

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

    top_views = ", ".join(
        f"{str(row.get('view') or row.get('file_type') or '-').split('/')[0].strip()}:{row.get('delta_total')}"
        for row in sorted(changed_view_rows, key=lambda row: -_as_int(row.get("delta_total")))[:5]
    )
    if not top_views:
        top_views = "无视图变化"

    must_check = []
    if changed_view_rows:
        must_check.append(f"先看视图变化矩阵：确认相对{base_noun}，哪些视图新增、删除、修改。")
        must_check.append("按使用场景筛选：时序看 Liberty/SPEF/DB，物理实现看 LEF/GDS/OAS/DB，RTL 集成看 Verilog/SystemVerilog，约束看 SDC/UPF/CPF。")
    if summary_only or metadata_only:
        must_check.append("确认轻量证据等级是否满足当前使用场景；摘要级证据（Summary-only）/ 元数据级证据（Metadata-only）是正常证据策略，不自动代表不完整。")
    if p0p1:
        must_check.append(f"查看 {p0p1} 个重点变化文件，但不要把 P0/P1 自动理解成阻塞项。")
    if not must_check:
        must_check.append("当前没有必须确认的基准差异项。")

    return {
        "schema_version": "ip_user_view.v1",
        "source_model": "version_update_detail.v1",
        "ip_use_decision": ip_decision,
        "ip_use_label": ip_label,
        "ip_use_status": _status_from_usage(ip_decision),
        "main_reason": main_reason,
        "release_decision": release_decision,
        "release_label": release_label,
        "release_reason": release_reason,
        "base_label": f"{_copy(BASE_REF_COPY, model.get('base_ref'))} / {model.get('base_version') or '-'}",
        "comparison_label": f"{_copy(SEMANTICS_COPY, model.get('comparison_semantics'))}；{_copy(DELETE_COPY, model.get('delete_semantics'))}",
        "delta_summary": f"新增 {added} / 删除 {removed} / 修改 {changed}",
        "top_view_delta": top_views,
        "delta_status": "INFO" if (added or removed or changed) else "PASS",
        "delta_label": "有更新" if (added or removed or changed) else "无更新",
        "evidence_summary": f"重点审查 {p0p1} / 摘要级 {summary_only} / 元数据级 {metadata_only}",
        "view_delta_rows": view_rows,
        "usage_area_sections": _build_usage_area_sections(view_rows),
        "must_check_items": must_check,
        "non_blocker_note": "普通增量变化、摘要级证据、元数据级证据、P0/P1 不自动构成阻塞；只有基准版、扫描、对比基础证据不可信或明确门禁阻塞项才升级为阻塞。",
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
