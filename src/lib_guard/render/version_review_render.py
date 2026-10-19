from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from lib_guard.package.types import DOC_PACKAGE_TYPES, PARTIAL_PACKAGE_TYPES, normalize_package_type
from lib_guard.render import catalog_render_common as common
from lib_guard.render import product_theme as ui
from lib_guard.view_types import VIEW_LABELS, canonical_view_type, usage_area_for_view, view_label


def _as_mapping(value: Any) -> Mapping[str, Any]:
    """Treat optional model sections as mappings without leaking None into HTML."""
    return value if isinstance(value, Mapping) else {}


def _fact_table(facts: list[Mapping[str, Any]]) -> str:
    rows = []
    for fact in facts:
        rows.append(
            "<tr>"
            f"<td>{ui.esc(fact.get('label') or '-')}</td>"
            f"<td>{ui.esc(fact.get('value') or '-')}</td>"
            "</tr>"
        )
    if not rows:
        rows.append("<tr><td colspan='2'><span class='muted'>暂无字段</span></td></tr>")
    return "<table class='compact-table review-group-facts'><thead><tr><th>字段</th><th>值</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>"


def _fact_value(facts: list[Mapping[str, Any]], label: str) -> str:
    for fact in facts:
        if str(fact.get("label") or "") == label:
            return str(fact.get("value") or "-")
    return "-"


def _status_class(status: Any) -> str:
    key = str(status or "").upper()
    if key in {"BLOCKED", "BAD", "ERROR", "FAIL", "FAILED"}:
        return "judgment-bad"
    if key in {"WARNING", "WARN", "USAGE_REVIEW_REQUIRED", "REVIEW", "REVIEW_REQUIRED", "ATTENTION"}:
        return "judgment-warn"
    if key in {"PASS", "READY", "OK"}:
        return "judgment-ok"
    return "judgment-neutral"


def _compact_evidence_label(value: Any) -> str:
    text = str(value or "-").strip()
    lowered = text.lower()
    if "summary-only" in lowered or "摘要级" in text:
        return "摘要检查"
    if "metadata-only" in lowered or "元数据级" in text:
        return "仅检查文件信息"
    if "重点" in text:
        return "需重点核查"
    if text in {"PASS", "完整证据", "内容级证据"}:
        return "内容检查"
    return text


def _compact_evidence_counts(value: Any, *, primary_label: str = "") -> str:
    counts = value if isinstance(value, Mapping) else {}
    parts = []
    for label, count in counts.items():
        number = int(count or 0)
        if number:
            compact_label = _compact_evidence_label(label)
            # The badge already names the dominant evidence level. Repeat only
            # the number in that common case so the cell stays scannable.
            parts.append(str(number) if compact_label == primary_label else f"{compact_label} {number}")
    return f"· {' / '.join(parts)}" if parts else ""


def _change_counts_text(value: Any) -> str:
    counts = value if isinstance(value, Mapping) else {}
    text = (
        f"+{int(counts.get('added') or 0)} / "
        f"-{int(counts.get('removed') or 0)} / "
        f"~{int(counts.get('changed') or 0)}"
    )
    path_count = int(counts.get("path_changed_same_content") or 0)
    if counts.get('unmatched_new') or counts.get('unmatched_base'):
        text += f"；待核对：本版 {int(counts.get('unmatched_new') or 0)} / 基准版 {int(counts.get('unmatched_base') or 0)}"
    return f"{text} / 路径变化且内容相同 {path_count}" if path_count else text


def _simple_table(
    headers: list[str],
    rows: list[str],
    empty: str,
    *,
    table_class: str = "",
    wrap_class: str = "table-wrap",
) -> str:
    if not rows:
        body = f"<tr><td colspan='{len(headers)}' class='empty'>{ui.esc(empty)}</td></tr>"
    else:
        body = "".join(rows)
    table_attr = f" class='{ui.esc(table_class)}'" if table_class else ""
    return (
        f"<div class='{ui.esc(wrap_class)}'>"
        f"<table{table_attr}><thead><tr>"
        + "".join(f"<th>{ui.esc(header)}</th>" for header in headers)
        + "</tr></thead><tbody>"
        + body
        + "</tbody></table></div>"
    )


