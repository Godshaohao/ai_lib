"""Catalog HTML renderer.

Catalog UI is a lightweight review entry. It links to Scan/Diff/Release evidence
instead of duplicating those reports. Catalog discovery and runtime state stay in
lib_guard.catalog.index; generated HTML remains an output artifact.
"""

from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any, Mapping

from lib_guard.catalog.index import STAGES, _read_json


def _esc(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def _display_status(value: Any) -> str:
    text = str(value or "")
    labels = {
        "PASS": "通过",
        "READY": "可用",
        "SCANNED": "已扫描",
        "DONE": "完成",
        "DIFF_DONE": "已比较",
        "DIFF": "有变化",
        "DRY_RUN": "预演",
        "APPLIED": "已应用",
        "PASS_WITH_WARNING": "通过但需关注",
        "WARNING": "需关注",
        "WARN": "需关注",
        "PENDING": "待处理",
        "NOT_SCANNED": "未扫描",
        "NEEDS_REVIEW": "需人工确认",
        "PASS_EMPTY": "空结果",
        "BLOCK": "阻塞",
        "BLOCKED": "阻塞",
        "FAILED": "失败",
        "ERROR": "错误",
        "BLOCKER": "阻塞项",
        "MANUAL_REVIEW": "需人工确认",
        "UNKNOWN": "未知",
        "NOT_APPLICABLE": "不适用",
        "INFO": "信息",
        "release_blocked": "Release blocked",
        "release_failed": "Release failed",
        "scan_blocked": "Scan blocked",
        "scan_failed": "Scan failed",
        "stage_unknown": "Stage unknown",
        "unclear_parent_base": "Unclear parent/base",
        "unknown": "unknown",
        "ad-hoc": "ad-hoc",
        "dated": "dated",
        "stable": "stable",
        "initial": "initial",
        "final": "final",
        "ip": "IP",
    }
    return labels.get(text, labels.get(text.upper(), text))


def _page_name(text: Any) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(text or "library")).strip("._")
    return safe or "library"


def _file_href(path: Any) -> str:
    if not path:
        return ""
    text = str(path)
    if text.startswith(("http://", "https://", "file://")):
        return text
    try:
        return Path(text).resolve().as_uri()
    except Exception:
        return text.replace("\\", "/")


def _js_arg(text: str) -> str:
    return _esc(json.dumps(text, ensure_ascii=False))


