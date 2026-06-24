"""Catalog HTML renderer using the shared Review Navigation theme.

UI policy for the catalog entry page:
- Library Browser is a browser, not a command console.
- Version rows show a compact Chinese summary and only one primary next action.
- Command examples are collected in a lower "命令示例" section instead of being
  repeated inside every row.
- Release status is hidden from normal rows unless the version is explicitly
  related to release evidence/candidate/current alias.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping
import json
import re

from lib_guard.review import build_review_state, build_review_tasks
from lib_guard.review.io import as_file_href, read_json, write_json
from lib_guard.render import product_theme as ui


def _safe(value: Any) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "item")).strip("._")
    return text or "item"


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _version_links(version: Mapping[str, Any]) -> Mapping[str, Any]:
    links = version.get("links") or {}
    return links if isinstance(links, Mapping) else {}


def _href(path: Any) -> str:
    return as_file_href(path) if path else ""


def _status_key(value: Any) -> str:
    return str(value or "UNKNOWN").strip().upper()


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "ok"}


def _short_path(path: Any, limit: int = 72) -> str:
    text = str(path or "-")
    if len(text) <= limit:
        return text
    return "…" + text[-limit:]


def _package_type(version: Mapping[str, Any]) -> str:
    return str(version.get("package_type") or version.get("version_type") or version.get("stage") or "UNKNOWN").upper()


def _package_label(version: Mapping[str, Any]) -> tuple[str, str]:
    pkg = _package_type(version)
    labels = {
        "FULL_PACKAGE": "完整",
        "PARTIAL_UPDATE": "增量",
        "HOTFIX": "热修",
        "DOC_UPDATE": "文档",
        "DOC_ONLY": "文档",
        "UNKNOWN_PACKAGE": "未知",
        "CANDIDATE": "候选",
        "FULL": "完整",
        "DAILY": "日更",
    }
    if pkg not in labels:
        stage = str(version.get("stage") or "").lower()
        if stage == "ad-hoc":
            return "HOTFIX", "热修"
        if stage in {"stable", "final", "initial"}:
            return pkg, stage
    return pkg, labels.get(pkg, ui.status_label(pkg) or pkg)


def _base_full_version(version: Mapping[str, Any]) -> str | None:
    diff = version.get("diff") or {}
    lineage = version.get("lineage") or {}
    for key in ["base_full_version", "base_version"]:
        value = version.get(key)
        if value:
            return str(value)
    for value in [diff.get("cumulative_base_version"), diff.get("base_version"), lineage.get("base_candidate")]:
        if value:
            return str(value)
    return None


def _previous_effective_version(version: Mapping[str, Any]) -> str | None:
    diff = version.get("diff") or {}
    lineage = version.get("lineage") or {}
    for key in ["previous_effective_version", "parent_version"]:
        value = version.get(key)
        if value:
            return str(value)
    for value in [diff.get("adjacent_old_version"), lineage.get("parent_candidate")]:
        if value:
            return str(value)
    return None


def _is_full_baseline(version: Mapping[str, Any]) -> bool:
    pkg = _package_type(version)
    return bool(_truthy(version.get("standalone")) or pkg in {"FULL_PACKAGE", "FULL"})


def _relation_status(version: Mapping[str, Any]) -> str:
    pkg = _package_type(version)
    if _is_full_baseline(version):
        return "FULL_BASELINE"
    base_full = _base_full_version(version)
    prev_eff = _previous_effective_version(version)
    base_required = _truthy(version.get("base_required")) or pkg in {"PARTIAL_UPDATE", "HOTFIX", "DOC_UPDATE", "DOC_ONLY"}
    if base_required and (not base_full or not prev_eff):
        return "NEED_BINDING"
    if prev_eff:
        return "RELATION_OK"
    if bool(version.get("manual_review")):
        return "NEED_BINDING"
    return "RELATION_UNKNOWN"


def _relation_label(status: str) -> str:
    return {
        "FULL_BASELINE": "完整基线",
        "RELATION_OK": "关系OK",
        "NEED_BINDING": "需绑定",
        "RELATION_UNKNOWN": "关系未知",
    }.get(status, status)


def _release_is_visible(version: Mapping[str, Any], lib: Mapping[str, Any] | None = None) -> bool:
    release = _status_key(version.get("release_status"))
    links = _version_links(version)
    version_id = str(version.get("version_id") or version.get("version") or "")
    lib = lib or {}
    current_like = {
        str(lib.get("approved_version") or ""),
        str(lib.get("current_version") or ""),
        str(lib.get("current_effective_version") or ""),
        str(lib.get("release_candidate") or ""),
    }
    explicit = bool(version.get("release_candidate") or version.get("selected_for_release"))
    has_release_evidence = bool(links.get("release_html"))
    release_done_or_blocked = release not in {"", "UNKNOWN", "RELEASE_NOT_CHECKED", "RELEASE_CHECK_REQUIRED", "NOT_APPLICABLE", "NONE"}
    return explicit or has_release_evidence or release_done_or_blocked or bool(version_id and version_id in current_like)


def _scan_label(version: Mapping[str, Any]) -> tuple[str, str]:
    status = _status_key(version.get("scan_status"))
    if status in {"SCANNED", "PASS", "DONE", "FINISHED"}:
        return status, "已扫"
    if status in {"FAILED", "BLOCK", "BLOCKED", "ERROR"}:
        return status, "失败"
    return "NOT_SCANNED", "未扫"


def _file_review_recommendation(version: Mapping[str, Any]) -> dict[str, Any]:
    rec = version.get("file_diff_recommendation") or version.get("file_review") or {}
    if isinstance(rec, Mapping) and rec:
        return dict(rec)
    pair = version.get("pairwise_summary") or {}
    total = int(pair.get("total", 0) or 0)
    done = int(pair.get("done", 0) or 0)
    return {
        "comparison_quality": version.get("comparison_quality") or "NORMAL",
        "recommended_total": total,
        "result_generated": done,
        "needs_run": max(total - done, 0),
        "candidate_total": int(pair.get("candidate_total", 0) or version.get("changed_file_total", 0) or 0),
        "suppressed_total": int(pair.get("suppressed_total", 0) or 0),
    }


def _file_review_text(version: Mapping[str, Any]) -> str:
    rec = _file_review_recommendation(version)
    quality = str(rec.get("comparison_quality") or "NORMAL")
    recommended = int(rec.get("recommended_total", 0) or 0)
    generated = int(rec.get("result_generated", 0) or 0)
    candidates = int(rec.get("candidate_total", 0) or 0)
    if quality.upper() not in {"NORMAL", "PASS", "OK", ""}:
        return f"{ui.status_label(quality)} · 重点 {recommended} · 候选 {candidates}"
    if recommended:
        return f"重点 {recommended} · 已生成 {generated}"
    if candidates:
        return f"候选 {candidates}"
    return "无重点"


def _file_review_status(version: Mapping[str, Any]) -> str:
    rec = _file_review_recommendation(version)
    quality = str(rec.get("comparison_quality") or "NORMAL").upper()
    if quality not in {"NORMAL", "PASS", "OK", ""}:
        return quality
    if int(rec.get("needs_run", 0) or 0):
        return "FILE_DIFF_RECOMMENDED"
    if int(rec.get("result_generated", 0) or 0):
        return "FILE_DIFF_DONE"
    if int(rec.get("recommended_total", 0) or 0):
        return "FILE_DIFF_RECOMMENDED"
    return "PAIRWISE_EMPTY"


def _version_tags(version: Mapping[str, Any]) -> set[str]:
    tags: set[str] = set()
    overall = _status_key(version.get("overall_status"))
    scan = _status_key(version.get("scan_status"))
    diff = _status_key(version.get("diff_status"))
    release = _status_key(version.get("release_status"))
    relation = _relation_status(version)
    if overall in {"BLOCK", "BLOCKED", "FAILED", "ERROR"}:
        tags.add("block")
    if overall in {"REVIEW", "NEEDS_REVIEW", "MANUAL_REVIEW"} or diff in {"DIFF", "CHANGED", "REVIEW_REQUIRED"}:
        tags.add("review")
    if scan in {"NOT_SCANNED", "SCAN_MISSING", "UNKNOWN", ""}:
        tags.add("not_scanned")
    if diff in {"DIFF", "CHANGED", "REVIEW_REQUIRED", "NEEDS_FILE_DIFF"}:
        tags.add("changed")
    rec_status = _file_review_status(version)
    if rec_status in {"FILE_DIFF_RECOMMENDED", "NEEDS_FILE_DIFF"}:
        tags.add("file_review_recommended")
    if relation == "NEED_BINDING" or rec_status in {"NEEDS_BASE_CONFIRM", "LARGE_CHANGE", "DIFF_EXPLOSION", "PATH_RESTRUCTURE"}:
        tags.add("needs_comparison_confirm")
    if release in {"RELEASED", "APPLIED", "PASS"}:
        tags.add("released")
    if not tags:
        tags.add("clear")
    return tags


def _library_tags(lib: Mapping[str, Any]) -> set[str]:
    tags: set[str] = set()
    for version in lib.get("versions", []) or []:
        tags.update(_version_tags(version))
    if not tags:
        tags.add("clear")
    return tags


def _version_display_text(version: Mapping[str, Any]) -> str:
    version_id = str(version.get("version_id") or version.get("version") or "-")
    stage = str(version.get("stage") or "-")
    pkg_status, pkg_label = _package_label(version)
    return f"{version_id} {stage} {pkg_label} {pkg_status} {version.get('raw_path') or ''}"


def _version_primary_action(version: Mapping[str, Any]) -> tuple[str, str, str, bool]:
    links = _version_links(version)
    relation = _relation_status(version)
    version_review = _href(links.get("version_review_html"))
    if relation == "NEED_BINDING":
        return "绑定", version_review, "primary", not bool(version_review)
    if links.get("diff_html"):
        return "差异", _href(links.get("diff_html")), "primary", False
    if links.get("scan_html"):
        return "扫描", _href(links.get("scan_html")), "secondary", False
    if version_review:
        return "详情", version_review, "secondary", False
    return "待处理", "", "secondary", True


def _build_comparisons_for_library(lib: Mapping[str, Any]) -> list[dict[str, Any]]:
    comparisons: list[dict[str, Any]] = []
    versions = list(lib.get("versions", []) or [])
    prev_version = None
    for version in versions:
        links = _version_links(version)
        diff = version.get("diff") or {}
        version_id = version.get("version_id") or version.get("version") or "-"
        base_version = _base_full_version(version) or diff.get("base_version") or diff.get("cumulative_base_version")
        adjacent_old = _previous_effective_version(version) or prev_version
        for mode, old in [("adjacent", adjacent_old), ("base", base_version)]:
            if not old or str(old) == str(version_id):
                continue
            rec = _file_review_recommendation(version)
            comparisons.append({
                "comparison_id": f"{mode}__{old}__{version_id}",
                "library_id": lib.get("library_id"),
                "old_version": old,
                "new_version": version_id,
                "mode": mode,
                "status": version.get("diff_status") or "COMPARE_PENDING",
                "review_level": version.get("overall_status") or version.get("diff_status") or "UNKNOWN",
                "diff_html": _href(links.get("diff_html")),
                "comparison_quality": rec.get("comparison_quality") or "NORMAL",
                "recommended_total": int(rec.get("recommended_total", 0) or 0),
                "result_generated": int(rec.get("result_generated", 0) or 0),
                "needs_run": int(rec.get("needs_run", 0) or 0),
                "candidate_total": int(rec.get("candidate_total", 0) or 0),
                "suppressed_total": int(rec.get("suppressed_total", 0) or 0),
                "release_impact": version.get("release_status") or "RELEASE_CHECK_REQUIRED",
            })
        prev_version = version_id
    return comparisons


def _render_library_diff_timeline(out: Path, lib: Mapping[str, Any]) -> str:
    lib_id = str(lib.get("library_id") or lib.get("display_name") or "library")
    safe = _safe(lib_id)
    html_path = out / "libraries" / safe / "diff_timeline.html"
    comparisons = _build_comparisons_for_library(lib)
    (html_path.parent / "diff_index.json").write_text(json.dumps({
        "schema_version": "library_diff_index.v1",
        "library_id": lib_id,
        "display_name": lib.get("display_name"),
        "comparisons": comparisons,
    }, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    changed = sum(1 for c in comparisons if _status_key(c.get("status")) in {"DIFF", "CHANGED", "REVIEW_REQUIRED", "NEEDS_FILE_DIFF"})
    recommended = sum(int(c.get("recommended_total", 0) or 0) for c in comparisons)
    confirm = sum(1 for c in comparisons if _status_key(c.get("comparison_quality")) not in {"NORMAL", "PASS", "OK", ""})
    candidates = sum(int(c.get("candidate_total", 0) or 0) for c in comparisons)
    rows = [
        "<tr>"
        f"<td><code>{ui.esc(c.get('mode'))}</code></td>"
        f"<td><code>{ui.esc(c.get('old_version'))}</code></td>"
        f"<td><code>{ui.esc(c.get('new_version'))}</code></td>"
        f"<td>{ui.badge(c.get('comparison_quality') or c.get('status'))}</td>"
        f"<td>{ui.esc(c.get('recommended_total', 0))} / 已生成 {ui.esc(c.get('result_generated', 0))}</td>"
        f"<td>{ui.esc(c.get('candidate_total', 0))}</td>"
        f"<td>{ui.button('打开', c.get('diff_html'), 'primary', disabled=not bool(c.get('diff_html')), target='_blank')}</td>"
        "</tr>"
        for c in comparisons
    ]
    body = (
        ui.panel(
            "库级版本链",
            "一个 library 的多版本 comparison 入口。普通用户先看这里，再进入 Selected Diff Review。",
            ui.metric_grid([
                ("版本", len(lib.get("versions", []) or []), "catalog versions", "PASS"),
                ("比较", len(comparisons), "adjacent / base", "PASS" if comparisons else "WARNING"),
                ("有变化", changed, "有变化的 comparison", "WARNING" if changed else "PASS"),
                ("重点文件", recommended, "只统计推荐队列", "WARNING" if recommended else "PASS"),
                ("候选变化", candidates, "大量候选默认折叠", "WARNING" if candidates > recommended else "PASS"),
                ("需确认", confirm, "base / path restructure / large change", "WARNING" if confirm else "PASS"),
            ]) + ui.compact_meta([
                ("Library", lib_id),
                ("Vendor", lib.get("vendor") or "-"),
                ("Path", lib.get("middle_path") or lib.get("library_root") or "-"),
            ]),
        )
        + ui.panel("滑动视图", "横向查看多个 comparison。", ui.comparison_filter_bar() + ui.timeline(comparisons))
        + ui.collapsible_panel(
            "Comparison 明细",
            "定位每次 old → new 的状态、质量和重点文件建议。",
            ui.filterable_table(
                f"cmp-{safe}",
                ["模式", "旧版", "新版", "质量", "重点文件", "候选", "入口"],
                rows,
                "暂无 comparison",
                "筛选 old / new / mode / status",
            ),
            open=True,
        )
    )
    html = ui.review_page_shell(
        f"{lib.get('display_name') or lib_id} / Diff Timeline",
        "DIFF TIMELINE",
        "库级版本变化导航。Scan / Release 是证据页，Selected Diff 和 File Diff 是主要审阅入口。",
        body,
        decision="REVIEW" if changed or recommended or confirm else "PASS",
        nav="<a href='../../index.html'>Catalog</a><a class='active' href='#'>版本链</a><a href='#'>Selected Diff</a>",
        meta=ui.compact_meta([("Library", lib_id), ("Comparisons", len(comparisons)), ("重点", recommended), ("需确认", confirm)]),
    )
    _write_text(html_path, html)
    return str(html_path)


def _latest_full_version(versions: list[Mapping[str, Any]]) -> str:
    for version in reversed(versions):
        if _is_full_baseline(version):
            return str(version.get("version_id") or version.get("version") or "-")
    return "-"


def _latest_effective_version(lib: Mapping[str, Any], versions: list[Mapping[str, Any]]) -> str:
    for key in ["current_effective_version", "approved_version", "current_version"]:
        if lib.get(key):
            return str(lib.get(key))
    for version in reversed(versions):
        if _truthy(version.get("current_effective")):
            return str(version.get("version_id") or version.get("version") or "-")
    return str(versions[-1].get("version_id") or versions[-1].get("version") or "-") if versions else "-"


def _version_row(lib: Mapping[str, Any], version: Mapping[str, Any], latest: Any) -> str:
    version_id = str(version.get("version_id") or version.get("version") or "-")
    is_latest = "1" if str(version_id) == str(latest) else "0"
    tags = ",".join(sorted(_version_tags(version)))
    stage = str(version.get("stage") or "-")
    pkg_status, pkg_label = _package_label(version)
    scan_status, scan_text = _scan_label(version)
    relation = _relation_status(version)
    relation_label = _relation_label(relation)
    file_status = _file_review_status(version)
    base_full = _base_full_version(version) or "?"
    prev_eff = _previous_effective_version(version) or "?"
    label, href, kind, disabled = _version_primary_action(version)
    release_html = f"<span class='release-mini'>{ui.badge(version.get('release_status'), '发布')}</span>" if _release_is_visible(version, lib) else ""
    review_hint = ui.badge(file_status, _file_review_text(version)) if file_status != "PAIRWISE_EMPTY" else ""
    return (
        f"<div class='version-row' data-tags='{ui.esc(tags)}' data-latest='{is_latest}' data-search='{ui.esc(_version_display_text(version))}'>"
        "<div class='version-id-cell'>"
        f"<div class='version-name long-token' title='{ui.esc(version_id)}'>{ui.esc(version_id)}</div>"
        f"<div class='version-path' title='{ui.esc(version.get('raw_path'))}'>{ui.esc(_short_path(version.get('raw_path')))}</div>"
        "</div>"
        "<div class='version-badges'>"
        f"{ui.badge(pkg_status, pkg_label)}{ui.badge(stage, stage)}{ui.badge(scan_status, scan_text)}{ui.badge(relation, relation_label)}{review_hint}{release_html}"
        "</div>"
        "<div class='version-relation'>"
        f"<span><b>基线</b><em title='{ui.esc(base_full)}'>{ui.esc(base_full)}</em></span>"
        f"<span><b>前版</b><em title='{ui.esc(prev_eff)}'>{ui.esc(prev_eff)}</em></span>"
        "</div>"
        f"<div class='version-action'>{ui.button(label, href, kind, disabled=disabled, target='_blank')}</div>"
        "</div>"
    )


def _library_card(out: Path, lib: Mapping[str, Any]) -> str:
    versions = list(lib.get("versions", []) or [])
    latest = lib.get("latest_version") or (versions[-1].get("version_id") if versions else "-")
    latest_full = _latest_full_version(versions)
    latest_effective = _latest_effective_version(lib, versions)
    status = lib.get("overall_status") or "UNKNOWN"
    vendor = str(lib.get("vendor") or "Unknown")
    middle = str(lib.get("middle_path") or lib.get("library_root") or "-")
    stages = sorted({str(v.get("stage") or "unknown") for v in versions})
    tags = _library_tags(lib)
    timeline_path = _render_library_diff_timeline(out, lib)
    need_bind = sum(1 for v in versions if _relation_status(v) == "NEED_BINDING")
    not_scanned = sum(1 for v in versions if "not_scanned" in _version_tags(v))
    changed = sum(1 for v in versions if "changed" in _version_tags(v))
    version_rows = "".join(_version_row(lib, v, latest) for v in reversed(versions))
    actions = ui.action_strip([
        ui.button("版本链", _href(timeline_path), "primary", target="_blank"),
        ui.button("最新扫描", _href((versions[-1].get("links") or {}).get("scan_html") if versions else ""), disabled=not versions or not (versions[-1].get("links") or {}).get("scan_html"), target="_blank"),
        ui.button("最新差异", _href((versions[-1].get("links") or {}).get("diff_html") if versions else ""), disabled=not versions or not (versions[-1].get("links") or {}).get("diff_html"), target="_blank"),
    ])
    return (
        f"<section class='library-card' data-overall='{ui.esc(status)}' data-vendor='{ui.esc(vendor)}' data-stages='{ui.esc(','.join(stages))}' data-tags='{ui.esc(','.join(sorted(tags)))}'>"
        "<div class='library-main'>"
        f"<div><div class='library-title long-token' title='{ui.esc(lib.get('display_name') or lib.get('library_name') or lib.get('library_id'))}'>{ui.esc(lib.get('display_name') or lib.get('library_name') or lib.get('library_id'))}</div><div class='library-path' title='{ui.esc(lib.get('library_id'))}'>{ui.esc(lib.get('library_id') or '-')}</div></div>"
        f"<div><b>{ui.esc(vendor)}</b><div class='library-path' title='{ui.esc(middle)}'>{ui.esc(_short_path(middle, 48))}</div></div>"
        f"<div><span class='muted'>完整基线</span><br><b title='{ui.esc(latest_full)}'>{ui.esc(latest_full)}</b></div>"
        f"<div><span class='muted'>当前有效</span><br><b title='{ui.esc(latest_effective)}'>{ui.esc(latest_effective)}</b></div>"
        "<div class='library-status'>"
        f"{ui.badge(status)}<span class='browser-count'>{len(versions)} 版</span>{ui.quiet_badge('NEED_BINDING', need_bind)}{ui.quiet_badge('NOT_SCANNED', not_scanned)}{ui.quiet_badge('CHANGED', changed)}{actions}"
        "</div></div>"
        f"<details class='version-drawer' {'open' if need_bind else ''}><summary>版本明细 / 默认只展开需绑定库</summary><div class='version-list'>{version_rows or '<div class=\'catalog-empty\'>暂无 version</div>'}</div></details>"
        "</section>"
    )


def _group_libraries(libraries: list[Mapping[str, Any]]) -> dict[tuple[str, str], list[Mapping[str, Any]]]:
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for lib in libraries:
        key = (str(lib.get("vendor") or "Unknown"), str(lib.get("middle_path") or lib.get("library_root") or "-"))
        grouped.setdefault(key, []).append(lib)
    return dict(sorted(grouped.items(), key=lambda kv: (kv[0][0], kv[0][1])))


def _library_browser(out: Path, state: Mapping[str, Any]) -> str:
    libraries = list(state.get("libraries", []) or [])
    groups = _group_libraries(libraries)
    group_html = []
    for (vendor, middle), libs in groups.items():
        cards = "".join(_library_card(out, lib) for lib in libs)
        has_attention = any((_library_tags(lib) & {"review", "block", "file_review_pending", "file_review_recommended", "not_scanned", "needs_comparison_confirm"}) for lib in libs)
        group_html.append(
            f"<details class='library-group' {'open' if has_attention else ''}>"
            f"<summary><div class='library-group-title'><b>{ui.esc(vendor)}</b><span>{ui.esc(middle)}</span></div><span class='browser-count'>{len(libs)} 库</span></summary>"
            f"<div class='library-group-body'>{cards}</div></details>"
        )
    return "<div class='library-browser' data-catalog-browser data-status-filter='all'>" + ("".join(group_html) or "<div class='catalog-empty'>暂无 library</div>") + "</div>"


def _catalog_filter_panel(state: Mapping[str, Any]) -> str:
    libraries = list(state.get("libraries", []) or [])
    vendors = sorted({str(lib.get("vendor") or "Unknown") for lib in libraries})
    stages = sorted({str(v.get("stage") or "unknown") for lib in libraries for v in (lib.get("versions", []) or [])})
    vendor_opts = "<option value='all'>全部 Vendor</option>" + "".join(f"<option value='{ui.esc(v)}'>{ui.esc(v)}</option>" for v in vendors)
    stage_opts = "<option value='all'>全部 Stage</option>" + "".join(f"<option value='{ui.esc(s)}'>{ui.esc(s)}</option>" for s in stages)
    chips = [("all", "全部"), ("needs_comparison_confirm", "需绑定"), ("not_scanned", "未扫"), ("changed", "有变化"), ("file_review_recommended", "重点"), ("review", "审阅"), ("block", "阻塞"), ("released", "已发布"), ("clear", "正常")]
    chip_html = "".join(f"<button type='button' class='filter-chip {'active' if k == 'all' else ''}' data-catalog-status-chip='{k}' onclick=\"setCatalogStatusFilter('{k}', this)\">{ui.esc(v)}</button>" for k, v in chips)
    body = (
        "<div class='search'><span>搜索</span><input id='catalog-search' type='search' placeholder='库 / 版本 / vendor / path' oninput='filterCatalogBrowser()'></div>"
        "<div class='filter-group-title'>Vendor</div>" + f"<select id='catalog-vendor' onchange='filterCatalogBrowser()'>{vendor_opts}</select>"
        "<div class='filter-group-title'>Stage</div>" + f"<select id='catalog-stage' onchange='filterCatalogBrowser()'>{stage_opts}</select>"
        "<label style='display:flex;gap:8px;align-items:center;margin:10px 0;color:#667085;font-size:13px'><input id='catalog-latest' type='checkbox' onchange='filterCatalogBrowser()'> 只看 latest</label>"
        "<div class='filter-group-title'>状态</div>" + f"<div class='catalog-chips'>{chip_html}</div>"
        "<div class='filter-group-title'>操作</div>"
        + ui.action_strip(["<button class='btn secondary' type='button' onclick=\"catalogExpand('review')\">展开关注</button>", "<button class='btn secondary' type='button' onclick=\"catalogExpand('collapse')\">折叠</button>", "<button class='btn secondary' type='button' onclick='resetCatalogFilters()'>重置</button>"])
        + "<div id='catalog-visible-count' class='browser-count' style='margin-top:12px'>-</div><script>setTimeout(filterCatalogBrowser,0)</script>"
    )
    return ui.panel("筛选", "按库、版本、Vendor、Stage、状态快速定位。", body)


def _task_rows(tasks: Mapping[str, Any], limit: int = 50) -> list[str]:
    rows = []
    skipped_file_diff = 0
    for task in tasks.get("tasks", []) or []:
        task_type = str(task.get("task_type") or "")
        command = str(task.get("command") or "")
        if ("file" in task_type.lower() and "diff" in task_type.lower()) or " file-diff " in f" {command} ":
            skipped_file_diff += 1
            continue
        if len(rows) >= limit:
            break
        rows.append(
            "<tr>"
            f"<td>{ui.badge(task.get('priority'), task.get('priority'))}</td>"
            f"<td><code>{ui.esc(task_type)}</code></td>"
            f"<td><b>{ui.esc(task.get('display_name'))}</b><div class='muted'>{ui.esc(task.get('version_id'))}</div></td>"
            f"<td>{ui.esc(task.get('reason'))}</td>"
            f"<td><span class='muted'>按下方命令示例执行</span></td></tr>"
        )
    if skipped_file_diff:
        rows.append("<tr><td><span class='muted'>-</span></td><td><code>file-diff</code></td><td><b>File Diff 命令已下沉</b></td>" + f"<td>共 {ui.esc(skipped_file_diff)} 条 File Diff 候选命令不在 Catalog 展开；请进入 Selected Diff 的重点文件建议队列。</td><td><span class='muted'>不在 Catalog 生成全量命令</span></td></tr>")
    return rows


def _summary_metrics(state: Mapping[str, Any], tasks: Mapping[str, Any]) -> list[tuple[str, Any, str, Any]]:
    libs = list(state.get("libraries", []) or [])
    versions = [v for lib in libs for v in lib.get("versions", []) or []]
    changed = sum(1 for v in versions if "changed" in _version_tags(v))
    recommended = sum(1 for v in versions if "file_review_recommended" in _version_tags(v))
    bind = sum(1 for v in versions if _relation_status(v) == "NEED_BINDING")
    not_scanned = sum(1 for v in versions if "not_scanned" in _version_tags(v))
    return [("库", len(libs), "library count", "PASS"), ("版本", len(versions), "version count", "PASS"), ("需绑定", bind, "base_full / previous_effective", "WARNING" if bind else "PASS"), ("未扫描", not_scanned, "需要 scan 的版本", "WARNING" if not_scanned else "PASS"), ("有变化", changed, "进入版本链查看 comparison", "WARNING" if changed else "PASS"), ("重点文件", recommended, "不是 File Diff 完成度", "WARNING" if recommended else "PASS")]


def _command_examples() -> str:
    examples = [("刷新目录", "$PROJ/scripts/lg.csh catalog"), ("扫描版本", "$PROJ/scripts/lg.csh scan <library> <version>"), ("绑定关系", "$PROJ/scripts/lg.csh override <library> <version> --package-type PARTIAL_UPDATE --update-scope lib,lef --base-full <full_version> --previous-effective <prev_version> --note \"manual confirmed\""), ("执行对比", "$PROJ/scripts/lg.csh diff <library> <version> --scan-if-missing"), ("PowerShell", ".\\scripts\\lg.ps1 diff <library> <version> --scan-if-missing")]
    boxes = "".join(ui.command_box(command, title=title, note="示例命令。实际执行时替换 <library> / <version> / <relpath>。") for title, command in examples)
    return "<div class='command-example-grid'>" + boxes + "</div>"


def _catalog_browser_styles() -> str:
    return """
