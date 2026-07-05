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
from lib_guard.render import catalog_render_common as common
from lib_guard.render import product_theme as ui

try:
    from lib_guard.effective.compare import discover_compare_reports
    from lib_guard.effective.pointer import mark_current_effective_items
except Exception:  # pragma: no cover - optional effective workflow import
    discover_compare_reports = None
    mark_current_effective_items = None


def _safe(value: Any) -> str:
    return common.safe(value)


def _write_text(path: Path, text: str) -> None:
    common.write_text(path, text)


def _version_links(version: Mapping[str, Any]) -> Mapping[str, Any]:
    return common.version_links(version)


def _href(path: Any) -> str:
    return common.href(path)


def _rel_href(base: Path, path: Any) -> str:
    return common.rel_href(base, path)


def _status_key(value: Any) -> str:
    return common.status_key(value)


def _truthy(value: Any) -> bool:
    return common.truthy(value)


def _short_path(path: Any, limit: int = 72) -> str:
    return common.short_path(path, limit)


def _short_name(value: Any, head: int = 26, tail: int = 18) -> str:
    return common.short_name(value, head, tail)


def _package_type(version: Mapping[str, Any]) -> str:
    return common.package_type(version)


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
    return common.base_full_version(version)


def _previous_effective_version(version: Mapping[str, Any]) -> str | None:
    return common.previous_effective_version(version)


def _is_full_baseline(version: Mapping[str, Any]) -> bool:
    return common.is_full_baseline(version)


def _relation_status(version: Mapping[str, Any]) -> str:
    return common.relation_status(version)


def _relation_label(status: str) -> str:
    return common.relation_label(status)


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
    return common.file_review_text(version)


def _file_review_status(version: Mapping[str, Any]) -> str:
    return common.file_review_status(version)


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
        str(lib.get("formal_library_id") or ""),
        str(lib.get("typed_library_id") or ""),
        str(lib.get("library_id") or ""),
        str(lib.get("library_name") or ""),
        str(lib.get("display_name") or ""),
        str(lib.get("report_slug") or ""),
    }
    values.update(str(v) for v in lib.get("aliases", []) or [] if v)
    values.update(v.rsplit("/", 1)[-1] for v in list(values) if v)
    return {v for v in values if v}


def _effective_manifest_candidates(out: Path, lib: Mapping[str, Any]) -> list[Path]:
    safe_libs = {_safe(key) for key in _library_match_keys(lib)}
    candidates: list[Path] = []
    seen: set[Path] = set()
    for safe_lib in sorted(safe_libs):
        bases = [
            out / "libraries" / safe_lib / "effective",
            out / "effective" / safe_lib,
            out / safe_lib / "effective",
            out.parent / "effective" / safe_lib,
            out.parent.parent / "effective" / safe_lib,
        ]
        for base in bases:
            if not base.exists():
                continue
            for path in [base / "effective_manifest.json", *base.glob("*/effective_manifest.json")]:
                if path in seen:
                    continue
                seen.add(path)
                candidates.append(path)
    return candidates


