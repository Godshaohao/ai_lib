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
import os
import re

from lib_guard.review import build_review_state, build_review_tasks
from lib_guard.review.io import as_file_href, read_json, write_json
from lib_guard.render import product_theme as ui

try:
    from lib_guard.effective.compare import discover_compare_reports
    from lib_guard.effective.pointer import mark_current_effective_items
except Exception:  # pragma: no cover - optional effective workflow import
    discover_compare_reports = None
    mark_current_effective_items = None


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


def _rel_href(base: Path, path: Any) -> str:
    if not path:
        return ""
    try:
        target = Path(str(path))
        if target.is_absolute():
            return Path(os.path.relpath(target, base)).as_posix()
    except Exception:
        pass
    return str(path).replace("\\", "/")


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


def _short_name(value: Any, head: int = 26, tail: int = 18) -> str:
    text = str(value or "-")
    if len(text) <= head + tail + 3:
        return text
    return f"{text[:head]}...{text[-tail:]}"


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
    release_done_or_blocked = release not in {"", "UNKNOWN", "RELEASE_NOT_CHECKED", "RELEASE_NOT_APPLICABLE", "RELEASE_CHECK_REQUIRED", "NOT_APPLICABLE", "NONE"}
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


def _load_json_if_exists(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _library_match_keys(lib: Mapping[str, Any]) -> set[str]:
    values = {
        str(lib.get("library_id") or ""),
        str(lib.get("library_name") or ""),
        str(lib.get("display_name") or ""),
    }
    values.update(str(v) for v in lib.get("aliases", []) or [] if v)
    values.update(v.rsplit("/", 1)[-1] for v in list(values) if v)
    return {v for v in values if v}


def _effective_search_roots(out: Path) -> list[Path]:
    roots = []
    for root in [out / "libraries", out / "effective", out.parent / "effective", out.parent.parent / "effective"]:
        if root not in roots and root.exists():
            roots.append(root)
    return roots


def _discover_effective_reports(out: Path, libraries: list[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    by_key: dict[str, list[dict[str, Any]]] = {str(lib.get("library_id") or lib.get("display_name") or lib.get("library_name") or ""): [] for lib in libraries}
    key_lookup: dict[str, str] = {}
    for lib in libraries:
        canonical = str(lib.get("library_id") or lib.get("display_name") or lib.get("library_name") or "")
        for key in _library_match_keys(lib):
            key_lookup[key] = canonical
    seen: set[Path] = set()
    for root in _effective_search_roots(out):
        for manifest_path in root.rglob("effective_manifest.json"):
            if manifest_path in seen:
                continue
            seen.add(manifest_path)
            data = _load_json_if_exists(manifest_path)
            if not data:
                continue
            manifest_keys = {
                str(data.get("library_id") or ""),
                str(data.get("library_name") or ""),
                str(data.get("display_name") or ""),
            }
            manifest_keys.update(k.rsplit("/", 1)[-1] for k in list(manifest_keys) if k)
            canonical = next((key_lookup[k] for k in manifest_keys if k in key_lookup), "")
            if not canonical:
                continue
            html_path = manifest_path.parent / "index.html"
            release_preview_html = manifest_path.parent / "release_preview" / "index.html"
            release_manifest = manifest_path.parent / "release_preview" / "release_manifest.json"
            summary = data.get("summary", {}) or {}
            components = data.get("components", []) or []
            item = {
                "effective_id": data.get("effective_id") or manifest_path.parent.name,
                "manifest": str(manifest_path),
                "html": str(html_path) if html_path.exists() else "",
                "release_preview": str(release_preview_html) if release_preview_html.exists() else "",
                "release_manifest": str(release_manifest) if release_manifest.exists() else "",
                "base_full_version": data.get("base_full_version"),
                "accepted_updates": list(data.get("accepted_updates", []) or []),
                "components": components,
                "summary": summary,
                "conflict_count": int(summary.get("conflict_count", len(data.get("conflicts", []) or [])) or 0),
                "file_count": int(summary.get("file_count", len(data.get("effective_files", {}) or {})) or 0),
                "component_count": int(summary.get("component_count", len(components)) or 0),
                "operation_summary": summary.get("operation_summary", {}) or {},
                "file_type_summary": summary.get("file_type_summary", {}) or {},
                "source_summary": summary.get("source_summary", {}) or {},
                "created_at": data.get("created_at") or "",
            }
            by_key.setdefault(canonical, []).append(item)
    for items in by_key.values():
        items.sort(key=lambda x: str(x.get("created_at") or x.get("effective_id") or ""))
    if mark_current_effective_items is not None:
        by_key = mark_current_effective_items(out, by_key)
    return by_key


def _effective_items_for_lib(effective_by_lib: Mapping[str, list[dict[str, Any]]], lib: Mapping[str, Any]) -> list[dict[str, Any]]:
    key = str(lib.get("library_id") or lib.get("display_name") or lib.get("library_name") or "")
    return list(effective_by_lib.get(key, []) or [])


def _latest_effective_item(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    for item in items:
        if item.get("is_current_effective") or item.get("effective_status") == "current":
            return item
    return items[-1] if items else None


def _version_effective_refs(version_id: str, effective_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    refs = []
    for item in effective_items:
        accepted = {str(v) for v in item.get("accepted_updates", []) or []}
        component_versions = {str(c.get("version_id")) for c in item.get("components", []) or []}
        if str(version_id) in accepted or str(version_id) == str(item.get("base_full_version")) or str(version_id) in component_versions:
            refs.append(item)
    return refs


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


def _effective_summary_panel(out: Path, effective_items: list[dict[str, Any]], *, compact: bool = False) -> str:
    if not effective_items:
        return "<div class='catalog-empty'>暂无 effective snapshot</div>"
    latest = _latest_effective_item(effective_items) or {}
    op = latest.get("operation_summary", {}) or {}
    by_type = latest.get("file_type_summary", {}) or {}
    source = latest.get("source_summary", {}) or {}
    component_labels = []
    for comp in latest.get("components", []) or []:
        role = "base" if comp.get("role") == "base_full" else "update"
        scope = ",".join(comp.get("scope", []) or []) or "-"
        version = str(comp.get("version_id") or "-")
        component_labels.append(
            f"<span class='effective-chip {ui.esc(role)}'><b title='{ui.esc(version)}'>{ui.esc(version)}</b><em>{ui.esc(scope)}</em></span>"
        )
    op_tags = "".join(f"<span class='tiny-tag'>{ui.esc(k)}:{ui.esc(v)}</span>" for k, v in sorted(op.items()))
    type_tags = "".join(f"<span class='tiny-tag'>{ui.esc(k)}:{ui.esc(v)}</span>" for k, v in sorted(by_type.items()))
    source_tags = "".join(f"<span class='tiny-tag' title='{ui.esc(k)}'>{ui.esc(k)}:{ui.esc(v)}</span>" for k, v in sorted(source.items()))
    muted_dash = "<span class='muted'>-</span>"
    actions = ui.action_strip([
        ui.button("Effective 详情", _href(latest.get("html")), "primary", disabled=not bool(latest.get("html")), target="_blank"),
        ui.button("Release Preview", _href(latest.get("release_preview")), "secondary", disabled=not bool(latest.get("release_preview")), target="_blank"),
        ui.button("Manifest JSON", _href(latest.get("manifest")), "secondary", disabled=not bool(latest.get("manifest")), target="_blank"),
    ])
    if compact:
        return (
            "<div class='effective-mini'>"
            f"<b>{ui.esc(latest.get('effective_id') or '-')}</b>"
            f"<span>{ui.esc(latest.get('file_count', 0))} files</span>"
            f"<span>{ui.esc(latest.get('conflict_count', 0))} risks</span>"
            f"{actions}</div>"
        )
    return (
        "<div class='effective-summary'>"
            f"<div class='effective-head'><div><div class='muted'>当前 Effective</div><h3 title='{ui.esc(latest.get('effective_id'))}'>{ui.esc(latest.get('effective_id') or '-')}</h3></div>{actions}</div>"
        + ui.metric_grid([
            ("有效文件", latest.get("file_count", 0), "effective_files", "PASS"),
            ("组件", latest.get("component_count", 0), "base + updates", "PASS"),
            ("冲突", latest.get("conflict_count", 0), "scope / replacement", "WARNING" if latest.get("conflict_count") else "PASS"),
            ("快照", len(effective_items), "effective snapshots", "PASS"),
        ])
        + f"<div class='effective-stack'>{''.join(component_labels) or muted_dash}</div>"
        + f"<div class='effective-tags'><b>操作</b>{op_tags or muted_dash}</div>"
        + f"<div class='effective-tags'><b>类型</b>{type_tags or muted_dash}</div>"
        + f"<div class='effective-tags'><b>来源</b>{source_tags or muted_dash}</div>"
        "</div>"
    )


def _effective_snapshot_rows(out: Path, effective_items: list[dict[str, Any]]) -> list[str]:
    rows = []
    for item in reversed(effective_items):
        rows.append(
            "<tr>"
            f"<td><code>{ui.esc(item.get('effective_id'))}</code></td>"
            f"<td>{ui.esc(item.get('base_full_version') or '-')}</td>"
            f"<td>{ui.esc(', '.join(str(v) for v in item.get('accepted_updates', []) or []) or '-')}</td>"
            f"<td>{ui.esc(item.get('file_count', 0))}</td>"
            f"<td>{ui.badge('RISK' if item.get('conflict_count') else 'OK', item.get('conflict_count', 0))}</td>"
            f"<td>{ui.action_strip([ui.button('Effective 详情', _href(item.get('html')), 'primary', disabled=not bool(item.get('html')), target='_blank'), ui.button('Release Preview', _href(item.get('release_preview')), 'secondary', disabled=not bool(item.get('release_preview')), target='_blank')])}</td>"
            "</tr>"
        )
    return rows


def _version_ledger_rows(lib: Mapping[str, Any], effective_items: list[dict[str, Any]]) -> list[str]:
    rows = []
    for version in reversed(list(lib.get("versions", []) or [])):
        version_id = str(version.get("version_id") or version.get("version") or "-")
        links = _version_links(version)
        refs = _version_effective_refs(version_id, effective_items)
        latest_ref = refs[-1] if refs else {}
        effective_label = str(latest_ref.get("effective_id") or "not included")
        rows.append(
            "<tr>"
            f"<td><b title='{ui.esc(version_id)}'>{ui.esc(version_id)}</b><div class='muted'>{ui.esc(version.get('stage') or '-')}</div></td>"
            f"<td>{ui.button('Scan 证据', _href(links.get('scan_html')), 'secondary', disabled=not bool(links.get('scan_html')), target='_blank')}</td>"
            f"<td>{ui.button('Diff 证据', _href(links.get('diff_html')), 'secondary', disabled=not bool(links.get('diff_html')), target='_blank')}</td>"
            f"<td>{ui.button(effective_label, _href(latest_ref.get('html')), 'primary' if latest_ref else 'secondary', disabled=not bool(latest_ref.get('html')), target='_blank')}</td>"
            f"<td>{ui.button('Release Preview', _href(latest_ref.get('release_preview')), 'secondary', disabled=not bool(latest_ref.get('release_preview')), target='_blank')}</td>"
            "</tr>"
        )
    return rows


def _compare_target_label(target: Mapping[str, Any]) -> str:
    if not isinstance(target, Mapping):
        return "-"
    return str(target.get("label") or f"{target.get('type') or 'target'}:{target.get('id') or '-'}")


def _compare_index_rows(lib: Mapping[str, Any], compare_items: list[dict[str, Any]] | None = None) -> list[str]:
    rows = []
    for item in compare_items or []:
        old_label = _compare_target_label(item.get("old_target", {}) or {})
        new_label = _compare_target_label(item.get("new_target", {}) or {})
        actions = item.get("actions", {}) or {}
        status = "RISK" if item.get("risk_count") else ("CHANGED" if item.get("changed_files") else "OK")
        rows.append(
            "<tr>"
            f"<td><code>{ui.esc(item.get('mode') or '-')}</code><div class='muted'>{ui.esc(item.get('compare_id') or '-')}</div></td>"
            f"<td><span title='{ui.esc(old_label)}'>{ui.esc(_short_name(old_label))}</span></td>"
            f"<td><span title='{ui.esc(new_label)}'>{ui.esc(_short_name(new_label))}</span></td>"
            f"<td>{ui.badge(status, {'RISK': '需复核', 'CHANGED': '有变化', 'OK': '无变化'}.get(status, status))}</td>"
            f"<td>{ui.esc(item.get('changed_files', 0))}</td>"
            f"<td>{ui.esc(actions.get('replace', 0))}</td>"
            f"<td><span title='{ui.esc(item.get('owner_target') or '')}'>{ui.esc(_short_name(item.get('owner_target') or '-'))}</span></td>"
            f"<td>{ui.action_strip([ui.button('打开报告', _href(item.get('html')), 'primary', disabled=not bool(item.get('html')), target='_blank'), ui.button('Manifest', _href(item.get('manifest')), 'secondary', disabled=not bool(item.get('manifest')), target='_blank')])}</td>"
            "</tr>"
        )
    if rows:
        return rows
    for item in _build_comparisons_for_library(lib):
        old_version = str(item.get("old_version") or "-")
        new_version = str(item.get("new_version") or "-")
        diff_html = item.get("diff_html")
        rows.append(
            "<tr>"
            f"<td><code>{ui.esc(item.get('mode') or '-')}</code></td>"
            f"<td><span title='{ui.esc(old_version)}'>{ui.esc(_short_name(old_version))}</span></td>"
            f"<td><span title='{ui.esc(new_version)}'>{ui.esc(_short_name(new_version))}</span></td>"
            f"<td>{ui.badge(item.get('status') or 'COMPARE_PENDING')}</td>"
            f"<td>{ui.esc(item.get('recommended_total', 0))}</td>"
            f"<td>{ui.esc(item.get('candidate_total', 0))}</td>"
            f"<td>{ui.badge(item.get('comparison_quality') or 'NORMAL')}</td>"
            f"<td>{ui.button('Diff', diff_html, 'primary', disabled=not bool(diff_html), target='_blank')}</td>"
            "</tr>"
        )
    return rows


def _render_library_home(out: Path, lib: Mapping[str, Any], effective_items: list[dict[str, Any]], compare_items: list[dict[str, Any]] | None = None) -> str:
    lib_id = str(lib.get("library_id") or lib.get("display_name") or "library")
    safe = _safe(lib_id)
    html_path = out / "libraries" / safe / "index.html"
    versions = list(lib.get("versions", []) or [])
    latest_effective = _latest_effective_item(effective_items)
    not_scanned = sum(1 for v in versions if "not_scanned" in _version_tags(v))
    diff_pending = sum(1 for v in versions if _status_key(v.get("diff_status")) in {"DIFF_PENDING", "DIFF_NOT_READY", "COMPARE_PENDING"})
    need_bind = sum(1 for v in versions if _relation_status(v) == "NEED_BINDING")
    body = (
        _catalog_browser_styles()
        + ui.panel(
            "库总览",
            "单库主页负责串联版本、scan、diff、effective 和 release preview；详情报告保持独立页面。",
            ui.metric_grid([
                ("最新完整包", _latest_full_version(versions), "完整基线", "PASS"),
                ("当前 Effective", (latest_effective or {}).get("effective_id") or "未设置", "当前有效组合", "PASS" if latest_effective else "WARNING"),
                ("待扫描", not_scanned, "raw 交付证据", "WARNING" if not_scanned else "PASS"),
                ("待对比", diff_pending, "compare 证据", "WARNING" if diff_pending else "PASS"),
                ("需绑定", need_bind, "base_full / previous_effective", "WARNING" if need_bind else "PASS"),
            ])
            + ui.compact_meta([
                ("Library", lib_id),
                ("Vendor", lib.get("vendor") or "-"),
                ("Path", lib.get("middle_path") or lib.get("library_root") or "-"),
            ]),
        )
        + ui.panel("Effective 摘要", "这里只展示 effective 摘要和入口，不嵌入完整 effective HTML。", _effective_summary_panel(out, effective_items))
        + ui.panel(
            "Raw 版本台账",
            "每个 raw version 的 scan/diff/effective/release-preview 证据链。",
            ui.filterable_table(
                f"ledger-{safe}",
                ["版本", "Scan 证据", "Diff 证据", "Effective", "Release"],
                _version_ledger_rows(lib, effective_items),
                "暂无 version",
                "筛选 version / stage",
            ),
        )
        + ui.collapsible_panel(
            "Compare 索引",
            "优先显示 Effective/Release Compare Report；没有真实 compare_manifest 时退回 raw diff 入口。",
            ui.filterable_table(
                f"compare-{safe}",
                ["模式", "基准目标", "对比目标", "状态", "变化", "替换", "检查对象 / 质量", "入口"],
                _compare_index_rows(lib, compare_items),
                "暂无 comparison",
                "筛选基准 / 对比 / 模式 / 状态",
            ),
            open=True,
        )
        + ui.collapsible_panel(
            "Effective 快照",
            "历史 effective 快照只列摘要，完整文件来源表进入独立 Effective 页面查看。",
            ui.filterable_table(
                f"effective-{safe}",
                ["Effective", "Base Full", "吸收更新", "文件数", "风险", "入口"],
                _effective_snapshot_rows(out, effective_items),
                "暂无 effective snapshot",
                "筛选 effective / update",
            ),
            open=bool(effective_items),
        )
        + ui.panel("证据入口", "统一证据入口。", ui.action_strip([
            ui.button("Catalog", _href(out / "index.html"), "secondary", target="_blank"),
            ui.button("当前 Effective", _href((latest_effective or {}).get("html")), "secondary", disabled=not bool((latest_effective or {}).get("html")), target="_blank"),
            ui.button("Release Preview", _href((latest_effective or {}).get("release_preview")), "secondary", disabled=not bool((latest_effective or {}).get("release_preview")), target="_blank"),
        ]))
        + ui.collapsible_panel("命令示例", "命令集中放置，不挤占版本表。", _command_examples(), open=False)
    )
    html = ui.review_page_shell(
        f"{lib.get('display_name') or lib_id} / Library Workspace",
        "LIBRARY WORKSPACE",
        "Catalog 的下钻主页：先看当前有效组合，再核对版本账本和证据链。",
        body,
        decision=lib.get("overall_status") or "REVIEW",
        nav="<a href='../../index.html'>Catalog</a><a class='active' href='#'>Library Workspace</a>",
        meta=ui.compact_meta([("版本", len(versions)), ("Effective", len(effective_items)), ("待扫描", not_scanned), ("待对比", diff_pending)]),
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
    file_status = _file_review_status(version)
    base_full = _base_full_version(version)
    prev_eff = _previous_effective_version(version)
    label, href, kind, disabled = _version_primary_action(version)
    release_html = f"<span class='release-mini'>{ui.badge(version.get('release_status'), '发布')}</span>" if _release_is_visible(version, lib) else ""
    review_hint = ui.badge(file_status, _file_review_text(version)) if file_status != "PAIRWISE_EMPTY" else ""
    stage_html = "" if stage.lower() in {"", "-", "unknown"} else ui.badge(stage, stage)
    scan_html = "" if scan_status == "NOT_SCANNED" else ui.badge(scan_status, scan_text)
    relation_html = "<div class='version-relation version-relation-empty' aria-hidden='true'></div>"
    if base_full or prev_eff:
        relation_html = (
            "<div class='version-relation'>"
            f"<span><b>基线</b><em title='{ui.esc(base_full or '-')}'>{ui.esc(base_full or '-')}</em></span>"
            f"<span><b>前版</b><em title='{ui.esc(prev_eff or '-')}'>{ui.esc(prev_eff or '-')}</em></span>"
            "</div>"
        )
    return (
        f"<div class='version-row' data-tags='{ui.esc(tags)}' data-latest='{is_latest}' data-search='{ui.esc(_version_display_text(version))}'>"
        "<div class='version-id-cell'>"
        f"<div class='version-name long-token' title='{ui.esc(version_id)}'>{ui.esc(version_id)}</div>"
        f"<div class='version-path' title='{ui.esc(version.get('raw_path'))}'>{ui.esc(_short_path(version.get('raw_path')))}</div>"
        "</div>"
        "<div class='version-badges'>"
        f"{ui.badge(pkg_status, pkg_label)}{stage_html}{scan_html}{review_hint}{release_html}"
        "</div>"
        f"{relation_html}"
        f"<div class='version-action'>{ui.button(label, href, kind, disabled=disabled, target='_blank')}</div>"
        "</div>"
    )


def _library_card(out: Path, lib: Mapping[str, Any], effective_items: list[dict[str, Any]]) -> str:
    versions = list(lib.get("versions", []) or [])
    latest = lib.get("latest_version") or (versions[-1].get("version_id") if versions else "-")
    latest_full = _latest_full_version(versions)
    latest_effective = _latest_effective_version(lib, versions)
    status = lib.get("overall_status") or "UNKNOWN"
    vendor = str(lib.get("vendor") or "Unknown")
    middle = str(lib.get("middle_path") or lib.get("library_root") or "-")
    stages = sorted({str(v.get("stage") or "unknown") for v in versions})
    tags = _library_tags(lib)
    home_path = str(lib.get("library_home_html") or "")
    latest_effective_item = _latest_effective_item(effective_items)
    changed = sum(1 for v in versions if "changed" in _version_tags(v))
    version_rows = "".join(_version_row(lib, v, latest) for v in reversed(versions))
    library_label = lib.get("display_name") or lib.get("library_name") or lib.get("library_id")
    empty_versions = "<div class='catalog-empty'>暂无 version</div>"
    version_list_html = version_rows or empty_versions
    actions = ui.action_strip([
        ui.button("进入库工作台", _href(home_path), "primary", disabled=not bool(home_path), target="_blank"),
        ui.button("Effective", _href((latest_effective_item or {}).get("html")), "secondary", disabled=not bool((latest_effective_item or {}).get("html")), target="_blank"),
    ])
    effective_label = str((latest_effective_item or {}).get("effective_id") or latest_effective)
    status_badge = "" if _status_key(status) == "UNKNOWN" else ui.badge(status)
    changed_badge = ui.quiet_badge("CHANGED", changed) if changed else ""
    return (
        f"<section class='library-card' data-overall='{ui.esc(status)}' data-vendor='{ui.esc(vendor)}' data-stages='{ui.esc(','.join(stages))}' data-tags='{ui.esc(','.join(sorted(tags)))}'>"
        "<div class='library-main'>"
        f"<div class='library-name-row'><div class='library-title long-token' title='{ui.esc(library_label)}'>{ui.esc(library_label)}</div></div>"
        f"<div class='library-path-row'><span class='muted'>Library</span><code title='{ui.esc(lib.get('library_id'))}'>{ui.esc(lib.get('library_id') or '-')}</code></div>"
        f"<div class='library-path-row'><span class='muted'>Path</span><code title='{ui.esc(middle)}'>{ui.esc(middle)}</code></div>"
        f"<div><span class='muted'>Vendor</span><br><b>{ui.esc(vendor)}</b></div>"
        f"<div><span class='muted'>完整基线</span><br><b title='{ui.esc(latest_full)}'>{ui.esc(latest_full)}</b></div>"
        f"<div><span class='muted'>当前有效</span><br><b title='{ui.esc(effective_label)}'>{ui.esc(effective_label)}</b></div>"
        "<div class='library-status'>"
        f"{status_badge}<span class='browser-count'>{len(versions)} 版</span>{changed_badge}{actions}"
        "</div></div>"
        f"<details class='version-drawer' {'open' if changed else ''}><summary>版本明细 / 默认展开有更新库</summary><div class='version-list'>{version_list_html}</div></details>"
        "</section>"
    )


def _group_libraries(libraries: list[Mapping[str, Any]]) -> dict[tuple[str, str], list[Mapping[str, Any]]]:
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for lib in libraries:
        key = (str(lib.get("vendor") or "Unknown"), str(lib.get("middle_path") or lib.get("library_root") or "-"))
        grouped.setdefault(key, []).append(lib)
    return dict(sorted(grouped.items(), key=lambda kv: (kv[0][0], kv[0][1])))


def _library_browser(out: Path, state: Mapping[str, Any], effective_by_lib: Mapping[str, list[dict[str, Any]]]) -> str:
    libraries = list(state.get("libraries", []) or [])
    groups = _group_libraries(libraries)
    group_html = []
    for (vendor, middle), libs in groups.items():
        cards = "".join(_library_card(out, lib, _effective_items_for_lib(effective_by_lib, lib)) for lib in libs)
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
    stages = sorted(
        {
            str(v.get("stage") or "unknown")
            for lib in libraries
            for v in (lib.get("versions", []) or [])
            if str(v.get("stage") or "unknown").lower() not in {"", "-", "unknown"}
        }
    )
    vendor_opts = "<option value='all'>全部 Vendor</option>" + "".join(f"<option value='{ui.esc(v)}'>{ui.esc(v)}</option>" for v in vendors)
    stage_opts = "<option value='all'>全部 Stage</option>" + "".join(f"<option value='{ui.esc(s)}'>{ui.esc(s)}</option>" for s in stages)
    chips = [("all", "全部"), ("changed", "有更新"), ("file_review_recommended", "重点文件"), ("not_scanned", "待补证据"), ("review", "需管理"), ("block", "阻塞"), ("clear", "正常")]
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
        if "release" in task_type.lower() or " release " in f" {command.lower()} ":
            continue
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
    diff_pending = sum(1 for v in versions if _status_key(v.get("diff_status")) in {"DIFF_PENDING", "DIFF_NOT_READY", "COMPARE_PENDING"})
    recommended = sum(1 for v in versions if "file_review_recommended" in _version_tags(v))
    not_scanned = sum(1 for v in versions if "not_scanned" in _version_tags(v))
    evidence_pending = not_scanned + diff_pending
    actionable_tasks = len([t for t in (tasks.get("tasks", []) or []) if "release" not in str(t.get("task_type") or "").lower()])
    return [
        ("库", len(libs), "可查询的 library", "PASS"),
        ("版本", len(versions), "可查询的版本", "PASS"),
        ("有更新", changed, "进入库工作台查看更新文件", "WARNING" if changed else "PASS"),
        ("重点文件", recommended, "Selected Diff 下钻建议", "WARNING" if recommended else "PASS"),
        ("待补证据", evidence_pending, "库管理者补 scan / diff", "WARNING" if evidence_pending else "PASS"),
        ("管理任务", actionable_tasks, "见 manager_tasks.json", "INFO" if actionable_tasks else "PASS"),
    ]


def _command_examples() -> str:
    examples = [("刷新目录", "$PROJ/scripts/lg.csh cat"), ("扫描版本", "$PROJ/scripts/lg.csh scan <library> <version>"), ("绑定关系", "$PROJ/scripts/lg.csh override <library> <version> --package-type PARTIAL_UPDATE --update-scope lib,lef --base-full <full_version> --previous-effective <prev_version> --note \"manual confirmed\""), ("执行对比", "$PROJ/scripts/lg.csh cmp <library> <version> --scan-if-missing"), ("发布检查", "$PROJ/scripts/lg.csh rel <library> <version> --check-first"), ("PowerShell", ".\\scripts\\lg.ps1 cmp <library> <version> --scan-if-missing")]
    boxes = "".join(ui.command_box(command, title=title, note="示例命令。实际执行时替换 <library> / <version> / <relpath>。") for title, command in examples)
    return "<div class='command-example-grid'>" + boxes + "</div>"


def _catalog_browser_styles() -> str:
    return """
<style>
.library-main{grid-template-columns:minmax(140px,.8fr) minmax(128px,.7fr) minmax(128px,.7fr);align-items:start}
.library-main>div{min-width:0}.library-main b[title]{display:inline-block;max-width:100%;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;vertical-align:bottom}.library-name-row,.library-path-row,.library-status{grid-column:1/-1}.library-name-row{padding-bottom:2px}.library-title{font-size:18px;line-height:1.28}.library-path-row{display:grid;grid-template-columns:72px minmax(0,1fr);gap:10px;align-items:start;border:1px solid var(--line);border-radius:9px;background:#f8fafc;padding:7px 9px}.library-path-row span{font-size:12px;font-weight:800}.library-path-row code{display:block;color:#344054;white-space:normal;overflow-wrap:anywhere;word-break:break-word}.library-status{min-width:0;justify-content:flex-start;padding-top:10px;margin-top:2px;border-top:1px dashed var(--line);overflow:visible}.library-status .action-strip{max-width:100%;min-width:0;overflow:visible;white-space:normal;flex-wrap:wrap;padding-bottom:0}.long-token{overflow-wrap:anywhere;word-break:break-word;hyphens:auto}.library-title.long-token{display:block}.version-name.long-token{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}.version-list{gap:7px}.version-row{display:grid;grid-template-columns:minmax(0,1.35fr) minmax(210px,1fr) minmax(220px,.95fr) minmax(76px,auto);gap:12px;align-items:center;border:1px solid var(--line);background:#fff;border-radius:11px;padding:10px 12px}.version-id-cell{min-width:0}.version-name{font-weight:800;font-size:14px;line-height:1.25}.version-path{font-size:12px;color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;margin-top:3px}.version-badges{display:flex;gap:6px;align-items:center;flex-wrap:wrap;min-width:0}.version-badges .badge{max-width:132px}.version-relation{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:6px;min-width:0}.version-relation span{border:1px solid var(--line);border-radius:8px;background:#f8fafc;padding:5px 7px;min-width:0}.version-relation b{display:block;color:#667085;font-size:11px;line-height:1.2}.version-relation em{display:block;font-style:normal;font-size:12px;color:#344054;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.version-action{text-align:right;min-width:0}.version-action .btn{max-width:100%}.table-wrap td code{white-space:normal;overflow-wrap:anywhere;word-break:break-word}.trace-link-row{min-width:0}.trace-link-row>div{min-width:0}.release-mini{display:inline-flex}.command-example-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px}.catalog-note{border:1px solid var(--line);border-radius:12px;background:#f8fafc;padding:12px;color:#667085;font-size:13px}@media(max-width:1180px){.library-main{grid-template-columns:1fr}.library-path-row{grid-template-columns:1fr}.version-row{grid-template-columns:1fr}.version-action{text-align:left}.version-relation{grid-template-columns:1fr}}
.effective-summary{display:flex;flex-direction:column;gap:12px}.effective-head{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}.effective-head h3{margin:3px 0 0;font-size:18px;max-width:680px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.effective-stack{display:flex;gap:8px;overflow-x:auto;padding-bottom:2px}.effective-chip{flex:0 0 220px;border:1px solid var(--line);border-radius:10px;background:#f8fafc;padding:9px}.effective-chip.base{background:#eff6ff;border-color:#bfdbfe}.effective-chip.update{background:#f5f3ff;border-color:#ddd6fe}.effective-chip b{display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.effective-chip em{display:block;font-size:12px;color:#667085;font-style:normal;margin-top:3px}.effective-tags{display:flex;gap:7px;align-items:center;flex-wrap:wrap}.effective-tags>b{font-size:12px;color:#667085;min-width:44px}.effective-mini{display:flex;gap:8px;align-items:center;flex-wrap:wrap;border:1px solid var(--line);border-radius:10px;background:#f8fafc;padding:10px}.tiny-tag{display:inline-flex;border:1px solid var(--line);border-radius:999px;padding:3px 7px;background:#fff;font-size:12px;color:#344054}
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
    relation = _relation_status(version)
    rail = ui.status_rail([("Catalog", "DISCOVERED", "版本已进入 catalog"), ("Scan", version.get("scan_status") or "NOT_SCANNED", "单版本证据页"), ("关系", relation, _relation_label(relation)), ("Diff", version.get("diff_status") or "COMPARE_PENDING", "进入库工作台选择 comparison"), ("重点", _file_review_status(version), _file_review_text(version))])
    body = (
        ui.panel("版本导航", "主要路径：Library Workspace → Compare Index → Selected Diff。Catalog 不直接展开每一行命令。", ui.metric_grid([("Scan", ui.status_label(version.get("scan_status")), "单版本扫描", version.get("scan_status")), ("关系", _relation_label(relation), "base_full / previous_effective", relation), ("Diff", ui.status_label(version.get("diff_status")), "版本变化", version.get("diff_status")), ("重点文件", _file_review_text(version), "只在 Selected Diff 中打开", _file_review_status(version))]) + ui.compact_meta([("Library", lib_id), ("Version", version_id), ("Raw Path", version.get("raw_path") or "-"), ("Stage", version.get("stage") or "-"), ("base_full", _base_full_version(version) or "-"), ("previous_effective", _previous_effective_version(version) or "-")]))
        + ui.panel("主要入口", "先回到库工作台查看 Compare Index，再打开 Selected Diff。File Diff 从 Selected Diff 下钻。", ui.action_strip([ui.button("库工作台", _href(out / "libraries" / safe_lib / "index.html"), "primary", target="_blank"), ui.button("差异页", _href(links.get("diff_html")), disabled=not links.get("diff_html"), target="_blank"), ui.button("扫描页", _href(links.get("scan_html")), disabled=not links.get("scan_html"), target="_blank"), ui.button("发布页", _href(links.get("release_html")), disabled=not links.get("release_html"), target="_blank")]))
        + ui.collapsible_panel("命令示例", "示例统一放在这里，不占用 Browser 列表宽度。", _command_examples(), open=False)
        + ui.collapsible_panel("Trace Links", "证据链接默认折叠。", ui.trace_link_list([("scan_html", _href(links.get("scan_html")), "单版本 Scan Review"), ("diff_html", _href(links.get("diff_html")), "Selected Diff Review"), ("pairwise_html", _href(links.get("pairwise_html")), "旧字段：不作为 Catalog/Version 直接入口；File Diff 从 Selected Diff 下钻"), ("release_html", _href(links.get("release_html")), "Release Review")]), open=False)
    )
    html = ui.review_page_shell(f"{lib.get('display_name') or lib_id} / {version_id}", "VERSION REVIEW", "版本入口页。主要路径是 Library Workspace → Compare Index → Selected Diff；File Diff 从 Selected Diff 下钻。", _catalog_browser_styles() + body, decision=version.get("overall_status") or ("REVIEW" if tags - {"clear"} else "PASS"), rail=rail, nav=f"<a href='../../../index.html'>Catalog</a><a class='active' href='#'>Version</a><a href='../index.html'>Library Workspace</a>", meta=ui.compact_meta([("Library", lib_id), ("Version", version_id), ("Tags", ", ".join(sorted(tags)))]))
    _write_text(page, html)
    return str(page)


def _write_report_index(
    out: Path,
    state: Mapping[str, Any],
    effective_by_lib: Mapping[str, list[dict[str, Any]]],
    compare_by_lib: Mapping[str, list[dict[str, Any]]] | None = None,
) -> str:
    libraries: dict[str, Any] = {}
    for lib in state.get("libraries", []) or []:
        lib_id = str(lib.get("library_id") or lib.get("display_name") or lib.get("library_name") or "")
        effective_items = _effective_items_for_lib(effective_by_lib, lib)
        versions: dict[str, Any] = {}
        for version in lib.get("versions", []) or []:
            version_id = str(version.get("version_id") or version.get("version") or "")
            links = _version_links(version)
            refs = _version_effective_refs(version_id, effective_items)
            versions[version_id] = {
                "home": _rel_href(out, links.get("version_review_html")),
                "scan": _rel_href(out, links.get("scan_html")),
                "diffs": [_rel_href(out, links.get("diff_html"))] if links.get("diff_html") else [],
                "contributes_to_effective": [str(item.get("effective_id")) for item in refs],
            }
        effective = {
            str(item.get("effective_id")): {
                "html": _rel_href(out, item.get("html")),
                "manifest": _rel_href(out, item.get("manifest")),
                "release_preview": _rel_href(out, item.get("release_preview")),
                "release_manifest": _rel_href(out, item.get("release_manifest")),
                "summary": {
                    "file_count": item.get("file_count", 0),
                    "component_count": item.get("component_count", 0),
                    "conflict_count": item.get("conflict_count", 0),
                    "operation_summary": item.get("operation_summary", {}),
                    "file_type_summary": item.get("file_type_summary", {}),
                },
            }
            for item in effective_items
        }
        current_effective = _latest_effective_item(effective_items) or {}
        compare_items = list((compare_by_lib or {}).get(lib_id, []) or [])
        compare_reports = {
            str(item.get("compare_id")): {
                "mode": item.get("mode"),
                "old_target": item.get("old_target", {}),
                "new_target": item.get("new_target", {}),
                "owner_target": item.get("owner_target") or "",
                "html": _rel_href(out, item.get("html")),
                "manifest": _rel_href(out, item.get("manifest")),
                "summary": {
                    "changed_files": item.get("changed_files", 0),
                    "risk_count": item.get("risk_count", 0),
                    "actions": item.get("actions", {}),
                },
            }
            for item in compare_items
            if item.get("compare_id")
        }
        libraries[lib_id] = {
            "home": _rel_href(out, lib.get("library_home_html")),
            "versions": versions,
            "effective": effective,
            "current_effective": str(current_effective.get("effective_id") or "") if current_effective else "",
            "compare_reports": compare_reports,
        }
    path = out / "report_index.json"
    write_json(
        path,
        {
            "schema_version": "report_index.v1",
            "entry": "index.html",
            "libraries": libraries,
        },
    )
    return str(path)


def render_catalog_html(catalog_json: str | Path, out_dir: str | Path, *, render_library_pages: bool = True, max_attention_items: int = 10, max_report_rows: int = 16) -> dict[str, Any]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    catalog = read_json(catalog_json, default={}) or {}
    state = build_review_state(catalog, out_dir=out)
    state["schema_version"] = "catalog_state.v1"
    tasks = build_review_tasks(state)
    tasks["schema_version"] = "manager_tasks.v1"
    libraries_for_reports = list(state.get("libraries", []) or [])
    effective_by_lib = _discover_effective_reports(out, libraries_for_reports)
    compare_by_lib = discover_compare_reports(out, libraries_for_reports) if discover_compare_reports is not None else {}
    if render_library_pages:
        for lib in state.get("libraries", []) or []:
            for version in lib.get("versions", []) or []:
                links = version.setdefault("links", {})
                links["version_review_html"] = _render_version_page(out, lib, version)
            lib_id = str(lib.get("library_id") or lib.get("display_name") or lib.get("library_name") or "")
            lib["library_home_html"] = _render_library_home(out, lib, _effective_items_for_lib(effective_by_lib, lib), list(compare_by_lib.get(lib_id, []) or []))
    report_index = _write_report_index(out, state, effective_by_lib, compare_by_lib)
    for stale_name in ("review_state.json", "review_tasks.json"):
        stale_path = out / stale_name
        if stale_path.exists():
            stale_path.unlink()
    write_json(out / "catalog_state.json", state)
    write_json(out / "manager_tasks.json", tasks)
    body = (
        _catalog_browser_styles()
        + ui.panel("Catalog 总览", "面向 IP 使用者：先搜索库，再进入库工作台查看更新文件和可执行脚本。库管理者证据放在下方折叠区。", ui.metric_grid(_summary_metrics(state, tasks)) + "<p class='catalog-note'>主流程是获取库更新信息、更新文件和执行脚本；管理补证据不作为普通使用者的首要任务。</p>")
        + "<div class='catalog-layout'>"
        + f"<div class='catalog-filter-panel'>{_catalog_filter_panel(state)}</div>"
        + f"<div>{ui.panel('Library Browser', '中文紧凑摘要：只显示库身份、当前有效组合和进入库工作台；scan/diff/effective/release preview 由库工作台串联。', _library_browser(out, state, effective_by_lib))}</div>"
        + "</div>"
        + ui.collapsible_panel("管理建议 / Suggested Commands", "manager_tasks.json 是有效的管理者任务列表，用于补 scan、diff 或关系确认；普通 IP 使用者通常不需要处理。", ui.filterable_table("catalog-task-table", ["优先级", "类型", "Library / Version", "原因", "执行"], _task_rows(tasks), "暂无建议", "筛选 task / reason"), open=False)
        + ui.collapsible_panel("Trace Evidence", "Catalog 原始证据和统一报告索引。manager_tasks.json 的定位是管理者任务证据。", ui.trace_link_list([("report_index.json", _href(report_index), "Catalog / Scan / Diff / Effective / Release Preview 的链接索引"), ("catalog_state.json", _href(out / "catalog_state.json"), "Catalog 页面使用的状态模型"), ("manager_tasks.json", _href(out / "manager_tasks.json"), "管理者建议动作列表"), ("catalog.json", _href(catalog_json), "原始 catalog")]), open=True)
        + ui.collapsible_panel("命令示例", "所有常用命令集中折叠在最下面。Browser 行内只保留状态和入口，不再放待生成命令。", _command_examples(), open=False)
    )
    html = ui.review_page_shell("Library Catalog", "CATALOG", "库版本变化导航入口。Catalog 是地图，不是命令控制台。", body, decision="REVIEW" if tasks.get("tasks") else "PASS", nav="<a class='active' href='#'>Catalog</a><a href='#'>Library Workspace</a><a href='#'>Selected Diff</a><a href='#'>Scan Evidence</a><a href='#'>Release Evidence</a>", meta=ui.compact_meta([("Libraries", len(state.get("libraries", []) or [])), ("Tasks", len(tasks.get("tasks", []) or []))]))
    index = out / "index.html"
    _write_text(index, html)
    return {"status": "PASS", "index_html": str(index), "catalog_state": str(out / "catalog_state.json"), "manager_tasks": str(out / "manager_tasks.json"), "report_index": report_index}