<style>
.library-main{grid-template-columns:minmax(0,1.3fr) minmax(140px,.8fr) minmax(128px,.7fr) minmax(128px,.7fr) minmax(0,1.05fr)}
.library-main>div{min-width:0}.library-main b[title]{display:inline-block;max-width:100%;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;vertical-align:bottom}.library-title{line-height:1.25}.library-status{grid-column:1/-1;min-width:0;justify-content:flex-start;padding-top:10px;margin-top:2px;border-top:1px dashed var(--line);overflow:visible}.library-status .action-strip{max-width:100%;min-width:0;overflow:visible;white-space:normal;flex-wrap:wrap;padding-bottom:0}.long-token{overflow-wrap:anywhere;word-break:break-word;hyphens:auto}.library-title.long-token,.version-name.long-token{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}.version-list{gap:7px}.version-row{display:grid;grid-template-columns:minmax(0,1.35fr) minmax(210px,1fr) minmax(220px,.95fr) minmax(76px,auto);gap:12px;align-items:center;border:1px solid var(--line);background:#fff;border-radius:11px;padding:10px 12px}.version-id-cell{min-width:0}.version-name{font-weight:800;font-size:14px;line-height:1.25}.version-path{font-size:12px;color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;margin-top:3px}.version-badges{display:flex;gap:6px;align-items:center;flex-wrap:wrap;min-width:0}.version-badges .badge{max-width:132px}.version-relation{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:6px;min-width:0}.version-relation span{border:1px solid var(--line);border-radius:8px;background:#f8fafc;padding:5px 7px;min-width:0}.version-relation b{display:block;color:#667085;font-size:11px;line-height:1.2}.version-relation em{display:block;font-style:normal;font-size:12px;color:#344054;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.version-action{text-align:right;min-width:0}.version-action .btn{max-width:100%}.table-wrap td code{white-space:normal;overflow-wrap:anywhere;word-break:break-word}.trace-link-row{min-width:0}.trace-link-row>div{min-width:0}.release-mini{display:inline-flex}.command-example-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px}.catalog-note{border:1px solid var(--line);border-radius:12px;background:#f8fafc;padding:12px;color:#667085;font-size:13px}@media(max-width:1180px){.library-main{grid-template-columns:1fr}.version-row{grid-template-columns:1fr}.version-action{text-align:left}.version-relation{grid-template-columns:1fr}}
</style>
"""


def _render_version_page(out: Path, lib: Mapping[str, Any], version: Mapping[str, Any]) -> str:
    lib_id = str(lib.get("library_id") or lib.get("display_name") or "library")
    version_id = str(version.get("version_id") or version.get("version") or "version")
    safe_lib = _safe(lib_id)
    safe_ver = _safe(version_id)
    page = out / "libraries" / safe_lib / "versions" / safe_ver / "index.html"
    links = _version_links(version)
    tags = _version_tags(version)
    timeline = out / "libraries" / safe_lib / "diff_timeline.html"
    relation = _relation_status(version)
    rail = ui.status_rail([("Catalog", "DISCOVERED", "版本已进入 catalog"), ("Scan", version.get("scan_status") or "NOT_SCANNED", "单版本证据页"), ("关系", relation, _relation_label(relation)), ("Diff", version.get("diff_status") or "COMPARE_PENDING", "进入版本链选择 comparison"), ("重点", _file_review_status(version), _file_review_text(version))])
    body = (
        ui.panel("版本导航", "主要路径：版本链 → Selected Diff。Catalog 不直接展开每一行命令。", ui.metric_grid([("Scan", ui.status_label(version.get("scan_status")), "单版本扫描", version.get("scan_status")), ("关系", _relation_label(relation), "base_full / previous_effective", relation), ("Diff", ui.status_label(version.get("diff_status")), "版本变化", version.get("diff_status")), ("重点文件", _file_review_text(version), "只在 Selected Diff 中打开", _file_review_status(version))]) + ui.compact_meta([("Library", lib_id), ("Version", version_id), ("Raw Path", version.get("raw_path") or "-"), ("Stage", version.get("stage") or "-"), ("base_full", _base_full_version(version) or "-"), ("previous_effective", _previous_effective_version(version) or "-")]))
        + ui.panel("主要入口", "先看库级版本链，再打开 Selected Diff。File Diff 从 Selected Diff 下钻。", ui.action_strip([ui.button("版本链", _href(timeline), "primary", target="_blank"), ui.button("差异页", _href(links.get("diff_html")), disabled=not links.get("diff_html"), target="_blank"), ui.button("扫描页", _href(links.get("scan_html")), disabled=not links.get("scan_html"), target="_blank"), ui.button("发布页", _href(links.get("release_html")), disabled=not links.get("release_html"), target="_blank")]))
        + ui.collapsible_panel("命令示例", "示例统一放在这里，不占用 Browser 列表宽度。", _command_examples(), open=False)
        + ui.collapsible_panel("Trace Links", "证据链接默认折叠。", ui.trace_link_list([("scan_html", _href(links.get("scan_html")), "单版本 Scan Review"), ("diff_html", _href(links.get("diff_html")), "Selected Diff Review"), ("pairwise_html", _href(links.get("pairwise_html")), "旧字段：不作为 Catalog/Version 直接入口；File Diff 从 Selected Diff 下钻"), ("release_html", _href(links.get("release_html")), "Release Review")]), open=False)
    )
    html = ui.review_page_shell(f"{lib.get('display_name') or lib_id} / {version_id}", "VERSION REVIEW", "版本入口页。主要路径是版本链 → Selected Diff；File Diff 从 Selected Diff 下钻。", _catalog_browser_styles() + body, decision=version.get("overall_status") or ("REVIEW" if tags - {"clear"} else "PASS"), rail=rail, nav=f"<a href='../../../index.html'>Catalog</a><a class='active' href='#'>Version</a><a href='../diff_timeline.html'>版本链</a>", meta=ui.compact_meta([("Library", lib_id), ("Version", version_id), ("Tags", ", ".join(sorted(tags)))]))
    _write_text(page, html)
    return str(page)


def render_catalog_html(catalog_json: str | Path, out_dir: str | Path, *, render_library_pages: bool = True, max_attention_items: int = 10, max_report_rows: int = 16) -> dict[str, Any]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    catalog = read_json(catalog_json, default={}) or {}
    state = build_review_state(catalog, out_dir=out)
    tasks = build_review_tasks(state)
    if render_library_pages:
        for lib in state.get("libraries", []) or []:
            for version in lib.get("versions", []) or []:
                links = version.setdefault("links", {})
                links["version_review_html"] = _render_version_page(out, lib, version)
    write_json(out / "review_state.json", state)
    write_json(out / "review_tasks.json", tasks)
    body = (
        _catalog_browser_styles()
        + ui.panel("Catalog 总览", "普通路径：搜索库 → 查看版本链 → 进入 Selected Diff。命令统一放在页面下方示例区。", ui.metric_grid(_summary_metrics(state, tasks)) + "<p class='catalog-note'>File Diff 是 Selected Diff 的文件级下钻入口。</p>")
        + "<div class='catalog-layout'>"
        + f"<div class='catalog-filter-panel'>{_catalog_filter_panel(state)}</div>"
        + f"<div>{ui.panel('Library Browser', '中文紧凑摘要：只显示版本身份、扫描、关系、基线/前版和一个主动作；不在行内放命令。', _library_browser(out, state))}</div>"
        + "</div>"
        + ui.collapsible_panel("Review Tasks", "任务列表只显示原因和类型；执行方式看下方命令示例，避免每行重复占宽。", ui.filterable_table("catalog-task-table", ["优先级", "类型", "Library / Version", "原因", "执行"], _task_rows(tasks), "暂无任务", "筛选 task / reason"), open=False)
        + ui.panel("命令示例", "所有常用命令集中放在这里。Browser 行内只保留状态和入口，不再放待生成命令。", _command_examples())
        + ui.collapsible_panel("Trace Evidence", "Catalog 原始证据。", ui.trace_link_list([("review_state.json", _href(out / "review_state.json"), "Catalog 页面使用的状态模型"), ("review_tasks.json", _href(out / "review_tasks.json"), "建议动作列表"), ("catalog.json", _href(catalog_json), "原始 catalog")]), open=False)
    )
    html = ui.review_page_shell("Library Catalog", "CATALOG", "库版本变化导航入口。Catalog 是地图，不是命令控制台。", body, decision="REVIEW" if tasks.get("tasks") else "PASS", nav="<a class='active' href='#'>Catalog</a><a href='#'>版本链</a><a href='#'>Selected Diff</a><a href='#'>Scan Evidence</a><a href='#'>Release Evidence</a>", meta=ui.compact_meta([("Libraries", len(state.get("libraries", []) or [])), ("Tasks", len(tasks.get("tasks", []) or []))]))
    index = out / "index.html"
    _write_text(index, html)
    return {"status": "PASS", "index_html": str(index), "review_state": str(out / "review_state.json"), "review_tasks": str(out / "review_tasks.json")}