def _versions(lib: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return list(lib.get("versions", []) or [])


def _latest_catalog_version(lib: Mapping[str, Any]) -> Mapping[str, Any]:
    versions = _versions(lib)
    return versions[-1] if versions else {}


def _version_label(version: Mapping[str, Any]) -> str:
    return str(version.get("version_key") or version.get("version_id") or "No version")


def _stage_value(version: Mapping[str, Any]) -> str:
    value = str(version.get("stage") or "").strip()
    return value if value else "unknown"


def _scan(version: Mapping[str, Any]) -> Mapping[str, Any]:
    return version.get("scan", {}) or {}


def _diff(version: Mapping[str, Any]) -> Mapping[str, Any]:
    return version.get("diff", {}) or {}


def _release(version: Mapping[str, Any]) -> Mapping[str, Any]:
    return version.get("release", {}) or {}


def _has_scan_evidence(version: Mapping[str, Any]) -> bool:
    scan = _scan(version)
    return bool(scan.get("scan_html") or scan.get("scan_dir"))


def _has_diff_evidence(version: Mapping[str, Any]) -> bool:
    diff = _diff(version)
    return bool(diff.get("adjacent_diff_html") or diff.get("cumulative_diff_html") or diff.get("diff_html"))


def _has_release_evidence(version: Mapping[str, Any]) -> bool:
    release = _release(version)
    return bool(
        release.get("release_html")
        or release.get("postcheck_json")
        or release.get("manifest_json")
        or release.get("check_json")
        or release.get("link_json")
        or release.get("release_dir")
    )


def _scan_link(version: Mapping[str, Any]) -> str:
    return str(_scan(version).get("scan_html") or _scan(version).get("scan_dir") or "")


def _diff_link(version: Mapping[str, Any]) -> str:
    diff = _diff(version)
    return str(diff.get("adjacent_diff_html") or diff.get("cumulative_diff_html") or diff.get("diff_html") or "")


def _release_link(version: Mapping[str, Any]) -> str:
    release = _release(version)
    return str(
        release.get("release_html")
        or release.get("postcheck_json")
        or release.get("manifest_json")
        or release.get("check_json")
        or release.get("link_json")
        or ""
    )


def _evidence_links(version: Mapping[str, Any], *, include_detail: str = "") -> str:
    from lib_guard.render.product_theme import evidence_link

    scan_path = _scan_link(version)
    diff_path = _diff_link(version)
    release_path = _release_link(version)
    links = [
        evidence_link("Scan", _file_href(scan_path), missing="Not run"),
        evidence_link("Diff", _file_href(diff_path), missing="Not run"),
        evidence_link("Release", _file_href(release_path), missing="Missing"),
    ]
    if include_detail:
        links.insert(0, evidence_link("Open detail", include_detail, missing="Missing"))
    return "<div class='evidence-links'>" + "".join(links) + _trace_paths(scan_path, diff_path, release_path) + "</div>"


def _trace_paths(*paths: Any) -> str:
    return "".join(f"<span class='trace-path'>{_esc(path)}</span>" for path in paths if path)


def _folded_path(label: str, path: Any) -> str:
    from lib_guard.render.product_theme import details_block, mono_path

    if not path:
        return "<span class='muted'>-</span>"
    return details_block(label, mono_path(path))


def _catalog_version_report_counts(lib: Mapping[str, Any]) -> dict[str, int]:
    counts = {"scan": 0, "diff": 0, "release": 0}
    for version in _versions(lib):
        counts["scan"] += 1 if _has_scan_evidence(version) else 0
        counts["diff"] += 1 if _has_diff_evidence(version) else 0
        counts["release"] += 1 if _has_release_evidence(version) else 0
    return counts


def _catalog_stage_mix(lib: Mapping[str, Any]) -> str:
    stage_counts: dict[str, int] = {}
    for version in _versions(lib):
        key = _stage_value(version).lower()
        stage_counts[key] = stage_counts.get(key, 0) + 1
    parts = []
    for key in ["initial", "stable", "final", "ad-hoc", "dated", "unknown"]:
        value = int(stage_counts.get(key, 0) or 0)
        if value:
            parts.append(f"{_esc(_display_status(key))} {value}")
    return " / ".join(parts) if parts else "-"


def _library_discovery_source(lib: Mapping[str, Any]) -> str:
    for version in _versions(lib):
        detected = version.get("detected", {}) or {}
        source = detected.get("discovery_source")
        rule = detected.get("structure_rule")
        if source:
            return f"{source} / {rule or '-'}"
        if rule:
            return str(rule)
    return "-"


def _catalog_home_metrics(catalog: Mapping[str, Any]) -> dict[str, int]:
    libraries = list(catalog.get("libraries", []) or [])
    versions = [version for lib in libraries for version in _versions(lib)]
    priority_items = _catalog_priority_items(catalog, max_items=100000)
    return {
        "libraries": len(libraries),
        "versions": len(versions),
        "scan_evidence": sum(1 for version in versions if _has_scan_evidence(version)),
        "diff_evidence": sum(1 for version in versions if _has_diff_evidence(version)),
        "release_evidence": sum(1 for version in versions if _has_release_evidence(version)),
        "manual_confirmation": len(priority_items),
        "unknown_stage": sum(1 for version in versions if _stage_value(version).lower() in {"", "unknown", "unknown_stage", "-"}),
        "blocked_scan_release": sum(1 for item in priority_items if str(item.get("kind")) in {"scan_blocked", "scan_failed", "release_blocked", "release_failed"}),
    }


def _catalog_metric_cards(metrics: Mapping[str, int]) -> str:
    from lib_guard.render.product_theme import product_summary

    return product_summary(
        [
            ("Libraries", metrics.get("libraries", 0), "Catalog 中登记的库数量", "PASS"),
            ("Versions", metrics.get("versions", 0), "所有库版本总数", "PASS"),
            ("Scan Evidence", metrics.get("scan_evidence", 0), "已有 scan 报告或 scan_dir", "PASS"),
            ("Diff Evidence", metrics.get("diff_evidence", 0), "已有结构变化报告", "PASS"),
            ("Release Evidence", metrics.get("release_evidence", 0), "已有 release/postcheck 证据", "PASS"),
            ("Manual Confirmation", metrics.get("manual_confirmation", 0), "影响 catalog 可信度的确认项", "WARNING" if metrics.get("manual_confirmation") else "PASS"),
            ("Unknown Stage", metrics.get("unknown_stage", 0), "stage 为空或 unknown", "WARNING" if metrics.get("unknown_stage") else "PASS"),
            ("Blocked Scan/Release", metrics.get("blocked_scan_release", 0), "scan/release 阻塞或失败", "WARNING" if metrics.get("blocked_scan_release") else "PASS"),
        ]
    )


def _catalog_priority_items(catalog: Mapping[str, Any], max_items: int = 10, library_id: str | None = None) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for lib in catalog.get("libraries", []) or []:
        if library_id and str(lib.get("library_id") or "") != library_id:
            continue
        library_name = str(lib.get("library_name") or lib.get("library_id") or "")
        detail_href = f"libraries/{_page_name(library_name)}.html"
        for version in _versions(lib):
            release = _release(version)
            scan = _scan(version)
            lineage = version.get("lineage", {}) or {}
            parent = lineage.get("parent_candidate") or lineage.get("parent")
            base = version.get("base_version") or lineage.get("base_candidate") or lineage.get("base")
            version_key = _version_label(version)
            stage = _stage_value(version)
            common = {
                "library_id": lib.get("library_id"),
                "library_name": library_name,
                "version_key": version_key,
                "stage": stage,
                "scan_html": _scan_link(version),
                "diff_html": _diff_link(version),
                "release_html": _release_link(version),
                "raw_path": version.get("raw_path"),
                "detail_href": detail_href,
            }
            release_status = str(release.get("status") or release.get("check_status") or "").upper()
            if release_status in {"BLOCK", "BLOCKED"}:
                items.append({**common, "priority": "P0", "kind": "release_blocked", "message": "Release 证据阻塞，需要先查看 release evidence。", "action": "Open release evidence"})
            elif release_status in {"FAILED", "ERROR"}:
                items.append({**common, "priority": "P0", "kind": "release_failed", "message": "Release 执行或校验失败，需要确认 manifest/link/postcheck。", "action": "Open release evidence"})
            scan_status = str(scan.get("status") or "").upper()
            if scan_status in {"BLOCK", "BLOCKED"}:
                items.append({**common, "priority": "P0", "kind": "scan_blocked", "message": "Scan 结果阻塞，Catalog 不能把该版本视为可信证据。", "action": "Open scan evidence"})
            elif scan_status in {"FAILED", "ERROR"}:
                items.append({**common, "priority": "P0", "kind": "scan_failed", "message": "Scan 失败，需要重新运行或查看 scan evidence。", "action": "Open scan evidence"})
            if stage.lower() in {"", "unknown", "unknown_stage", "-"}:
                items.append({**common, "priority": "P1", "kind": "stage_unknown", "message": "版本阶段未识别，需要人工确认 initial/stable/final/ad-hoc。", "action": "Confirm stage"})
            if version.get("manual_review") and stage.lower() not in {"", "unknown", "unknown_stage", "-"} and (not parent or (version.get("base_required") and not base)):
                items.append({**common, "priority": "P1", "kind": "unclear_parent_base", "message": "parent/base 不清楚，需要人工补齐版本关系。", "action": "Check parent/base"})
    rank = {"P0": 0, "P1": 1, "P2": 2}
    return sorted(items, key=lambda item: (rank.get(str(item.get("priority")), 9), str(item.get("library_name")), str(item.get("version_key"))))[:max_items]


def _catalog_attention_table(catalog: Mapping[str, Any], max_items: int = 10) -> str:
    from lib_guard.render.product_theme import badge, details_block, evidence_link, mono_path, table

    rows: list[str] = []
    for item in _catalog_priority_items(catalog, max_items=max_items):
        evidence = [
            evidence_link("Library detail", item.get("detail_href")),
            evidence_link("Scan", _file_href(item.get("scan_html")), missing="Not run"),
            evidence_link("Release", _file_href(item.get("release_html")), missing="Missing"),
        ]
        trace = _trace_paths(item.get("scan_html"), item.get("diff_html"), item.get("release_html"))
        raw_path = details_block("source path", mono_path(item.get("raw_path"))) if item.get("raw_path") else ""
        action = item.get("action") or "Open library detail"
        rows.append(
            "<tr>"
            f"<td>{badge(item.get('kind'), _display_status(item.get('kind')))}</td>"
            f"<td><b>{_esc(item.get('library_name'))}</b><div class='sub'>{_esc(item.get('library_id'))}</div></td>"
            f"<td><code>{_esc(item.get('version_key'))}</code></td>"
            f"<td>{badge(item.get('stage'), _display_status(item.get('stage')))}</td>"
            f"<td>{_esc(item.get('message'))}</td>"
            f"<td><div class='evidence-links'>{''.join(evidence)}{trace}</div>{raw_path}</td>"
            f"<td><a class='btn secondary' href='{_esc(item.get('detail_href'))}'>{_esc(action)}</a></td>"
            "</tr>"
        )
    return table(["Category", "Library", "Version", "Stage", "Issue", "Evidence", "Action"], rows, "暂无影响 catalog 可信度的确认项")


def _catalog_library_rows(libraries: list[Mapping[str, Any]]) -> list[str]:
    from lib_guard.render.product_theme import badge, compact_meta, evidence_link

    rows: list[str] = []
    ordered = sorted(
        libraries,
        key=lambda lib: (
            -int((lib.get("summary", {}) or {}).get("manual_review", 0) or 0),
            -int(((lib.get("summary", {}) or {}).get("stage_counts", {}) or {}).get("unknown", 0) or 0),
            -len(_versions(lib)),
            str(lib.get("library_name") or ""),
        ),
    )
    for lib in ordered:
        summary = lib.get("summary", {}) or {}
        latest = _latest_catalog_version(lib)
        reports = _catalog_version_report_counts(lib)
        href = f"libraries/{_page_name(lib.get('library_name'))}.html"
        manual = int(summary.get("manual_review", 0) or sum(1 for version in _versions(lib) if version.get("manual_review")))
        unknown = sum(1 for version in _versions(lib) if _stage_value(version).lower() in {"", "unknown", "unknown_stage", "-"})
        latest_label = _version_label(latest) if latest else "No version"
        review_text = "Needs review" if manual or unknown else "Clear"
        rows.append(
            f"<tr data-type='{_esc(lib.get('library_type'))}' data-status='{_esc('manual' if manual or unknown else 'ready')}' data-unknown='{_esc('yes' if unknown else 'no')}'>"
            f"<td><a class='link' href='{_esc(href)}'>{_esc(lib.get('library_name'))}</a><div class='sub'>{_esc(lib.get('library_id'))}</div></td>"
            f"<td>{compact_meta([('Alias', ', '.join(str(a) for a in lib.get('aliases', []) or []) or '-'), ('Vendor', lib.get('vendor') or '-'), ('Middle', lib.get('middle_path') or '-'), ('Category', lib.get('category') or '-')])}</td>"
            f"<td>{_folded_path('library_root', lib.get('library_root'))}<div class='sub'>{_esc(_library_discovery_source(lib))}</div></td>"
            f"<td><code>{_esc(latest_label)}</code><div>{badge(_stage_value(latest), _display_status(_stage_value(latest))) if latest else ''}</div></td>"
            f"<td>{_esc(_catalog_stage_mix(lib))}</td>"
            f"<td><b>{_esc(len(_versions(lib)))}</b> versions</td>"
            f"<td>{compact_meta([('Scan', reports['scan']), ('Diff', reports['diff']), ('Release', reports['release'])])}</td>"
            f"<td>{badge('NEEDS_REVIEW' if manual or unknown else 'PASS', review_text)}<div class='sub'>{_esc(manual)} manual / {_esc(unknown)} unknown</div></td>"
            f"<td><div class='evidence-links'>{evidence_link('Open detail', href)}{evidence_link('Scan', _file_href(_scan_link(latest)), missing='Not run')}{evidence_link('Diff', _file_href(_diff_link(latest)), missing='Not run')}{evidence_link('Release', _file_href(_release_link(latest)), missing='Missing')}{_trace_paths(_scan_link(latest), _diff_link(latest), _release_link(latest))}</div></td>"
            "</tr>"
        )
    return rows


def _catalog_report_rows(libraries: list[Mapping[str, Any]], max_rows: int = 16) -> list[str]:
    from lib_guard.render.product_theme import badge, evidence_link

    candidates: list[tuple[int, str, str, str, str, str]] = []
    for lib in libraries:
        library_name = str(lib.get("library_name") or lib.get("library_id") or "")
        for version in _versions(lib):
            version_label = _version_label(version)
            stage = _stage_value(version)
            priority = 20 if version.get("manual_review") else 0
            release_type = "Release" if _release(version).get("release_html") else "Release JSON"
            links = [
                ("Scan", _scan_link(version), 30),
                ("Diff", _diff_link(version), 20),
                (release_type, _release_link(version), 25),
            ]
            for report_type, href, weight in links:
                if href:
                    candidates.append((priority + weight, library_name, version_label, report_type, stage, href))
    candidates.sort(key=lambda item: (-item[0], item[1], item[2], item[3]))
    rows = []
    for _, library_name, version_label, report_type, stage, href in candidates[:max_rows]:
        rows.append(
            "<tr>"
            f"<td><b>{_esc(library_name)}</b></td>"
            f"<td><code>{_esc(version_label)}</code></td>"
            f"<td>{badge(report_type, report_type)}</td>"
            f"<td>{badge(stage, _display_status(stage))}</td>"
            f"<td>{evidence_link('Open evidence', _file_href(href))}{_trace_paths(href)}</td>"
            "</tr>"
        )
    return rows


def _lineage_summary(version: Mapping[str, Any]) -> str:
    lineage = version.get("lineage", {}) or {}
    parent = lineage.get("parent_candidate") or lineage.get("parent") or "-"
    base = version.get("base_version") or lineage.get("base_candidate") or lineage.get("base") or "-"
    return f"parent: {parent} / base: {base}"


def _manual_review_summary(version: Mapping[str, Any]) -> str:
    value = version.get("manual_review")
    if not value:
        return "-"
    if isinstance(value, list):
        return "; ".join(str(item) for item in value)
    if isinstance(value, Mapping):
        return json.dumps(value, ensure_ascii=False)
    return "Needs review" if value is True else str(value)


def _version_simple_rows(lib: Mapping[str, Any]) -> list[str]:
    from lib_guard.render.product_theme import badge

    rows: list[str] = []
    for version in _versions(lib):
        lineage = _lineage_summary(version)
        manual = _manual_review_summary(version)
        rows.append(
            f"<tr data-stage='{_esc(_stage_value(version))}' data-scan='{_esc(str(_scan(version).get('status') or 'NOT_RUN'))}' data-release='{_esc(str(_release(version).get('status') or 'MISSING'))}'>"
            f"<td><code>{_esc(_version_label(version))}</code><div class='sub'>{_esc(version.get('version_id') or '-')}</div></td>"
            f"<td>{badge(_stage_value(version), _display_status(_stage_value(version)))}</td>"
            f"<td>{_folded_path('lineage', lineage)}</td>"
            f"<td>{badge('NEEDS_REVIEW' if version.get('manual_review') else 'PASS', 'Needs review' if version.get('manual_review') else 'Clear')}{_folded_path('detail', manual) if version.get('manual_review') else ''}</td>"
            f"<td>{_evidence_links(version).split('</div>')[0]}</div></td>"
            f"<td>{_folded_path('source', version.get('raw_path'))}</td>"
            "</tr>"
        )
    return rows


def _render_library_page(catalog: Mapping[str, Any], lib: Mapping[str, Any], out: Path, catalog_path: str | Path) -> str:
    from lib_guard.render.product_theme import action_bar, compact_meta, collapsible_panel, faceted_table, page_shell, panel, product_summary, table

    library_dir = out / "libraries"
    library_dir.mkdir(parents=True, exist_ok=True)
    page = library_dir / f"{_page_name(lib.get('library_name'))}.html"
    versions = _versions(lib)
    latest = _latest_catalog_version(lib)
    reports = _catalog_version_report_counts(lib)
    priority_items = _catalog_priority_items(catalog, max_items=100000, library_id=str(lib.get("library_id") or ""))
    unknown = sum(1 for version in versions if _stage_value(version).lower() in {"", "unknown", "unknown_stage", "-"})
    cards = product_summary(
        [
            ("Versions", len(versions), "该库登记的版本数", "PASS"),
            ("Latest Version", _version_label(latest) if latest else "-", "按 catalog 顺序显示", "PASS"),
            ("Reports", f"S{reports['scan']} / D{reports['diff']} / R{reports['release']}", "scan / diff / release evidence", "PASS" if any(reports.values()) else "UNKNOWN"),
            ("Manual Confirmation", len(priority_items), "影响 catalog 可信度的确认项", "WARNING" if priority_items else "PASS"),
            ("Unknown Stage", unknown, "stage unknown 版本数", "WARNING" if unknown else "PASS"),
            ("Stage Mix", _catalog_stage_mix(lib), "版本阶段构成", "PASS" if not unknown else "WARNING"),
        ]
    )
    issue_rows = []
    for item in priority_items:
        issue_rows.append(
            "<tr>"
            f"<td>{_esc(item.get('priority'))}</td>"
            f"<td>{_esc(_display_status(item.get('kind')))}</td>"
            f"<td><code>{_esc(item.get('version_key'))}</code></td>"
            f"<td>{_esc(item.get('message'))}</td>"
            f"<td>{_evidence_links({'scan': {'scan_html': item.get('scan_html')}, 'diff': {'adjacent_diff_html': item.get('diff_html')}, 'release': {'release_html': item.get('release_html')}})}</td>"
            "</tr>"
        )
    matrix = faceted_table(
        f"library-{_page_name(lib.get('library_name'))}-versions",
        ["Version", "Stage", "Lineage", "Manual Review", "Scan / Diff / Release", "Source"],
        _version_simple_rows(lib),
        [
            ("stage", "Stage", [(stage, _display_status(stage)) for stage in STAGES]),
            ("scan", "Scan", [("NOT_RUN", "Not run"), ("NOT_SCANNED", "Not scanned"), ("SCANNED", "Scanned"), ("FAILED", "Failed")]),
            ("release", "Release", [("MISSING", "Missing"), ("APPLIED", "Applied"), ("FAILED", "Failed"), ("BLOCKED", "Blocked")]),
        ],
        "暂无版本",
    )
    body = (
        action_bar([("Back to Catalog", "../index.html", "secondary")])
        + "<span class='compat-token'>版本结构 证据 返回 Catalog</span>"
        + panel("Library Header", "单库资产摘要：版本数量、最新版本、阶段构成和证据覆盖。", cards + compact_meta([("Library", lib.get("library_name") or "-"), ("ID", lib.get("library_id") or "-"), ("Catalog", catalog_path)]))
        + panel("Version Table", "一行一个版本。Scan/Diff/Release 只作为证据链接，不在这里复制报告正文。", matrix)
        + collapsible_panel("Attention Queue", "只保留影响 catalog 可信度或阻塞 scan/release 的确认项。", table(["Priority", "Category", "Version", "Issue", "Evidence"], issue_rows, "暂无需要确认的索引问题"), open=bool(issue_rows))
    )
    html_text = page_shell(
        f"{lib.get('library_name')} Library Review",
        "LIBRARY DETAIL",
        f"{lib.get('library_id')} · {len(versions)} versions · {_catalog_stage_mix(lib)}",
        body,
        nav="<a class='active' href='#'>Versions</a><a href='#'>Attention</a><a href='../index.html'>Catalog</a>",
    )
    page.write_text(html_text, encoding="utf-8")
    return str(page)


def render_catalog_html(
    catalog_path: str | Path,
    out_dir: str | Path,
    *,
    render_library_pages: bool = True,
    max_attention_items: int = 100,
    max_report_rows: int = 16,
) -> dict[str, Any]:
    from lib_guard.render.product_theme import action_bar, collapsible_panel, evidence_grid, faceted_table, page_shell, panel, table

    catalog = _read_json(catalog_path, {}) or {}
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    catalog_path_obj = Path(catalog_path)
    base_out = catalog_path_obj.parent
    libraries = list(catalog.get("libraries", []) or [])
    versions = [version for lib in libraries for version in _versions(lib)]
    metrics = _catalog_home_metrics(catalog)

    if render_library_pages:
        for lib in libraries:
            _render_library_page(catalog, lib, out, catalog_path_obj)

    evidence = evidence_grid(
        [
            ("Catalog JSON", "PASS" if catalog_path_obj.exists() else "UNKNOWN", "库、版本关系和 runtime state 主索引。", _file_href(catalog_path_obj)),
            ("Catalog Summary", "PASS" if (base_out / "reports" / "catalog_summary.json").exists() else "UNKNOWN", "规模和状态摘要。", _file_href(base_out / "reports" / "catalog_summary.json")),
            ("Scan Candidates", "PASS" if (base_out / "reports" / "scan_candidates.json").exists() else "UNKNOWN", "待 scan 候选队列。", _file_href(base_out / "reports" / "scan_candidates.json")),
            ("Diff Candidates", "PASS" if (base_out / "reports" / "diff_candidates.json").exists() else "UNKNOWN", "待 diff 候选队列。", _file_href(base_out / "reports" / "diff_candidates.json")),
        ]
    )
    library_table = faceted_table(
        "catalog-library-index",
        ["Library", "Identity", "Discovery", "Latest Version", "Stage Mix", "Versions", "Reports", "Manual Review", "Evidence"],
        _catalog_library_rows(libraries),
        [
            ("type", "Type", [("ip", "IP"), ("ram", "RAM"), ("std", "STD")]),
            ("status", "Review", [("ready", "Clear"), ("manual", "Needs review")]),
            ("unknown", "Unknown", [("yes", "Yes"), ("no", "No")]),
        ],
        "暂无库",
    )
    report_rows = _catalog_report_rows(libraries, max_rows=max_report_rows)
    body = (
        action_bar([("Open catalog.json", _file_href(catalog_path_obj), "secondary")])
        + "<span class='compat-token'>lib_guard 库资产入口 资产入口总览 需要人工确认 库资产索引 高价值报告入口 证据文件</span>"
        + panel("Summary Metrics", "轻量入口页只展示规模、证据覆盖和影响 catalog 可信度的确认数量。", _catalog_metric_cards(metrics))
        + panel("Attention Queue", "只展示 stage unknown、parent/base 不清楚、scan/release 阻塞或失败的项目。", _catalog_attention_table(catalog, max_items=max_attention_items))
        + panel("Library Index", "一库一行。进入单库页查看版本链和证据链接。", library_table)
        + panel("Report Shortcuts", "只保留高价值 report 入口，默认不展开完整历史。", table(["Library", "Version", "Report Type", "Stage", "Link"], report_rows, "暂无报告入口"))
        + collapsible_panel("Evidence Files", "底层 JSON 和候选队列集中放在这里，避免首页铺开 debug 内容。", evidence, open=False)
    )
    html_text = page_shell(
        "Library Catalog Review / 库版本 Review 入口",
        "ASSET CATALOG",
        f"{len(libraries)} libraries · {len(versions)} versions · {metrics.get('manual_confirmation', 0)} attention items",
        body,
        nav="<a class='active' href='#'>Catalog</a><a href='#'>Attention</a><a href='#'>Libraries</a><a href='#'>Evidence</a>",
    )
    (out / "index.html").write_text(html_text, encoding="utf-8")
    return {"status": "PASS", "catalog_path": str(catalog_path), "html_dir": str(out), "index_html": str(out / "index.html")}