def _discover_effective_reports(out: Path, libraries: list[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    by_key: dict[str, list[dict[str, Any]]] = {str(lib.get("library_id") or lib.get("display_name") or lib.get("library_name") or ""): [] for lib in libraries}
    key_lookup: dict[str, str] = {}
    for lib in libraries:
        canonical = str(lib.get("library_id") or lib.get("display_name") or lib.get("library_name") or "")
        for key in _library_match_keys(lib):
            key_lookup[key] = canonical
    seen: set[Path] = set()
    for lib in libraries:
        for manifest_path in _effective_manifest_candidates(out, lib):
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
    return None


def _version_effective_refs(version_id: str, effective_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    refs = []
    for item in effective_items:
        accepted = {str(v) for v in item.get("accepted_updates", []) or []}
        component_versions = {str(c.get("version_id")) for c in item.get("components", []) or []}
        if str(version_id) in accepted or str(version_id) == str(item.get("base_full_version")) or str(version_id) in component_versions:
            refs.append(item)
    return refs


def _date_hint(value: Any) -> str:
    text = str(value or "")
    match = re.search(r"(20\d{2})[-_]?(\d{2})[-_]?(\d{2})", text)
    if match:
        return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
    return ""


def _event_time_for_node(*values: Any, fallback_index: int = 0) -> tuple[str, str]:
    for value in values:
        text = str(value or "")
        if not text:
            continue
        if re.match(r"20\d{2}-\d{2}-\d{2}", text):
            return text[:10], text
        date = _date_hint(text)
        if date:
            return date, date
    fallback = f"9999-12-31.{fallback_index:06d}"
    return "-", fallback


def _node_package_type(version: Mapping[str, Any]) -> str:
    return common.node_package_type(version)


def _explicit_latest_effective_ref(lib: Mapping[str, Any], effective_items: list[dict[str, Any]]) -> str:
    for key in ["latest_effective_ref", "current_effective_ref", "approved_version", "current_version"]:
        value = lib.get(key)
        if value:
            return str(value)
    for version in lib.get("versions", []) or []:
        if _truthy(version.get("current_effective")):
            return str(version.get("version_id") or version.get("version") or "")
    return ""


def _current_effective_item_ref(effective_items: list[dict[str, Any]]) -> str:
    for item in effective_items:
        if item.get("is_current_effective") or item.get("effective_status") == "current":
            return str(item.get("effective_id") or "")
    return ""


def _effective_source_refs(item: Mapping[str, Any]) -> list[str]:
    refs = []
    base = item.get("base_full_version")
    if base:
        refs.append(str(base))
    refs.extend(str(v) for v in item.get("accepted_updates", []) or [])
    for comp in item.get("components", []) or []:
        version_id = comp.get("version_id")
        if version_id:
            refs.append(str(version_id))
    dedup: list[str] = []
    seen = set()
    for ref in refs:
        if ref and ref not in seen:
            dedup.append(ref)
            seen.add(ref)
    return dedup


def _library_timeline(lib: Mapping[str, Any], effective_items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str]:
    nodes: list[dict[str, Any]] = []
    versions = list(lib.get("versions", []) or [])
    for index, version in enumerate(versions):
        version_id = str(version.get("version_id") or version.get("version") or "")
        package_type = _node_package_type(version)
        event_time, sort_key = _event_time_for_node(
            version.get("event_time"),
            version.get("created_at"),
            version.get("release_date"),
            version_id,
            fallback_index=index,
        )
        refs = _version_effective_refs(version_id, effective_items)
        node = {
            "version_id": version_id,
            "node_kind": "raw",
            "package_type": package_type,
            "event_time": event_time,
            "_sort_key": f"{sort_key}|0|{index:06d}",
            "scan_status": version.get("scan_status") or "unknown",
            "usage_status": "pending_review",
            "base_ref": _base_full_version(version) or _previous_effective_version(version) or "",
            "used_by": [str(item.get("effective_id")) for item in refs],
            "home": str(_version_links(version).get("version_review_html") or ""),
            "scan": str(_version_links(version).get("scan_html") or ""),
            "diffs": [str(_version_links(version).get("diff_html") or "")] if _version_links(version).get("diff_html") else [],
        }
        if refs:
            node["usage_status"] = "accepted" if package_type in {"partial", "hotfix", "doc"} else "superseded"
        elif package_type == "full":
            node["usage_status"] = "usable"
        nodes.append(node)
    for index, item in enumerate(effective_items):
        effective_id = str(item.get("effective_id") or "")
        source_refs = _effective_source_refs(item)
        event_time, sort_key = _event_time_for_node(
            item.get("event_time"),
            effective_id,
            *source_refs,
            item.get("created_at"),
            fallback_index=100000 + index,
        )
        nodes.append({
            "version_id": effective_id,
            "node_kind": "effective",
            "package_type": "composed",
            "event_time": event_time,
            "_sort_key": f"{sort_key}|1|{index:06d}",
            "usage_status": item.get("effective_status") or "usable",
            "sources": source_refs,
            "manifest": str(item.get("manifest") or ""),
            "html": str(item.get("html") or ""),
            "release_preview": str(item.get("release_preview") or ""),
            "file_count": int(item.get("file_count", 0) or 0),
            "conflict_count": int(item.get("conflict_count", 0) or 0),
        })
    nodes.sort(key=lambda x: str(x.get("_sort_key") or ""))
    latest_ref = _explicit_latest_effective_ref(lib, effective_items)
    if not latest_ref:
        current_effective_ref = _current_effective_item_ref(effective_items)
        if current_effective_ref:
            latest_ref = current_effective_ref
            current_index = next((i for i, node in enumerate(nodes) if str(node.get("version_id") or "") == current_effective_ref), -1)
            later_raw_full = [
                node
                for i, node in enumerate(nodes)
                if i > current_index and node.get("node_kind") == "raw" and node.get("package_type") == "full"
            ]
            if later_raw_full:
                latest_ref = str(later_raw_full[-1].get("version_id") or latest_ref)
    for node in nodes:
        if latest_ref and str(node.get("version_id") or "") == latest_ref:
            node["usage_status"] = "current"
            node["effective_pointer"] = "current"
        elif node.get("usage_status") == "current":
            node["usage_status"] = "superseded" if node.get("node_kind") == "effective" or node.get("package_type") == "full" else "accepted"
        node.pop("_sort_key", None)
    return nodes, latest_ref


def _timeline_rows(out: Path, timeline: list[dict[str, Any]], latest_effective_ref: str) -> list[str]:
    rows = []
    for node in reversed(timeline):
        node_kind = str(node.get("node_kind") or "-")
        package_type = str(node.get("package_type") or "-")
        version_id = str(node.get("version_id") or "-")
        usage = str(node.get("usage_status") or "-")
        pointer = "current" if latest_effective_ref and version_id == latest_effective_ref else "-"
        detail_href = node.get("html") or node.get("home")
        if node_kind == "raw" and not detail_href:
            detail_href = node.get("scan") or ((node.get("diffs") or [""])[0])
        source_text = ", ".join(str(v) for v in node.get("sources", []) or []) or ", ".join(str(v) for v in node.get("used_by", []) or []) or node.get("base_ref") or "-"
        rows.append(
            "<tr>"
            f"<td>{ui.esc(node.get('event_time') or '-')}</td>"
            f"<td><b title='{ui.esc(version_id)}'>{ui.esc(_short_name(version_id))}</b></td>"
            f"<td>{ui.badge(node_kind, node_kind)} {ui.badge(package_type, package_type)}</td>"
            f"<td>{ui.badge(usage, usage.replace('_', ' '))}</td>"
            f"<td>{ui.badge('CURRENT' if pointer == 'current' else 'INFO', pointer)}</td>"
            f"<td><span title='{ui.esc(source_text)}'>{ui.esc(_short_name(source_text))}</span></td>"
            f"<td>{ui.action_strip([ui.button('Open', _href(detail_href), 'primary' if pointer == 'current' else 'secondary', disabled=not bool(detail_href), target='_blank')])}</td>"
            "</tr>"
        )
    return rows


def _timeline_for_report_index(out: Path, timeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for node in timeline:
        row = dict(node)
        for key in ["home", "scan", "manifest", "html", "release_preview"]:
            if row.get(key):
                row[key] = _rel_href(out, row.get(key))
        if row.get("diffs"):
            row["diffs"] = [_rel_href(out, path) for path in row.get("diffs", []) if path]
        result.append(row)
    return result


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
        effective_label = str(latest_ref.get("effective_id") or "pending_review")
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
    return ""


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
    user_library_id = lib.get("formal_library_id") or lib.get("library_name") or lib.get("library_id")
    library_label = lib.get("display_name") or user_library_id
    empty_versions = "<div class='catalog-empty'>暂无 version</div>"
    version_list_html = version_rows or empty_versions
    actions = ui.action_strip([
        ui.button("进入库工作台", _href(home_path), "primary", disabled=not bool(home_path), target="_blank"),
        ui.button("Effective", _href((latest_effective_item or {}).get("html")), "secondary", disabled=not bool((latest_effective_item or {}).get("html")), target="_blank"),
    ])
    effective_label = str((latest_effective_item or {}).get("effective_id") or latest_effective or "待确认")
    status_badge = "" if _status_key(status) == "UNKNOWN" else ui.badge(status)
    changed_badge = ui.quiet_badge("CHANGED", changed) if changed else ""
    return (
        f"<section class='library-card' data-overall='{ui.esc(status)}' data-vendor='{ui.esc(vendor)}' data-stages='{ui.esc(','.join(stages))}' data-tags='{ui.esc(','.join(sorted(tags)))}'>"
        "<div class='library-main'>"
        f"<div class='library-name-row'><div class='library-title long-token' title='{ui.esc(library_label)}'>{ui.esc(library_label)}</div></div>"
        f"<div class='library-path-row'><span class='muted'>库名</span><code title='{ui.esc(user_library_id)}'>{ui.esc(user_library_id or '-')}</code></div>"
        f"<div class='library-path-row'><span class='muted'>路径</span><code title='{ui.esc(middle)}'>{ui.esc(middle)}</code></div>"
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
        ("重点文件", recommended, "版本详情证据确认项", "WARNING" if recommended else "PASS"),
        ("待补证据", evidence_pending, "库管理者补 scan / diff", "WARNING" if evidence_pending else "PASS"),
        ("管理任务", actionable_tasks, "见 manager_tasks.json", "INFO" if actionable_tasks else "PASS"),
    ]


VERSION_COUNT_ONLY_TYPES = {"liberty", "lib", "db", "spef", "gds", "oas", "layout", "milkyway", "verilog"}


def _version_scan_dir(version: Mapping[str, Any]) -> Path | None:
    scan = version.get("scan") or {}
    value = scan.get("scan_dir") if isinstance(scan, Mapping) else None
    if not value:
        value = version.get("scan_dir")
    if not value:
        return None
    path = Path(str(value))
    return path if path.exists() else None


def _version_diff_dir(version: Mapping[str, Any]) -> Path | None:
    diff = version.get("diff") or {}
    value = None
    if isinstance(diff, Mapping):
        for key in ["adjacent_diff_dir", "base_diff_dir", "cumulative_diff_dir", "diff_dir"]:
            if diff.get(key):
                value = diff.get(key)
                break
    if not value:
        links = _version_links(version)
        value = links.get("diff_dir") if isinstance(links, Mapping) else None
    if not value:
        return None
    path = Path(str(value))
    return path if path.exists() else None


def _clip_text(text: str, limit: int = 900) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text[: limit - 1] + "..." if len(text) > limit else text


def _version_file_type_counts(inventory: Mapping[str, Any]) -> dict[str, int]:
    direct = inventory.get("file_type_counts")
    if isinstance(direct, Mapping):
        return {str(k): int(v or 0) for k, v in direct.items()}
    counts: dict[str, int] = {}
    for item in inventory.get("files", []) or []:
        file_type = str(item.get("file_type") or "unknown")
        counts[file_type] = counts.get(file_type, 0) + 1
    return dict(sorted(counts.items()))


def _version_count_only_rows(counts: Mapping[str, int]) -> list[str]:
    rows: list[str] = []
    for file_type in sorted(VERSION_COUNT_ONLY_TYPES):
        count = int(counts.get(file_type, 0) or 0)
        if not count:
            continue
        rows.append(
            "<tr>"
            f"<td><code>{ui.esc(file_type)}</code></td>"
            f"<td>{ui.esc(count)}</td>"
            f"<td>{ui.esc('默认只统计数量与文件名线索')}</td>"
            "</tr>"
        )
    return rows


def _version_corner_rows(inventory: Mapping[str, Any]) -> list[str]:
    summary = inventory.get("corner_filename_summary") or {}
    examples = list(summary.get("examples") or [])
    if not examples:
        for item in inventory.get("files", []) or []:
            corner = item.get("corner")
            if isinstance(corner, Mapping) and any(corner.values()):
                examples.append({"file": item.get("path"), "file_type": item.get("file_type"), "corner": corner})
    rows: list[str] = []
    for item in examples[:40]:
        corner = item.get("corner") or {}
        rows.append(
            "<tr>"
            f"<td><code>{ui.esc(item.get('file_type') or '-')}</code></td>"
            f"<td>{ui.esc(corner.get('process') or '-')}</td>"
            f"<td>{ui.esc(corner.get('voltage') or '-')}</td>"
            f"<td>{ui.esc(corner.get('temperature') or '-')}</td>"
            f"<td><code>{ui.esc(item.get('file') or '-')}</code></td>"
            "</tr>"
        )
    return rows


def _stats_value(data: Mapping[str, Any], *keys: str) -> int:
    stats = data.get("stats") if isinstance(data.get("stats"), Mapping) else {}
    for key in keys:
        if key in stats:
            try:
                return int(stats.get(key) or 0)
            except Exception:
                return 0
    for key in keys:
        value = data.get(key)
        if isinstance(value, Mapping):
            return len(value)
        if isinstance(value, list):
            return len(value)
    subckts = data.get("subckts") if isinstance(data.get("subckts"), Mapping) else {}
    if subckts and any(key in {"pin_count", "pins"} for key in keys):
        return sum(_as_int((item or {}).get("pin_count")) for item in subckts.values() if isinstance(item, Mapping))
    if subckts and any(key in {"device_count", "devices", "instance_count", "instances"} for key in keys):
        return sum(_as_int((item or {}).get("device_count")) for item in subckts.values() if isinstance(item, Mapping))
    macros = data.get("macros") if isinstance(data.get("macros"), Mapping) else {}
    if macros and any(key in {"pin_count", "pins"} for key in keys):
        return sum(len((item or {}).get("pins") or {}) for item in macros.values() if isinstance(item, Mapping))
    if macros and any(key in {"layer_count", "layers"} for key in keys):
        layers: set[str] = set()
        for macro in macros.values():
            if not isinstance(macro, Mapping):
                continue
            for pin in ((macro.get("pins") or {}) if isinstance(macro.get("pins"), Mapping) else {}).values():
                if isinstance(pin, Mapping):
                    layers.update(str(x) for x in (pin.get("layers") or []) if str(x))
        return len(layers)
    return 0


def _metric_text(label: str, value: Any) -> str:
    return f"<span class='tiny-tag'><b>{ui.esc(label)}</b>&nbsp;{ui.esc(value)}</span>"


def _format_counts(counts: Mapping[str, int], *, limit: int = 5) -> str:
    pairs = [(str(k), int(v or 0)) for k, v in counts.items() if str(k) and int(v or 0) > 0]
    pairs.sort(key=lambda item: (-item[1], item[0]))
    text = ", ".join(f"{key}:{value}" for key, value in pairs[:limit])
    return text + (", ..." if len(pairs) > limit else "")


def _bump(counts: dict[str, int], value: Any) -> None:
    text = str(value or "").strip()
    if not text:
        return
    counts[text] = counts.get(text, 0) + 1


def _size_text(size: Any) -> str | None:
    if not isinstance(size, Mapping):
        return None
    x = size.get("x")
    y = size.get("y")
    if x is None or y is None:
        return None
    return f"{x}x{y}"


def _iter_lef_pins(data: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    pins: list[Mapping[str, Any]] = []
    macros = data.get("macros") if isinstance(data.get("macros"), Mapping) else {}
    for macro in macros.values():
        if not isinstance(macro, Mapping):
            continue
        for pin in ((macro.get("pins") or {}) if isinstance(macro.get("pins"), Mapping) else {}).values():
            if isinstance(pin, Mapping):
                pins.append(pin)
    return pins


def _lef_used_layers(data: Mapping[str, Any]) -> list[str]:
    explicit = [str(item) for item in (data.get("used_layers") or []) if str(item)]
    if explicit:
        return sorted(set(explicit))
    layers = data.get("layers") if isinstance(data.get("layers"), Mapping) else {}
    found = set(str(name) for name in layers if str(name))
    for pin in _iter_lef_pins(data):
        found.update(str(layer) for layer in (pin.get("layers") or []) if str(layer))
    return sorted(found)


def _iter_cdl_instances(data: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    instances = data.get("instances")
    if isinstance(instances, list):
        return [item for item in instances if isinstance(item, Mapping)]
    out: list[Mapping[str, Any]] = []
    subckts = data.get("subckts") if isinstance(data.get("subckts"), Mapping) else {}
    for subckt in subckts.values():
        if not isinstance(subckt, Mapping):
            continue
        for item in subckt.get("instances") or []:
            if isinstance(item, Mapping):
                out.append(item)
    return out


def _parser_insight_items(file_type: str, data: Mapping[str, Any]) -> list[tuple[str, str]]:
    key = file_type.lower()
    items: list[tuple[str, str]] = []
    stats = data.get("stats") if isinstance(data.get("stats"), Mapping) else {}
    if key == "lef":
        direction_counts: dict[str, int] = {}
        use_counts: dict[str, int] = {}
        for pin in _iter_lef_pins(data):
            _bump(direction_counts, pin.get("direction"))
            _bump(use_counts, pin.get("use"))
        layer_type_counts: dict[str, int] = {}
        layers = data.get("layers") if isinstance(data.get("layers"), Mapping) else {}
        for layer in layers.values():
            if isinstance(layer, Mapping):
                _bump(layer_type_counts, layer.get("type"))
        if direction_counts:
            items.append(("Pin Directions", _format_counts(direction_counts)))
        if use_counts:
            items.append(("Pin Uses", _format_counts(use_counts)))
        if layer_type_counts:
            items.append(("Layer Types", _format_counts(layer_type_counts)))
        used_layers = _lef_used_layers(data)
        if used_layers:
            items.append(("Top Layers", ", ".join(used_layers[:8]) + (" ..." if len(used_layers) > 8 else "")))
        if _as_int(stats.get("pin_rect_count")):
            items.append(("Pin Rects", str(_as_int(stats.get("pin_rect_count")))))
        if _as_int(stats.get("obs_rect_count")):
            items.append(("OBS Rects", str(_as_int(stats.get("obs_rect_count")))))
    elif key == "cdl":
        kind_counts: dict[str, int] = {}
        for instance in _iter_cdl_instances(data):
            _bump(kind_counts, instance.get("kind"))
        if kind_counts:
            items.append(("Instance Types", _format_counts(kind_counts)))
        subckts = data.get("subckts") if isinstance(data.get("subckts"), Mapping) else {}
        pin_counts = {
            str(name): _as_int((subckt or {}).get("pin_count"))
            for name, subckt in subckts.items()
            if isinstance(subckt, Mapping)
        }
        if pin_counts:
            items.append(("Subckt Pins", _format_counts(pin_counts, limit=4)))
    elif key in {"verilog", "systemverilog"}:
        direction_counts: dict[str, int] = {}
        modules = data.get("modules") if isinstance(data.get("modules"), Mapping) else {}
        for module in modules.values():
            if not isinstance(module, Mapping):
                continue
            ports = module.get("ports") if isinstance(module.get("ports"), Mapping) else {}
            for port in ports.values():
                if isinstance(port, Mapping):
                    _bump(direction_counts, port.get("direction"))
        if direction_counts:
            items.append(("Port Directions", _format_counts(direction_counts)))
    return [(label, value) for label, value in items if value]


def _parser_insight_html(file_type: str, data: Mapping[str, Any]) -> str:
    items = _parser_insight_items(file_type, data)
    if not items:
        return ""
    return "<div class='effective-tags parser-insights'>" + "".join(_metric_text(label, value) for label, value in items[:8]) + "</div>"


PARSER_DETAIL_KEYS = [
    "macros",
    "pins",
    "layers",
    "clocks",
    "clock_groups",
    "loads",
    "uncertainties",
    "power_domains",
    "supplies",
    "isolations",
    "retentions",
    "waivers",
    "rules",
    "models",
    "waveforms",
    "points",
    "ports",
    "modules",
    "defines",
    "subckts",
    "instances",
]


def _short_detail_value(value: Any) -> str:
    if isinstance(value, Mapping):
        if "target" in value or "kind" in value:
            parts = []
            if value.get("kind"):
                parts.append(f"kind={value.get('kind')}")
            if value.get("target"):
                parts.append(f"target={value.get('target')}")
            if value.get("pin_count") is not None:
                parts.append(f"pins={value.get('pin_count')}")
            return ", ".join(parts) or str(value.get("name") or "-")
        if "direction" in value or "use" in value or "rect_count" in value:
            parts = []
            if value.get("direction"):
                parts.append(str(value.get("direction")))
            if value.get("use"):
                parts.append(str(value.get("use")))
            layers = value.get("layers") or []
            if layers:
                parts.append("layers=" + ",".join(str(item) for item in layers[:4]))
            if value.get("rect_count") is not None:
                parts.append(f"rects={value.get('rect_count')}")
            return ", ".join(parts) or str(value.get("name") or "-")
        if "type" in value or "width" in value or "pitch" in value:
            parts = []
            for key in ["type", "direction", "width", "pitch", "spacing"]:
                if value.get(key) is not None:
                    parts.append(f"{key}={value.get(key)}")
            return ", ".join(parts) or str(value.get("name") or "-")
        if "pins" in value or "pin_count" in value or "instance_count" in value:
            parts = []
            size = _size_text(value.get("size"))
            if value.get("class"):
                parts.append(f"class={value.get('class')}")
            if size:
                parts.append(f"size={size}")
            if value.get("site"):
                parts.append(f"site={value.get('site')}")
            if value.get("pin_count") is not None:
                parts.append(f"pins={value.get('pin_count')}")
            elif isinstance(value.get("pins"), Mapping):
                parts.append(f"pins={len(value.get('pins') or {})}")
            if value.get("instance_count") is not None:
                parts.append(f"instances={value.get('instance_count')}")
            return ", ".join(parts) or str(value.get("name") or "-")
        if "port_count" in value or "module_count" in value:
            parts = []
            if value.get("port_count") is not None:
                parts.append(f"ports={value.get('port_count')}")
            if value.get("module_count") is not None:
                parts.append(f"modules={value.get('module_count')}")
            return ", ".join(parts) or str(value.get("name") or "-")
        if "name" in value:
            return str(value.get("name") or "-")
        parts = [f"{k}={v}" for k, v in list(value.items())[:3] if not isinstance(v, (dict, list))]
        return ", ".join(parts) or "-"
    return str(value or "-")


def _lef_layer_detail(detail: Any) -> str:
    if not isinstance(detail, Mapping):
        text = str(detail or "").strip()
        return "-" if not text else text
    parts = []
    for key in ["type", "direction", "width", "pitch", "spacing"]:
        value = detail.get(key)
        if value is not None:
            parts.append(f"{key}={value}")
    return ", ".join(parts) or "-"


def _lef_layer_meaning(detail: Any) -> str:
    if not isinstance(detail, Mapping):
        return "tech_layer"
    layer_type = str(detail.get("type") or "").upper()
    if layer_type == "ROUTING":
        return "routing_layer"
    if layer_type == "CUT":
        return "cut_layer"
    return "tech_layer"


def _lef_layer_sort_key(name: str, detail: Any) -> tuple[int, str]:
    if isinstance(detail, Mapping):
        layer_type = str(detail.get("type") or "").upper()
        if layer_type == "ROUTING":
            return (0, name)
        if layer_type == "CUT":
            return (1, name)
        if any(detail.get(key) is not None for key in ["direction", "width", "pitch", "spacing"]):
            return (2, name)
    return (3, name)


def _parser_object_meaning(file_type: str, category: str, name: str, detail: str, source: str = "", raw_detail: Any = None) -> str:
    key = str(file_type or "").lower()
    lower = f"{name} {detail}".lower()
    source_lower = str(source or "").replace("\\", "/").lower()
    if key in {"verilog", "systemverilog"} and category == "modules":
        if "clkgate" in lower or "clockgate" in lower:
            return "clock_gate"
        if "fakeram" in lower or "sram" in lower or "regfile" in lower:
            return "macro_stub"
        if "/yosys/" in f"/{source_lower}" or "yosys/cells_" in source_lower:
            return "yosys_cell_model"
        if lower.startswith("_tech") or "tech" in lower:
            return "support_module"
        return "rtl_module"
    if key == "lef":
        if category == "macros":
            return "physical_macro"
        if category == "pins":
            return "macro_pin"
        if category == "layers":
            return _lef_layer_meaning(raw_detail)
    if key == "cdl":
        if category == "subckts":
            return "circuit_subckt"
        if category == "instances":
            return "circuit_instance"
    if key == "sdc":
        return "constraint_object"
    if key in {"upf", "cpf"}:
        return "power_intent_object"
    if key == "waiver":
        return "waiver_object"
    return "parser_object"


def _parser_detail_items(data: Mapping[str, Any], *, source: Any = None, file_type: str = "", limit: int = 10) -> list[tuple[str, str, str, str, str]]:
    items: list[tuple[str, str, str, str, str]] = []
    source_text = str(source or data.get("file") or "-")
    for key in PARSER_DETAIL_KEYS:
        value = data.get(key)
        if isinstance(value, Mapping):
            entries = value.items()
            if file_type.lower() == "lef" and key == "layers":
                entries = sorted(value.items(), key=lambda item: _lef_layer_sort_key(str(item[0]), item[1]))
            for name, detail in entries:
                short = _lef_layer_detail(detail) if file_type.lower() == "lef" and key == "layers" else _short_detail_value(detail)
                if key == "modules" and short == str(name):
                    short = "module declaration"
                if short == str(name):
                    short = "-"
                items.append((key, str(name), source_text, _parser_object_meaning(file_type, key, str(name), short, source_text, detail), short))
                if len(items) >= limit:
                    return items
        elif isinstance(value, list):
            for entry in value:
                name = str(entry.get("name") or _short_detail_value(entry)) if isinstance(entry, Mapping) else _short_detail_value(entry)
                short = _short_detail_value(entry if isinstance(entry, Mapping) else "")
                if short == name:
                    short = "-"
                items.append((key, name, source_text, _parser_object_meaning(file_type, key, name, short, source_text, entry), short))
                if len(items) >= limit:
                    return items
    return items


def _parser_detail_html(data: Mapping[str, Any]) -> str:
    rows = []
    file_type = str(data.get("file_type") or "")
    for category, name, source, _meaning, _detail in _parser_detail_items(data, source=data.get("file"), file_type=file_type, limit=10):
        rows.append(
            "<tr>"
            f"<td><code>{ui.esc(category)}</code></td>"
            f"<td>{ui.esc(name)}</td>"
            f"<td><code>{ui.esc(source)}</code></td>"
            "</tr>"
        )
    if not rows:
        return "<details class='detail-fold'><summary>解析对象明细</summary><div class='muted-box'>暂无可展示的解析对象示例</div></details>"
    return (
        "<details class='detail-fold parser-detail'><summary>解析对象明细</summary>"
        + ui.table(["对象类型", "代表对象", "来源文件"], rows, "暂无可展示的解析对象示例")
        + "</details>"
    )


def _parser_review_metrics(file_type: str, data: Mapping[str, Any]) -> list[tuple[str, Any]]:
    key = file_type.lower()
    if key == "lef":
        return [("Macros", _stats_value(data, "macro_count", "macros")), ("Pins", _stats_value(data, "pin_count", "pins")), ("Used Layers", _stats_value(data, "layer_count", "layers"))]
    if key in {"verilog", "systemverilog"}:
        return [("Modules", _stats_value(data, "module_count", "modules")), ("Ports", _stats_value(data, "port_count", "ports"))]
    if key == "cdl":
        return [("Subckts", _stats_value(data, "subckt_count", "subckts", "circuits")), ("Pins", _stats_value(data, "pin_count", "pins")), ("Instances", _stats_value(data, "instance_count", "instances", "device_count", "devices"))]
    if key == "sdc":
        return [("Clocks", _stats_value(data, "clock_count", "clocks")), ("Clock Groups", _stats_value(data, "clock_group_count", "clock_groups")), ("Loads", _stats_value(data, "load_count", "loads")), ("Uncertainty", _stats_value(data, "uncertainty_count", "uncertainties"))]
    if key in {"upf", "cpf"}:
        return [("Power Domains", _stats_value(data, "power_domain_count", "power_domains")), ("Supplies", _stats_value(data, "supply_count", "supplies")), ("Isolation", _stats_value(data, "isolation_count", "isolations")), ("Retention", _stats_value(data, "retention_count", "retentions"))]
    if key == "waiver":
        return [("Waivers", _stats_value(data, "waiver_count", "waivers")), ("Rules", _stats_value(data, "rule_count", "rules"))]
    if key == "ibis":
        return [("Models", _stats_value(data, "model_count", "models")), ("Pins", _stats_value(data, "pin_count", "pins"))]
    if key == "pwl":
        return [("Points", _stats_value(data, "point_count", "points")), ("Waveforms", _stats_value(data, "waveform_count", "waveforms"))]
    if key in {"snp", "touchstone"}:
        return [("Ports", _stats_value(data, "port_count", "ports")), ("Samples", _stats_value(data, "sample_count", "samples"))]
    if key == "cpm":
        return [("Entries", _stats_value(data, "entry_count", "entries")), ("Pins", _stats_value(data, "pin_count", "pins"))]
    stats = data.get("stats") if isinstance(data.get("stats"), Mapping) else {}
    return [(str(k).replace("_count", "").replace("_", " ").title(), v) for k, v in list(stats.items())[:4] if str(k).endswith("_count")]


def _parser_scope_html(file_type: str, data: Mapping[str, Any]) -> str:
    key = file_type.lower()
    if key not in {"verilog", "systemverilog"}:
        return ""
    parsed = [str(item) for item in data.get("parsed_fields", []) or [] if str(item)]
    unparsed = [str(item) for item in data.get("unparsed_features", []) or [] if str(item)]
    rows = []
    if parsed:
        rows.append(f"<span class='tiny-tag'><b>Parsed Scope</b>&nbsp;{ui.esc(', '.join(parsed))}</span>")
    if unparsed:
        rows.append(f"<span class='tiny-tag'><b>Not Parsed</b>&nbsp;{ui.esc(', '.join(unparsed))}</span>")
    if not rows:
        return ""
    return "<div class='effective-tags parser-scope'>" + "".join(rows) + "</div>"


def _merge_parser_metrics(target: dict[str, int], file_type: str, data: Mapping[str, Any]) -> None:
    for label, value in _parser_review_metrics(file_type, data):
        target[label] = target.get(label, 0) + _as_int(value)


def _version_parser_aggregate_rows(parser_manifest: Mapping[str, Any], parser_results: Mapping[str, Any]) -> list[str]:
    result_by_path = dict(parser_results or {})
    groups: dict[str, dict[str, Any]] = {}
    for file_entry in parser_manifest.get("files", []) or []:
        for task in file_entry.get("parser_tasks", []) or []:
            parser_name = task.get("parser_name")
            if not parser_name:
                continue
            result = result_by_path.get(task.get("result_path")) or {}
            data = result.get("data") if isinstance(result.get("data"), Mapping) else {}
            file_type = str(result.get("file_type") or file_entry.get("file_type") or "-")
            key = file_type.lower()
            group = groups.setdefault(
                key,
                {
                    "file_type": file_type,
                    "parser_names": set(),
                    "files": [],
                    "status_counts": {},
                    "metrics": {},
                    "details": [],
                    "insights": [],
                    "scope": {"parsed": [], "unparsed": []},
                },
            )
            status = str(task.get("result_status") or task.get("status") or result.get("status") or "UNKNOWN").upper()
            group["parser_names"].add(str(parser_name))
            source_file = str(result.get("file") or file_entry.get("file") or "-")
            if source_file not in group["files"]:
                group["files"].append(source_file)
            group["status_counts"][status] = group["status_counts"].get(status, 0) + 1
            _merge_parser_metrics(group["metrics"], file_type, data)
            group["details"].extend(_parser_detail_items(data, source=result.get("file") or file_entry.get("file"), file_type=file_type, limit=10))
            group["insights"].extend(_parser_insight_items(file_type, data))
            if key in {"verilog", "systemverilog"}:
                for item in data.get("parsed_fields", []) or []:
                    text = str(item)
                    if text and text not in group["scope"]["parsed"]:
                        group["scope"]["parsed"].append(text)
                for item in data.get("unparsed_features", []) or []:
                    text = str(item)
                    if text and text not in group["scope"]["unparsed"]:
                        group["scope"]["unparsed"].append(text)
    rows: list[str] = []
    for key in sorted(groups):
        group = groups[key]
        status = "PASS" if set(group["status_counts"]) <= {"PASS"} else "FAILED" if group["status_counts"].get("FAILED") else "REVIEW"
        metric_html = "<div class='effective-tags'>" + "".join(_metric_text(label, value) for label, value in group["metrics"].items()) + "</div>"
        status_text = ", ".join(f"{k}:{v}" for k, v in sorted(group["status_counts"].items()))
        insight_rows = []
        insight_seen: set[tuple[str, str]] = set()
        for label, value in group["insights"]:
            token = (label, value)
            if token in insight_seen:
                continue
            insight_seen.add(token)
            insight_rows.append(_metric_text(label, value))
            if len(insight_rows) >= 8:
                break
        insight_html = "<div class='effective-tags parser-insights'>" + "".join(insight_rows) + "</div>" if insight_rows else ""
        detail_rows = []
        detail_groups: dict[tuple[str, str], dict[str, Any]] = {}
        for category, name, source, meaning, detail in group["details"]:
            token = (category, name)
            detail_group = detail_groups.setdefault(token, {"sources": []})
            if source not in detail_group["sources"]:
                detail_group["sources"].append(source)
        for (category, name), detail_group in detail_groups.items():
            sources = detail_group["sources"]
            source_html = f"<code>{ui.esc(sources[0] if sources else '-')}</code>"
            if len(sources) > 1:
                source_html += f"<br><span class='muted'>另有 {ui.esc(len(sources) - 1)} 个来源</span>"
            detail_rows.append(
                "<tr>"
                f"<td><code>{ui.esc(category)}</code></td>"
                f"<td>{ui.esc(name)}</td>"
                f"<td>{source_html}</td>"
                "</tr>"
            )
            if len(detail_rows) >= 12:
                break
        scope_html = ""
        if group["scope"]["parsed"] or group["scope"]["unparsed"]:
            scope_html = (
                "<div class='effective-tags parser-scope'>"
                + (f"<span class='tiny-tag'><b>Parsed Scope</b>&nbsp;{ui.esc(', '.join(group['scope']['parsed']))}</span>" if group["scope"]["parsed"] else "")
                + (f"<span class='tiny-tag'><b>Not Parsed</b>&nbsp;{ui.esc(', '.join(group['scope']['unparsed']))}</span>" if group["scope"]["unparsed"] else "")
                + "</div>"
            )
        detail_html = (
            "<details class='detail-fold parser-detail'><summary>解析对象明细</summary>"
            + ui.table(["对象类型", "代表对象", "来源文件"], detail_rows, "暂无可展示的解析对象")
            + "</details>"
        )
        files_html = (
            "<details class='detail-fold'><summary>已解析文件</summary>"
            + "<div class='muted-box'>"
            + "<br>".join(f"<code>{ui.esc(path)}</code>" for path in group["files"][:20])
            + ("<br><span class='muted'>...</span>" if len(group["files"]) > 20 else "")
            + "</div></details>"
        )
        rows.append(
            "<tr>"
            f"<td><b>{ui.esc(str(group['file_type']).upper())}</b><br><code>{ui.esc(', '.join(sorted(group['parser_names'])))}</code></td>"
            f"<td>{ui.badge(status)}</td>"
            f"<td>{ui.esc(len(group['files']))}</td>"
            f"<td>{ui.esc(status_text)}</td>"
            f"<td>{metric_html}{insight_html}{scope_html}{detail_html}</td>"
            f"<td>{files_html}</td>"
            "</tr>"
        )
    return rows


def _version_parser_rows(parser_manifest: Mapping[str, Any], parser_results: Mapping[str, Any]) -> list[str]:
    rows: list[str] = []
    result_by_path = dict(parser_results or {})
    for file_entry in parser_manifest.get("files", []) or []:
        for task in file_entry.get("parser_tasks", []) or []:
            parser_name = task.get("parser_name")
            if not parser_name:
                continue
            result = result_by_path.get(task.get("result_path")) or {}
            data = result.get("data") if isinstance(result.get("data"), Mapping) else {}
            file_type = str(result.get("file_type") or file_entry.get("file_type") or "-")
            metrics = _parser_review_metrics(file_type, data)
            metric_html = "<div class='effective-tags'>" + "".join(_metric_text(label, value) for label, value in metrics) + "</div>" if metrics else ui.muted("-")
            insight_html = _parser_insight_html(file_type, data)
            scope_html = _parser_scope_html(file_type, data)
            detail_html = _parser_detail_html(data)
            rows.append(
                "<tr>"
                f"<td><b>{ui.esc(file_type.upper() if file_type != 'waiver' else 'Waiver')}</b><br><code>{ui.esc(parser_name)}</code></td>"
                f"<td>{ui.badge(str(task.get('result_status') or task.get('status') or result.get('status') or 'UNKNOWN'))}</td>"
                f"<td>{metric_html}{insight_html}{scope_html}{detail_html}</td>"
                f"<td><code>{ui.esc(result.get('file') or file_entry.get('file') or '-')}</code></td>"
                "</tr>"
            )
    return rows


def _summary_metric_rows(summary: Mapping[str, Any]) -> list[str]:
    keys = [
        "status",
        "risk_level",
        "added_files",
        "removed_files",
        "changed_files",
        "view_changes",
        "type_changes",
        "release_evidence_changes",
        "parser_regressions",
        "parser_status_regressions",
        "readiness_regressions",
        "manual_pairwise_tasks",
        "manual_review_items",
        "breaking_changes",
    ]
    rows = []
    for key in keys:
        if key not in summary:
            continue
        rows.append(f"<tr><td><code>{ui.esc(key)}</code></td><td>{ui.esc(summary.get(key))}</td></tr>")
    return rows


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def _relative_display_path(path: Any, *, base: Any = None, tail_parts: int = 4) -> str:
    return common.relative_display_path(path, base=base, tail_parts=tail_parts)


def _raw_relpath(raw_path: Any) -> str:
    p = Path(str(raw_path or ""))
    parts = p.parts[-2:]
    return Path(*parts).as_posix() if parts else "-"


def _diff_view_rows(view_diff: Mapping[str, Any]) -> list[str]:
    rows: list[str] = []
    for item in view_diff.get("views", []) or []:
        if not isinstance(item, Mapping):
            continue
        if not item.get("changed") and str(item.get("severity") or "info").lower() == "info":
            continue
        rows.append(
            "<tr>"
            f"<td><code>{ui.esc(item.get('view') or '-')}</code></td>"
            f"<td>{ui.badge(str(item.get('severity') or 'info').upper())}</td>"
            f"<td>{ui.esc(item.get('old_count') or 0)} → {ui.esc(item.get('new_count') or 0)}</td>"
            f"<td>{ui.esc(item.get('old_status') or '-')} → {ui.esc(item.get('new_status') or '-')}</td>"
            f"<td>{ui.esc(item.get('old_parser_status') or '-')} → {ui.esc(item.get('new_parser_status') or '-')}</td>"
            "</tr>"
        )
    return rows


def _diff_type_rows(type_diff: Mapping[str, Any], *, limit: int = 12) -> list[str]:
    rows: list[str] = []
    by_type = type_diff.get("by_type") if isinstance(type_diff.get("by_type"), Mapping) else {}
    for file_type, item in sorted(by_type.items()):
        if not isinstance(item, Mapping):
            continue
        changed = _as_int(item.get("added_count")) + _as_int(item.get("removed_count")) + _as_int(item.get("changed_count"))
        if not changed:
            continue
        examples = []
        for key in ["added", "removed", "changed"]:
            values = item.get(key) or []
            if isinstance(values, Mapping):
                values = list(values.keys())
            for path in list(values)[:3]:
                examples.append(f"{key}: {path}")
        rows.append(
            "<tr>"
            f"<td><code>{ui.esc(file_type)}</code></td>"
            f"<td>{ui.esc(item.get('old_count') or 0)} → {ui.esc(item.get('new_count') or 0)}</td>"
            f"<td>+{ui.esc(item.get('added_count') or 0)} / -{ui.esc(item.get('removed_count') or 0)} / ~{ui.esc(item.get('changed_count') or 0)}</td>"
            f"<td>{ui.badge(str(item.get('status') or 'CHANGED'))}</td>"
            f"<td><code>{ui.esc('; '.join(examples[:limit]) or '-')}</code></td>"
            "</tr>"
        )
    return rows


def _diff_readiness_rows(readiness_diff: Mapping[str, Any]) -> list[str]:
    rows: list[str] = []
    for key, value in readiness_diff.items():
        if key in {"schema_version", "new_blocking_items", "new_manual_review_items"}:
            continue
        if isinstance(value, Mapping):
            rows.append(
                "<tr>"
                f"<td><code>{ui.esc(key)}</code></td>"
                f"<td>{ui.esc(value.get('old'))}</td>"
                f"<td>{ui.esc(value.get('new'))}</td>"
                f"<td>{ui.esc(value.get('delta') if 'delta' in value else '-')}</td>"
                "</tr>"
            )
    for item in readiness_diff.get("new_blocking_items", []) or []:
        if isinstance(item, Mapping):
            rows.append(
                "<tr>"
                f"<td><code>new_blocker</code></td>"
                f"<td>-</td><td>{ui.esc(item.get('title') or item.get('category') or '-')}</td>"
                f"<td>{ui.esc(item.get('message') or '-')}</td>"
                "</tr>"
            )
    return rows


def _diff_issue_rows(diff_dir: Path | None, *, limit: int = 20) -> list[str]:
    issues = common.version_diff_json(diff_dir, "diff_issues.json").get("issues") if diff_dir else []
    rows: list[str] = []
    for item in list(issues or [])[:limit]:
        if not isinstance(item, Mapping):
            continue
        rows.append(
            "<tr>"
            f"<td>{ui.badge(str(item.get('severity') or 'info').upper())}</td>"
            f"<td>{ui.esc(item.get('category') or '-')}</td>"
            f"<td>{ui.esc(item.get('title') or '-')}</td>"
            f"<td>{ui.esc(item.get('message') or '-')}</td>"
            "</tr>"
        )
    return rows


def _version_diff_evidence_panel(version: Mapping[str, Any]) -> str:
    diff_dir = _version_diff_dir(version)
    if not diff_dir:
        return ui.panel("Diff Evidence", "Run compare to populate version-level diff evidence.", ui.muted("No diff directory is registered for this version."))
    view_diff = common.version_diff_json(diff_dir, "view_diff.json")
    type_diff = common.version_diff_json(diff_dir, "type_diff.json")
    readiness_diff = common.version_diff_json(diff_dir, "release_readiness_diff.json")
    summary = common.version_diff_summary(diff_dir)
    return ui.panel(
        "Diff Evidence",
        "Concrete comparison evidence embedded from the standalone comparison JSON. Open the full diff page only when you need the complete evidence trail.",
        ui.metric_grid([
            ("Status", summary.get("status") or "NO_DIFF", _relative_display_path(diff_dir, tail_parts=5), summary.get("status")),
            ("Files", f"+{summary.get('added_files', 0)} / -{summary.get('removed_files', 0)} / ~{summary.get('changed_files', 0)}", "added / removed / changed", "WARNING" if _as_int(summary.get("removed_files")) or _as_int(summary.get("changed_files")) else "INFO"),
            ("Views", summary.get("view_changes", 0), "view-level changes", "WARNING" if _as_int(summary.get("view_changes")) else "PASS"),
            ("Readiness", f"{(readiness_diff.get('bundle_status') or {}).get('old', '-')} → {(readiness_diff.get('bundle_status') or {}).get('new', '-')}", "release readiness delta", "BLOCK" if (readiness_diff.get("bundle_status") or {}).get("new") == "BLOCK" else "INFO"),
        ])
        + _scroll_table(["View", "Severity", "Count", "Status", "Parser"], _diff_view_rows(view_diff), "No changed views", "diff-view-scroll")
        + _scroll_table(["Type", "Count", "Delta", "Status", "Examples"], _diff_type_rows(type_diff), "No type changes", "diff-type-scroll")
        + _scroll_table(["Readiness", "Old", "New", "Delta / Message"], _diff_readiness_rows(readiness_diff), "No release readiness delta", "diff-readiness-scroll")
        + _scroll_table(["Severity", "Category", "Title", "Message"], _diff_issue_rows(diff_dir), "No diff issues", "diff-issue-scroll"),
    )


def _scroll_table_facets(class_name: str, headers: list[str]) -> list[tuple[int, str]]:
    preferred = {
        "metric-scroll": [0],
        "change-scroll": [0, 1, 3],
        "view-coverage-scroll": [0, 1, 3, 4, 5],
        "corner-detail-scroll": [0, 1, 2, 3],
        "unknown-detail-scroll": [0],
        "diff-view-scroll": [0, 1, 3, 4],
        "diff-type-scroll": [0, 3],
        "diff-readiness-scroll": [0],
        "diff-issue-scroll": [0, 1],
        "review-gate-blocking-scroll": [1, 2],
        "review-gate-attention-scroll": [1, 2],
    }
    indexes = preferred.get(class_name)
    if indexes is None:
        indexes = [0, 1] if len(headers) > 1 else [0]
    return [(index, headers[index]) for index in indexes if 0 <= index < len(headers)]


def _scroll_table(headers: list[str], rows: list[str], empty: str, class_name: str) -> str:
    table_id = "tbl-" + _safe(class_name)
    return ui.faceted_table(
        table_id,
        headers,
        rows,
        empty,
        "搜索当前表格...",
        _scroll_table_facets(class_name, headers),
        wrap_class=f"version-scroll-table {class_name}",
    )


def _absolute_path_box(label: str, path: Any) -> str:
    if not path:
        text = "-"
    else:
        p = Path(str(path))
        try:
            text = str(p if p.is_absolute() else p.resolve())
        except Exception:
            text = str(p)
    return f"<div class='absolute-path-box'><b>{ui.esc(label)}</b><code>{ui.esc(text)}</code></div>"


def _render_version_page(out: Path, lib: Mapping[str, Any], version: Mapping[str, Any]) -> str:
    from lib_guard.render.version_detail_report import render_version_detail_page

    return render_version_detail_page(out, lib, version)


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
        timeline, latest_effective_ref = _library_timeline(lib, effective_items)
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
            "latest_effective_ref": latest_effective_ref,
            "timeline": _timeline_for_report_index(out, timeline),
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


def _selector_aliases(value: Any) -> set[str]:
    text = str(value or "").strip()
    if not text:
        return set()
    aliases = {text, _safe(text)}
    aliases.add(text.replace("/", "."))
    aliases.add(text.replace("/", "_"))
    aliases.add(text.replace(".", "_"))
    if "/" in text:
        tail = text.split("/", 1)[1]
        aliases.update({tail, tail.replace("/", "."), tail.replace("/", "_"), _safe(tail)})
    return {alias for alias in aliases if alias}


def _library_selector_aliases(lib: Mapping[str, Any]) -> set[str]:
    aliases: set[str] = set()
    for key in ("library_id", "library_name", "display_name"):
        aliases.update(_selector_aliases(lib.get(key)))
    for alias in lib.get("aliases", []) or []:
        aliases.update(_selector_aliases(alias))
    return aliases


def _version_selector_aliases(version: Mapping[str, Any]) -> set[str]:
    aliases: set[str] = set()
    for key in ("version_id", "version", "name"):
        aliases.update(_selector_aliases(version.get(key)))
    aliases.update(_selector_aliases(version.get("version_key")))
    return aliases


def _selector_values(selector: Any) -> list[str]:
    if not selector:
        return []
    if isinstance(selector, (list, tuple, set)):
        return [str(item).strip() for item in selector if str(item).strip()]
    return [str(selector).strip()]


def _matches_selector(aliases: set[str], selector: Any) -> bool:
    values = _selector_values(selector)
    if not values:
        return True
    return any(value in aliases for value in values)


def _first_existing_state_match(item: Mapping[str, Any], old_items: list[Mapping[str, Any]], alias_fn: Any) -> Mapping[str, Any]:
    aliases = alias_fn(item)
    for old in old_items:
        if aliases & alias_fn(old):
            return old
    return {}


def _preserve_unrendered_catalog_links(
    out: Path,
    state: Mapping[str, Any],
    *,
    library_filter: str | None,
    version_filter: str | None,
) -> None:
    if not library_filter and not version_filter:
        return
    previous = read_json(out / "catalog_state.json", default={}) or {}
    old_libraries = [item for item in previous.get("libraries", []) or [] if isinstance(item, Mapping)]
    if not old_libraries:
        return
    for lib in state.get("libraries", []) or []:
        if not isinstance(lib, dict):
            continue
        old_lib = _first_existing_state_match(lib, old_libraries, _library_selector_aliases)
        if not old_lib:
            continue
        lib_selected = _matches_selector(_library_selector_aliases(lib), library_filter)
        if not lib_selected:
            if old_lib.get("library_home_html") and not lib.get("library_home_html"):
                lib["library_home_html"] = old_lib.get("library_home_html")
        old_versions = [item for item in old_lib.get("versions", []) or [] if isinstance(item, Mapping)]
        for version in lib.get("versions", []) or []:
            if not isinstance(version, dict):
                continue
            version_selected = lib_selected and _matches_selector(_version_selector_aliases(version), version_filter)
            if version_selected:
                continue
            old_version = _first_existing_state_match(version, old_versions, _version_selector_aliases)
            old_links = old_version.get("links") if isinstance(old_version.get("links"), Mapping) else {}
            if old_links:
                merged_links = dict(old_links)
                merged_links.update(version.get("links") or {})
                version["links"] = merged_links


def render_catalog_html(
    catalog_json: str | Path,
    out_dir: str | Path,
    *,
    render_library_pages: bool = True,
    max_attention_items: int = 10,
    max_report_rows: int = 16,
    library_filter: str | None = None,
    version_filter: str | None = None,
) -> dict[str, Any]:
    from lib_guard.render.catalog_workspace_report import render_catalog_index_page, render_library_workspace_page
    from lib_guard.render.version_detail_report import render_version_detail_page

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
    rendered_libraries = 0
    rendered_versions = 0
    if render_library_pages:
        for lib in state.get("libraries", []) or []:
            if not _matches_selector(_library_selector_aliases(lib), library_filter):
                continue
            for version in lib.get("versions", []) or []:
                if not _matches_selector(_version_selector_aliases(version), version_filter):
                    continue
                links = version.setdefault("links", {})
                links["version_review_html"] = render_version_detail_page(out, lib, version)
                rendered_versions += 1
                gate = version.get("review_gate") if isinstance(version.get("review_gate"), Mapping) else {}
                if gate.get("gate_file"):
                    write_json(gate["gate_file"], gate)
            lib_id = str(lib.get("typed_library_id") or lib.get("library_id") or lib.get("formal_library_id") or lib.get("library_name") or "")
            lib["library_home_html"] = render_library_workspace_page(out, lib, _effective_items_for_lib(effective_by_lib, lib), list(compare_by_lib.get(lib_id, []) or []))
            rendered_libraries += 1
    _preserve_unrendered_catalog_links(out, state, library_filter=library_filter, version_filter=version_filter)
    report_index = _write_report_index(out, state, effective_by_lib, compare_by_lib)
    for stale_name in ("review_state.json", "review_tasks.json"):
        stale_path = out / stale_name
        if stale_path.exists():
            stale_path.unlink()
    write_json(out / "catalog_state.json", state)
    write_json(out / "manager_tasks.json", tasks)
    html = render_catalog_index_page(
        out,
        state,
        tasks,
        effective_by_lib,
        compare_by_lib,
        max_attention_items=max_attention_items,
        max_report_rows=max_report_rows,
        report_index=report_index,
        catalog_json=catalog_json,
    )
    index = out / "index.html"
    _write_text(index, html)
    return {
        "status": "PASS",
        "index_html": str(index),
        "catalog_state": str(out / "catalog_state.json"),
        "manager_tasks": str(out / "manager_tasks.json"),
        "report_index": report_index,
        "rendered_libraries": rendered_libraries,
        "rendered_versions": rendered_versions,
        "library_filter": library_filter,
        "version_filter": version_filter,
    }