def _view_delta_items(ip_model: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Return only facts that change the IP user's review decision."""
    items: list[Mapping[str, Any]] = []
    first_version = str(ip_model.get("review_mode") or "").lower() == "first_version"
    for item in ip_model.get("view_rows", []) or []:
        if not isinstance(item, Mapping):
            continue
        has_change = int(item.get("delta_total") or 0) > 0
        has_path_change = int(item.get("path_changed_same_content") or 0) > 0
        has_delivery = int(item.get("delivery_count") or 0) > 0 or int(item.get("current_count") or 0) > 0
        needs_classification = (
            str(item.get("view_type") or item.get("file_type") or "").lower() == "unknown"
            and has_delivery
        )
        # A first version has no baseline delta. Its useful output is the
        # package's own view coverage, limited to views actually delivered.
        if not first_version and not has_change and not has_path_change and not needs_classification:
            continue
        if first_version and not has_delivery and not needs_classification:
            continue
        items.append(item)
    return items


def _evidence_href(value: Any, href_base: Path | None) -> str:
    """Keep evidence links portable when the catalog is moved to another host."""
    text = str(value or "")
    if not text or text.startswith(("#", "http://", "https://")):
        return text
    if href_base is None:
        return text.replace("\\", "/")
    try:
        return common.rel_href(href_base, text)
    except (OSError, ValueError, TypeError):
        return text.replace("\\", "/")


def _view_delta_file_evidence(item: Mapping[str, Any], href_base: Path | None = None) -> str:
    full_evidence = _evidence_href(item.get("full_evidence_href"), href_base)
    total_count = int(item.get("total_evidence_count") or 0)
    count_copy = f"查看文件结构（{total_count} 项）" if total_count else "查看文件结构"
    raw_view = str(item.get('view_type') or item.get('file_type') or '')
    file_view = raw_view if raw_view in VIEW_LABELS else canonical_view_type(raw_view)
    links = [f"<a href='#file-structure' class='file-entry-link' data-file-view='{ui.esc(file_view)}' onclick='selectFileTreeView(this.dataset.fileView)'>{ui.esc(count_copy)}</a>"]
    if item.get('unmatched_new') or item.get('unmatched_base'):
        links = [f"<a href='#file-structure' class='file-entry-link' data-file-view='{ui.esc(file_view)}' onclick='selectFileTreeAllView(this.dataset.fileView)'>核对文件列表</a>"]
    if full_evidence:
        links.append(f"<details class='reader-evidence-key'><summary>原始结果</summary><a href='{ui.esc(full_evidence)}' target='_blank'>对比数据（JSON）</a></details>")
    path_examples = [
        example
        for example in item.get("path_change_examples", []) or []
        if isinstance(example, Mapping)
    ]
    path_count = int(item.get("path_changed_same_content") or 0)
    path_detail = ""
    if path_examples:
        rows = "".join(
            "<li>"
            f"<code>{ui.esc(example.get('old') or '-')}</code>"
            " <span aria-hidden='true'>→</span> "
            f"<code>{ui.esc(example.get('new') or '-')}</code>"
            "</li>"
            for example in path_examples
        )
        path_detail = (
            "<details class='inline-file-evidence'>"
            f"<summary>查看路径变化（{path_count}）</summary>"
            f"<ul>{rows}</ul></details>"
        )
    return path_detail + "<span class='file-entry-links'>" + " / ".join(links) + "</span>"


def _view_delta_rows(ip_model: Mapping[str, Any], href_base: Path | None = None) -> list[str]:
    rows: list[str] = []
    first_version = str(ip_model.get("review_mode") or "").lower() == "first_version"
    for item in _view_delta_items(ip_model):
        delivery_count = int(item.get("delivery_count") or item.get("current_count") or 0)
        evidence = _compact_evidence_label(item.get("evidence_level"))
        if first_version and evidence == "无变化":
            evidence = "扫描证据"
        status_code = str(item.get("status") or "")
        status_label = str(item.get("status_label") or ui.status_label(status_code) or "待确认")
        if status_label == '需确认匹配':
            status_label = '待核对文件'
        status_html = ui.badge(status_code or "INFO", status_label)
        evidence_counts = item.get("evidence_counts") if isinstance(item.get("evidence_counts"), Mapping) else {}
        evidence_count_text = _compact_evidence_counts(evidence_counts, primary_label=evidence)
        evidence_count_html = f"<small class='evidence-counts'>{ui.esc(evidence_count_text)}</small>" if evidence_count_text else ""
        matrix_view = str(item.get('view_type') or item.get('file_type') or '')
        matrix_view = matrix_view if matrix_view in VIEW_LABELS else canonical_view_type(matrix_view)
        selected_checks = [row for row in ip_model.get('representative_files', []) or []
                           if canonical_view_type(row.get('file_type')) == matrix_view]
        check_html = ''
        if selected_checks:
            row = selected_checks[0]
            scope = '仅所选文件；' + ('未检出差异' if row.get('result') == 'SAME' else '检出字段变化')
            if row.get('freshness') != '文件状态未改变':
                scope = '所选文件结果需重新核查'
            check_html = f"<div class='selected-file-check'><a href='#file-checks'>已保存所选文件核查</a><br><small>{ui.esc(scope)}</small></div>"
        raw_view_type = str(item.get("view_type") or item.get("file_type") or "").strip().lower()
        normalized_view_type = (
            raw_view_type
            if raw_view_type in VIEW_LABELS
            else canonical_view_type(raw_view_type)
        )
        has_canonical_view = raw_view_type in VIEW_LABELS or normalized_view_type != "other"
        display_view = view_label(normalized_view_type) if has_canonical_view else str(item.get("view") or raw_view_type or "-")
        usage = (
            usage_area_for_view(normalized_view_type)
            if has_canonical_view
            else str(item.get("usage_area") or "")
        )
        display_view_html = ui.esc(display_view)
        usage_html = f"<span class='view-use'>{ui.esc(usage)}</span>" if usage else ""
        change_kinds = []
        if int(item.get("added") or 0):
            change_kinds.append("added")
        if int(item.get("removed") or 0):
            change_kinds.append("removed")
        if int(item.get("changed") or 0):
            change_kinds.append("changed")
        if int(item.get("unmatched_new") or 0):
            change_kinds.append("unmatched")
        if int(item.get("unmatched_base") or 0):
            change_kinds.append("unmatched")
        if int(item.get("path_changed_same_content") or 0):
            change_kinds.append("path")
        change_kind_text = " ".join(change_kinds) or "current"
        view_search_text = f"{display_view} {usage} {raw_view_type}".strip().lower()
        def compact_count(value: Any, kind: str, prefix: str, label: str) -> str:
            number = int(value or 0)
            if not number:
                return ""
            return (
                f"<span class='delta-compact-count {kind}' title='{ui.esc(label)} {number}'>"
                f"<b>{ui.esc(prefix)}{number}</b><small>{ui.esc(label)}</small></span>"
            )

        delta_summary = (
            "<div class='delta-delivery-count'>"
            f"<b>{delivery_count}</b><span>{'交付' if first_version else '本版'}</span>"
            + (f"<small>基准 {int(item['base_count'])}</small>" if item.get('base_count') is not None and not first_version else '')
            +
            "</div>"
            "<div class='delta-compact-counts'>"
            + compact_count(item.get("added"), "added", "+", "新增")
            + compact_count(item.get("removed"), "removed", "-", "删除")
            + compact_count(item.get("changed"), "changed", "~", "修改")
            + ("<div class='delta-unverified'><b>待核对</b><span>"
               + " / ".join(f"{label} {int(item.get(key) or 0)}" for key, label in
                            (("unmatched_new", "本版"), ("unmatched_base", "基准版")) if item.get(key))
               + "</span></div>" if item.get("unmatched_new") or item.get("unmatched_base") else "")
            + compact_count(
                item.get("path_changed_same_content"),
                "path-changed",
                "↔",
                "路径变化且内容相同",
            )
            + "</div>"
        )

        rows.append(
            f"<tr data-view-type='{ui.esc(normalized_view_type)}'"
            f" data-view-label='{ui.esc(display_view)}'"
            f" data-view-search='{ui.esc(view_search_text)}'"
            f" data-change-kinds='{ui.esc(change_kind_text)}'"
            f" data-has-change='{'1' if change_kinds else '0'}'>"
            f"<td><b>{display_view_html}</b>{usage_html}</td>"
            f"<td class='delta-summary-cell'>{delta_summary}</td>"
            f"<td><div class='evidence-line'><span class='evidence-level'>{ui.esc(evidence)}</span>{evidence_count_html}</div><div class='evidence-status'>{status_html}</div></td>"
            f"<td>{_view_delta_file_evidence(item, href_base)}{check_html}</td>"
            "</tr>"
        )
    return rows


def _view_delta_filter_bar(view_items: list[Mapping[str, Any]], *, first_version: bool = False) -> str:
    """Render filters from the same view rows that feed the matrix."""
    view_options: list[tuple[str, str]] = []
    seen_views: set[str] = set()
    totals = {"added": 0, "removed": 0, "changed": 0, "unmatched": 0, "path": 0}
    for item in view_items:
        raw_type = str(item.get("view_type") or item.get("file_type") or "other").strip().lower()
        view_type = raw_type if raw_type in VIEW_LABELS else canonical_view_type(raw_type)
        label = view_label(view_type) if view_type in VIEW_LABELS else str(item.get("view") or raw_type or "其他证据")
        if view_type not in seen_views:
            seen_views.add(view_type)
            view_options.append((view_type, label))
        for key in totals:
            if key == "path":
                totals[key] += int(item.get("path_changed_same_content") or 0)
            elif key == "unmatched":
                totals[key] += int(item.get("unmatched_new") or 0) + int(item.get("unmatched_base") or 0)
            else:
                totals[key] += int(item.get(key) or 0)

    change_options = [
        ("added", f"新增（{totals['added']}）"),
        ("removed", f"删除（{totals['removed']}）"),
        ("changed", f"修改（{totals['changed']}）"),
    ]
    if totals["path"]:
        change_options.append(("path", f"路径变化且内容相同（{totals['path']}）"))
    if totals["unmatched"]:
        change_options.append(("unmatched", "待核对文件"))
    view_select_options = "<option value='all'>全部视图</option>" + "".join(
        f"<option value='{ui.esc(value)}'>{ui.esc(label)}</option>"
        for value, label in sorted(view_options, key=lambda item: item[1])
    )
    change_select_options = "<option value='all'>全部变化</option>" + "".join(
        f"<option value='{ui.esc(value)}'>{ui.esc(label)}</option>"
        for value, label in change_options
    )
    summary_chips = "".join(
        f"<span class='view-delta-total {kind}'><b>{count}</b>{label}</span>"
        for kind, count, label in (
            ("added", totals["added"], "新增"),
            ("removed", totals["removed"], "删除"),
            ("changed", totals["changed"], "修改"),
        )
        if count
    )
    if totals["unmatched"]:
        new_count = sum(int(row.get('unmatched_new') or 0) for row in view_items)
        base_count = sum(int(row.get('unmatched_base') or 0) for row in view_items)
        summary_chips += f"<span class='view-delta-total unmatched'>待核对：本版 {new_count} / 基准版 {base_count}</span>"
    if totals["path"]:
        summary_chips += f"<span class='view-delta-total path-changed'><b>{totals['path']}</b>路径变化且内容相同</span>"
    if not summary_chips:
        summary_chips = "<span class='view-delta-total neutral'><b>0</b>文件变化</span>"
    return (
        "<div class='view-delta-filter-bar' data-view-delta-filter>"
        "<div class='view-delta-filter-head'><b>筛选变化</b>"
        "<span>选择视图和变化类型，查看对应文件。</span></div>"
        "<div class='view-delta-filter-controls'>"
        "<label class='view-delta-search'><span>搜索</span>"
        "<input type='search' data-view-search placeholder='搜索视图、用途或类型' oninput='filterViewDelta()'></label>"
        + ("<label class='view-delta-select'><span>变化类型</span>"
           f"<select data-change-filter onchange='filterViewDelta()'>{change_select_options}</select></label>" if not first_version else "")
        + "<label class='view-delta-select'><span>视图类型</span>"
        f"<select data-view-type-filter onchange='filterViewDelta()'>{view_select_options}</select></label>"
        + ("<label class='view-delta-check'><input type='checkbox' data-only-changes onchange='filterViewDelta()'>仅显示有变化</label>" if not first_version else "")
        + "<button type='button' class='btn secondary' data-reset-view-delta onclick='resetViewDeltaFilters()'>清除筛选</button>"
        "<span class='view-delta-filter-count' data-view-delta-count aria-live='polite'></span>"
        "</div>"
        + (f"<div class='view-delta-totals' aria-label='变化汇总'>{summary_chips}</div>" if not first_version else "")
        + "</div>"
    )


def _pending_fact_list(ip_model: Mapping[str, Any]) -> str:
    rows: list[str] = []
    for item in ip_model.get("pending_fact_items", []) or []:
        if not isinstance(item, Mapping):
            continue
        rows.append(
            "<div class='context-row'>"
            f"<b>{ui.esc(item.get('label') or '待确认事实')}</b>"
            f"<em>{ui.esc(item.get('summary') or '-')}</em>"
            "</div>"
        )
    return "<div class='context-list pending-fact-list'>" + "".join(rows) + "</div>"


def _baseline_only_note(ip_model: Mapping[str, Any]) -> str:
    count = sum(int(item.get("baseline_only_count") or 0) for item in ip_model.get("view_rows", []) or [] if isinstance(item, Mapping))
    if not count:
        return ""
    return f"<div class='scope-note'>基准中另有 {count} 个文件未随本包交付，未计为删除。</div>"


def render_ip_user_view(
    ip_model: Mapping[str, Any],
    *,
    href_base: Path | None = None,
    show_pending: bool = True,
) -> str:
    if not ip_model:
        return "<div class='muted-box'>暂无 IP 使用者视图模型。</div>"
    # View deltas already have a dedicated row above. Keep this list for facts
    # that require a separate decision, such as missing base or real deletion.
    pending = [
        item
        for item in ip_model.get("pending_fact_items", []) or []
        if isinstance(item, Mapping) and str(item.get("kind") or "").upper() != "VIEW_DELTA"
    ]
    pending_html = ""
    if pending and show_pending:
        pending_html = "<div class='pending-facts'><b>需确认</b>" + _pending_fact_list({"pending_fact_items": pending}) + "</div>"
    view_items = _view_delta_items(ip_model)
    path_change_legend = (
        "<span><i class='legend-dot path-changed'></i>路径变化且内容相同</span>"
        if any(int(item.get("path_changed_same_content") or 0) for item in view_items)
        else ""
    )
    unmatched_legend = (
        "<span><i class='legend-dot unmatched'></i>待核对</span>"
        if any(int(item.get("unmatched_new") or 0) or int(item.get("unmatched_base") or 0) for item in view_items)
        else ""
    )
    first_version = str(ip_model.get("review_mode") or "").lower() == "first_version"
    delta_toolbar = (
        "<div class='view-delta-toolbar'>"
        "<div><b>本次变化</b></div>"
        "<div class='delta-legend' aria-label='变化类型图例'>"
        "<span><i class='legend-dot current'></i>当前文件</span>"
        "<span><i class='legend-dot added'></i>新增</span>"
        "<span><i class='legend-dot removed'></i>删除</span>"
        "<span><i class='legend-dot changed'></i>修改</span>"
        f"{unmatched_legend}"
        f"{path_change_legend}"
        "</div></div>"
    )
    if first_version:
        delta_toolbar = "<div class='view-delta-toolbar'><b>本次交付</b></div>"
    scroll_note = (
        f"<div class='view-delta-scroll-note'>共 {len(view_items)} 个视图；表格区域可滚动查看全部视图。</div>"
        if len(view_items) > 3
        else ""
    )
    decision = _as_mapping(ip_model.get("decision"))
    change_summary = _as_mapping(ip_model.get("change_summary"))
    blocked_without_diff = (
        str(decision.get("status") or "").upper() == "BLOCKED"
        and str(change_summary.get("status") or "").upper() in {"UNKNOWN", "DIFF_NOT_RUN", "NO_DIFF_SUMMARY"}
    )
    empty_copy = "对比证据尚未完成，不能据此判断无变化。" if blocked_without_diff else "没有需要关注的视图变化。"
    return (
        "<div class='ip-user-view'>"
        + delta_toolbar
        + _view_delta_filter_bar(view_items, first_version=first_version)
        + scroll_note
        + _simple_table(
            ["视图 / 用途", "交付 / 变化", "证据 / 状态", "文件入口"],
            _view_delta_rows(ip_model, href_base),
            empty_copy,
            table_class="view-delta-table",
            wrap_class="table-wrap view-delta-scroll",
        )
        + "<div class='view-delta-filter-empty' data-view-delta-filter-empty hidden>当前筛选没有匹配的视图；请清除筛选或更换条件。</div>"
        + _baseline_only_note(ip_model)
        + ("<p class='scope-note'>待核对：尚未确定两版文件的对应关系，不计为新增或删除；本版与基准版分别计数。</p>" if unmatched_legend else "")
        + "<details class='reader-evidence-key'><summary>检查范围说明</summary><p>摘要检查：使用解析摘要核对部分字段，不等于逐字核对全文。仅检查文件信息：未确认内容是否相同。代表文件核查只覆盖选定文件，不代表整个视图通过。</p></details>"
        + pending_html
        + "</div>"
    )


def _report_value(value: Any, fallback: str = "-") -> str:
    if value is None or value == "":
        return fallback
    if isinstance(value, (list, tuple, set)):
        return "、".join(str(item) for item in value) or fallback
    text = str(value)
    return {
        "NEEDS_BASE_CONFIRM": "待确认基准版",
        "DIFF_NOT_RUN": "尚未生成对比",
        "NO_DIFF_SUMMARY": "缺少对比摘要",
        "BLOCKED": "阻塞",
        "INCOMPLETE": "证据不完整",
        "STALE": "证据已过期",
        "PASS": "通过",
        "RECONCILED": "已核对",
        "NOT_AVAILABLE": "不适用",
        "UNKNOWN_PACKAGE": "未知包类型",
        "recorded_base": "对比记录基准",
        "current_effective": "当前有效版",
        "previous_effective": "上一有效版",
        "adjacent_fallback": "相邻上一版回退",
        "review_window": "审查窗口",
        "ADDED": "新增", "REMOVED": "删除", "CHANGED": "修改",
        "UNMATCHED_NEW": "本版待核对", "UNMATCHED_BASE": "基准版待核对",
        "BASELINE_ONLY": "本包未交付", "full": "全量对比", "incremental": "增量对比",
        "FULL_PACKAGE": "完整包", "PARTIAL_UPDATE": "增量包", "HOTFIX": "紧急修订", "DOC_UPDATE": "文档更新",
        "NEEDS_CLASSIFICATION": "类型待确认", "NONE": "无", "UNKNOWN": "未确定",
        "NOT_SCANNED": "尚未扫描", "SCAN_PASS": "扫描通过", "SCAN_EMPTY": "未获得交付文件",
        "SCANNED": "已扫描", "SAME": "未检出差异", "FIRST_VERSION_REVIEW": "首版交付",
    }.get(text, text)


def _required_view_evidence_table(items: list[Mapping[str, Any]]) -> str:
    items = [item for item in (items or []) if isinstance(item, Mapping)]
    rows = []
    level_labels = {
        "parsed_required": "必须解析",
        "parsed_preferred": "优先解析",
        "metadata_required": "仅登记元数据",
        "doc_review_required": "人工审阅文档",
        "manual_review": "人工审查",
        "pass_through_allowed": "未纳入自动校验",
    }
    status_labels = {"PASS": "满足", "BLOCK": "未满足", "WARNING": "待人工确认", "INFO": "提示"}
    for item in items:
        paths = [str(path) for path in item.get("incomplete_files", []) or []]
        remaining = max(0, int(item.get("incomplete_file_count") or 0) - len(paths))
        path_text = "、".join(paths) or "无"
        if remaining:
            path_text += f" 等 {remaining} 个文件"
        total = int(item.get("total") or 0)
        satisfied = int(item.get("satisfied") or 0)
        rows.append(
            "<tr>"
            f"<td>{ui.esc(view_label(item.get('view')))}</td>"
            f"<td>{ui.esc(level_labels.get(str(item.get('validation_level')), str(item.get('validation_level') or '-')))}</td>"
            f"<td>{ui.esc(status_labels.get(str(item.get('status')), str(item.get('status') or '-')))}</td>"
            f"<td>{satisfied} / {total}</td>"
            f"<td>{ui.esc(path_text)}</td>"
            "</tr>"
        )
    return ui.table(
        ["必需视图", "校验方式", "结果", "满足文件 / 总数", "未完成文件（最多列出 20 个）"],
        rows,
        "当前策略没有必需视图。",
    )


def _delivery_source_label(value: Any) -> str:
    return {
        "explicit_scan_metadata": "显式扫描元数据",
        "filename_or_path_hint": "文件名/目录提示（尚未确认）",
        "none": "未提供",
    }.get(str(value or "none"), "来源待确认")


def _report_kv_rows(items: list[tuple[str, Any]]) -> list[str]:
    return [
        f"<tr><th>{ui.esc(label)}</th><td>{ui.esc(_report_value(value))}</td></tr>"
        for label, value in items
    ]


def render_review_report(report: Mapping[str, Any]) -> str:
    """Render the bounded formal report below the IP-user first screen."""
    if not report:
        return ""
    base = _as_mapping(report.get("base_analysis"))
    delivery = _as_mapping(report.get("delivery_analysis"))
    overlay = normalize_package_type(delivery.get("package_type")) in PARTIAL_PACKAGE_TYPES | DOC_PACKAGE_TYPES
    delta = _as_mapping(report.get("view_delta_analysis"))
    focus = _as_mapping(report.get("focus_file_analysis"))
    unknown = _as_mapping(report.get("unknown_analysis"))
    evidence = _as_mapping(report.get("evidence_assessment"))
    reconciliation = _as_mapping(delta.get("evidence_reconciliation"))
    delta_rows = []
    for row in delta.get("rows", []) or []:
        if not isinstance(row, Mapping):
            continue
        delta_rows.append(
            "<tr>"
            f"<td><b>{ui.esc(row.get('label') or row.get('view_type') or row.get('file_type') or '-')}</b></td>"
            f"<td>{ui.esc(row.get('delivery_count') or row.get('current_count') or 0)}</td>"
            f"<td>{ui.esc(_change_counts_text(row))}</td>"
            f"<td>{ui.esc(row.get('evidence_level') or row.get('status_label') or '-')}</td>"
            "</tr>"
        )
    focus_rows = []
    for item in focus.get("items", []) or []:
        if not isinstance(item, Mapping):
            continue
        focus_rows.append(
            "<tr>"
            f"<td>{ui.esc(item.get('review_lane') or '-')}</td>"
            f"<td>{ui.esc(_report_value(item.get('display_change') or item.get('change')))}</td>"
            f"<td><code>{ui.esc(item.get('path') or '-')}</code></td>"
            f"<td>{ui.esc(_compact_evidence_label(item.get('evidence_mode')))}</td>"
            "</tr>"
        )
    question_rows = [f"<li>{ui.esc(item)}</li>" for item in report.get("open_questions", []) or []]
    action_rows = [f"<li>{ui.esc(item)}</li>" for item in report.get("recommended_actions", []) or []]
    report_parts = ["<div class='review-report-grid'>"]
    report_parts.append(ui.panel("对比范围", "基准版本、对比范围及选择依据。", ui.table(["字段", "值"], _report_kv_rows([
        ("状态", base.get("status")), ("基准来源", base.get("base_ref")), ("基准版本", base.get("base_version")),
        ("目标版本", base.get("target_version")), ("对比语义", base.get("comparison_semantics")), ("说明", base.get("reason")),
    ]))))
    report_parts.append(ui.panel("交付分析", (
        "这里检查本包范围；未交付视图需从有效组合核对继承来源。" if overlay else
        "逐项显示策略要求和对应证据；元数据登记不代表内容解析通过。"
    ), ui.table(["字段", "值"], _report_kv_rows([
        ("状态", delivery.get("status")), ("包类型", delivery.get("package_type")), ("交付文件", delivery.get("file_count")),
        ("必需视图", f"{delivery.get('required_present') or 0} / {delivery.get('required_total') or 0}"),
        ("本包未交付视图" if overlay else "缺失视图", delivery.get("missing_views")),
        ("必需模式", delivery.get("required_modes") or "未配置"),
        ("模式覆盖", f"已确认：{delivery.get('observed_modes') or '无'}；路径提示待确认：{delivery.get('hinted_required_modes') or '无'}；缺失：{delivery.get('missing_modes') or '无'}；来源：{_delivery_source_label(delivery.get('mode_evidence_source'))}"),
        ("必需工艺角", delivery.get("required_corners") or "未配置"),
        ("工艺角覆盖", f"已确认：{delivery.get('observed_corners') or '无'}；路径提示待确认：{delivery.get('hinted_required_corners') or '无'}；缺失：{delivery.get('missing_corners') or '无'}；来源：{_delivery_source_label(delivery.get('corner_evidence_source'))}"),
        ("交付要求状态", delivery.get("requirement_status")),
        ("组合", delivery.get("package_composition")),
    ])) + "<h4>必需视图逐文件证据</h4>" + _required_view_evidence_table(delivery.get("view_evidence", []))))
    report_parts.append("</div><div class='review-report-grid'>")
    totals = _as_mapping(delta.get("totals"))
    reconciliation_checks = _as_mapping(reconciliation.get("checks"))
    reconciliation_text = (
        f"证据对账：{_report_value(reconciliation.get('status'))}；"
        f"文件变化证据 {_change_counts_text(reconciliation.get('file_diff_items'))} → "
        f"视图变化矩阵 {_change_counts_text(reconciliation.get('view_matrix'))}；"
        f"重点文件是变化子集：{ui.esc('是' if reconciliation_checks.get('focus_files_are_file_diff_subset') else '否')}；"
        f"文件树状态已核对：{ui.esc('是' if reconciliation_checks.get('file_tree_status_matches_file_diff') else '否')}。"
    )
    report_parts.append(ui.panel("视图变化分析", "按统一视图类型汇总；总计与视图行必须可核对。", ui.table(
        ["视图", "交付数量", "变化分类", "证据"], delta_rows, "当前没有可用视图变化。"
    ) + f"<p class='report-reconcile'>总计：{ui.esc(_change_counts_text(totals))}；{ui.esc(delta.get('reconciliation') or '-')}</p>"
    + f"<p class='report-reconcile'>{reconciliation_text}</p>"))
    focus_table = (
        "<div class='report-focus-scroll' data-focus-scroll='true'>"
        + ui.table(["级别", "变化", "路径", "证据"], focus_rows, "没有重点文件。")
        + "</div>"
    )
    report_parts.append(ui.panel(
        "重点文件分析",
        "",
        focus_table
        + f"<p class='report-reconcile'>重点文件 {ui.esc(focus.get('count') or 0)} 个，当前展示 {ui.esc(focus.get('shown_count') or 0)} 个。</p>",
    ))
    report_parts.append("</div><div class='review-report-grid'>")
    report_parts.append(ui.panel("未知项与证据评估", "未知文件和证据新鲜度是需要明确的限制条件。", ui.table(["字段", "值"], _report_kv_rows([
        ("未知文件", unknown.get("count")), ("未知状态", unknown.get("status")), ("代表路径", unknown.get("examples")),
        ("证据状态", evidence.get("status")), ("扫描状态", evidence.get("scan_status")),
        ("对比状态", evidence.get("diff_status")),
    ]))))
    report_parts.append(ui.panel("待确认与建议动作", "这是报告层的未决事项，不自动等同于阻塞。", (
        "<div class='report-list'><b>待确认</b><ul>" + ("".join(question_rows) or "<li>暂无</li>") + "</ul>"
        "<b>建议动作</b><ul>" + ("".join(action_rows) or "<li>暂无</li>") + "</ul></div>"
    )))
    report_parts.append("</div>")
    report_body = "".join(report_parts)
    return (
        "<style>.review-report-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;margin-bottom:14px}.review-report-grid .panel{margin-bottom:0;box-shadow:none;border-radius:9px}.review-report-grid .panel-head{padding:12px 14px}.review-report-grid .panel-body{padding:12px 14px}.report-focus-scroll{max-height:360px;overflow:auto;scrollbar-gutter:stable;border:1px solid var(--line);border-radius:8px;background:var(--surface)}.report-focus-scroll .table-wrap{border:0;border-radius:0;overflow:visible}.report-focus-scroll table{min-width:560px}.report-focus-scroll th{position:sticky;top:0;z-index:1;background:var(--surface-2)}.report-focus-scroll td code{white-space:nowrap}.report-reconcile{margin:10px 0 0;color:var(--muted);font-size:12px}.report-list ul{margin:6px 0 14px;padding-left:22px;color:var(--muted)}.report-list li{margin:3px 0}@media(max-width:900px){.review-report-grid{grid-template-columns:1fr}}</style>"
        '<details data-section="review-report" class="panel collapsible review-report-fold">'
        '<summary class="panel-head"><div><h2>完整审查报告</h2><p>交付范围、重点文件、检查限制与数据核对明细。</p></div>'
        '<div class="panel-actions"><span class="chevron">⌄</span></div></summary>'
        f"<div class='panel-body'>{report_body}</div></details>"
    )


def _package_root_callout(group: Mapping[str, Any], facts: list[Mapping[str, Any]]) -> str:
    if group.get("key") != "package_root_migration" or str(group.get("status") or "").upper() == "PASS":
        return ""
    old_root = _fact_value(facts, "旧包根")
    new_root = _fact_value(facts, "新包根")
    matched = _fact_value(facts, "逻辑路径匹配")
    moved = _fact_value(facts, "文件级一一匹配")
    old_count = _fact_value(facts, "旧包根文件数")
    new_count = _fact_value(facts, "新包根文件数")
    package_counts = ""
    if old_count not in {"", "-", "0"} or new_count not in {"", "-", "0"}:
        package_counts = f"旧包根内 {ui.esc(old_count)} 个文件，新包根内 {ui.esc(new_count)} 个文件；"
    return (
        "<div class='quality-note path-restructure-note'>"
        f"<b>包装目录变化</b> 旧包根：<code>{ui.esc(old_root)}</code>，"
        f"新包根：<code>{ui.esc(new_root)}</code>；逻辑路径匹配 {ui.esc(matched)}，"
        f"{package_counts}文件级一一匹配 {ui.esc(moved)}。此信息用于解释上一版对比，不默认作为 IP 使用阻塞。"
        "</div>"
    )


def render_version_review_groups(review_model: Mapping[str, Any]) -> str:
    groups = [group for group in review_model.get("groups", []) or [] if isinstance(group, Mapping)]
    cards = []
    for group in groups:
        facts = [fact for fact in group.get("facts", []) or [] if isinstance(fact, Mapping)]
        cards.append(
            "<section class='review-group-card'>"
            "<div class='review-group-head'>"
            f"<h3>{ui.esc(group.get('label') or '-')}</h3>"
            f"{ui.badge(group.get('status') or 'INFO', group.get('status') or 'INFO')}"
            "</div>"
            f"<p>{ui.esc(group.get('summary') or '-')}</p>"
            + _package_root_callout(group, facts)
            + _fact_table(facts)
            + "</section>"
        )
    if not cards:
        cards.append("<div class='muted-box'>暂无更新详情分组。</div>")
    return (
        "<div class='version-review-model'>"
        "<div class='quality-note'><b>高级审查字段</b> 保留对比范围、包根匹配、文件匹配质量、内容变化和原始审计判断，默认作为证据/管理层信息，不抢占 IP 使用者主线。</div>"
        "<div class='review-group-grid'>"
        + "".join(cards)
        + "</div></div>"
    )
