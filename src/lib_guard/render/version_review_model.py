from __future__ import annotations

from collections import Counter
from typing import Any, Mapping


GROUP_LABELS = ["对比范围", "包根目录迁移", "文件匹配质量", "内容变化", "使用影响"]
STATUS_COPY = {
    "DIFF_NOT_RUN": "尚未生成更新详情；请运行 lg refresh <LIB>。",
    "NEEDS_BASE_CONFIRM": "无法确定 Base；请先确认当前有效版本或上一有效版本。",
    "NO_DIFF_SUMMARY": "找到 diff 输出目录，但缺少 diff_summary.json；请检查 compare artifact。",
    "CHANGED": "已完成比较，有变化。",
    "SAME": "已完成比较，无变化。",
}
BASE_REF_COPY = {
    "current_effective": "当前有效版本",
    "previous_effective": "上一有效版本",
    "latest_effective": "最新有效版本",
    "explicit": "手动指定",
    "adjacent": "相邻版本",
    "NEEDS_BASE_CONFIRM": "待确认 Base",
}
BASE_SOURCE_COPY = {
    "current_effective_ref": "当前有效版本引用",
    "previous_effective_version": "上一有效版本",
    "latest_effective_ref": "最新有效版本引用",
    "explicit": "手动指定",
    "manual": "手动指定",
    "diff_summary": "Diff 记录",
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
    "NEEDS_BASE_CONFIRM": "Base 待确认",
    "NO_DIFF_SUMMARY": "缺少 Diff 摘要",
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
    "release_note_missing": "缺少 release note",
    "review_gate_blocking": "Review Gate 有阻塞项",
    "base_not_confirmed": "Base 未确认",
}
ACTION_COPY = {
    "Review focused file evidence": "审查重点文件证据",
    "Open comparison review": "打开对比审查",
    "Confirm base version": "确认 Base 版本",
    "No action required": "无需动作",
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
                f"{model.get('base_trust_note') or 'Base 和对比口径需要确认。'}"
            ).strip(),
            "facts": _facts(
                [
                    ("Base 来源", _base_source_text(model.get("base_ref"), model.get("base_source"))),
                    ("Base 版本", model.get("base_version") or "-"),
                    ("Target 版本", model.get("target_version") or model.get("version_id") or "-"),
                    ("对比语义", _copy(SEMANTICS_COPY, model.get("comparison_semantics"))),
                    ("删除语义", _copy(DELETE_COPY, model.get("delete_semantics"))),
                    ("Diff 状态", _copy(DIFF_STATUS_COPY, model.get("status"))),
                ]
            ),
        },
        {
            "key": "package_root_migration",
            "label": "包根目录迁移",
            "status": "WARNING" if migration_suspected else "PASS",
            "summary": (
                "疑似重打包 / 目录迁移，需要确认路径变化是否影响脚本引用、flow config、release manifest。"
                if migration_suspected
                else "未识别到包根目录迁移。"
            ),
            "facts": _facts(
                [
                    ("Old root", path_restructure.get("old_root") or "-"),
                    ("New root", path_restructure.get("new_root") or "-"),
                    ("逻辑路径匹配", migration_matched),
                    ("文件级一一匹配", moved),
                    ("Old 包内文件", _as_int(path_restructure.get("old_root_file_count"))),
                    ("New 包内文件", _as_int(path_restructure.get("new_root_file_count"))),
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
                    ("匹配依据", "basename / hash / parser signature / logical path"),
                ]
            ),
        },
        {
            "key": "content_changes",
            "label": "内容变化",
            "status": "WARNING" if p0p1 or blocking_issues else "PASS",
            "summary": (
                f"变化风险：新增 {added} / 删除 {removed} / 修改 {changed}；"
                f"P0/P1={p0p1}，证据分层：{evidence_label}，Summary-only={summary_only}，Metadata-only={metadata_only}。"
            ),
            "facts": _facts(
                [
                    ("新增文件", added),
                    ("删除文件", removed),
                    ("修改文件", changed),
                    ("P0/P1", p0p1),
                    ("证据分层", f"{evidence_label}；摘要级 {summary_only} / metadata-only {metadata_only}"),
                    ("Unknown 文件", unknown_files),
                    ("主要类型", _top_file_types(file_changes)),
                ]
            ),
        },
        {
            "key": "usage_impact",
            "label": "使用影响",
            "status": _status_from_usage(usage_decision),
            "summary": f"使用建议：{usage_text}；原因：{reasons_text}。",
            "facts": _facts(
                [
                    ("使用决策", usage_text),
                    ("Release note", "已发现" if release_notes else "缺失"),
                    ("阻塞问题", blocking_issues),
                    ("主动作", _action_text(model.get("primary_next_action"))),
                ]
            ),
        },
    ]
    return {
        "schema_version": "version_review_model.v1",
        "source_model": "version_update_detail.v1",
        "groups": groups,
    }
