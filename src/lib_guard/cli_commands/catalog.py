"""Catalog and catalog-driven workflow CLI command handlers."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping
import json
import time

from .common import auto_scan_id, default_cache_dir, default_state_dir, print_json, refresh_catalog_html, render_impacted_catalog_html
from .scan import split_strategy_list
from lib_guard.render.impact import impacts_for_versions

RELEASE_CHECK_PASS_STATUSES = {"PASS", "PASS_WITH_WARNING"}


def _read_json(path: str | Path) -> dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def run_catalog_scan(args: Namespace) -> int:
    from lib_guard.catalog.index import render_catalog_html, scan_catalog

    # Default catalog refresh is fast: discover library/version paths without
    # recursing into every version directory. Use --with-evidence only when the
    # catalog page needs file-type hints before real scan reports exist.
    collect_evidence = bool(getattr(args, "with_evidence", False))
    if bool(getattr(args, "fast", False)):
        collect_evidence = False
    result = scan_catalog(
        args.root,
        out_dir=args.out,
        library_type=args.library_type,
        policy_path=args.policy,
        library=args.library,
        force=bool(getattr(args, "full", False)),
        collect_evidence=collect_evidence,
    )
    if args.render:
        html_out = args.html_out or str(Path(args.out) / "html")
        result["html"] = render_catalog_html(
            Path(args.out) / "catalog.json",
            html_out,
            library_filter=getattr(args, "library", None),
            version_filter=getattr(args, "render_version", None),
        )
    print_json({k: v for k, v in result.items() if k != "catalog"})
    return 0 if result.get("status") == "PASS" else 2


def _library_match_names(lib: dict[str, Any]) -> set[str]:
    names = {
        str(lib.get("formal_library_id") or ""),
        str(lib.get("typed_library_id") or ""),
        str(lib.get("library_name") or ""),
        str(lib.get("library_id") or ""),
    }
    names.update(str(a) for a in lib.get("aliases", []) or [] if str(a))
    return {name for name in names if name}


def _latest_version_for_library(catalog_path: str | Path, library: str) -> str:
    data = _read_json(catalog_path)
    for lib in data.get("libraries", []) or []:
        if not isinstance(lib, dict):
            continue
        if library not in _library_match_names(lib):
            continue
        versions = [item for item in lib.get("versions", []) or [] if isinstance(item, dict)]
        summary = lib.get("summary", {}) if isinstance(lib.get("summary"), Mapping) else {}
        latest = summary.get("latest_version") or (versions[-1].get("version_id") if versions else None)
        if latest:
            return str(latest)
        break
    raise ValueError(f"catalog library not found or has no versions: {library}")


def _report_index_path(args: Namespace) -> Path:
    if getattr(args, "html_out", None):
        return Path(args.html_out) / "report_index.json"
    return Path(args.catalog).parent / "html" / "report_index.json"


def _load_report_index(args: Namespace) -> dict[str, Any]:
    path = _report_index_path(args)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _report_library_entry(report_index: Mapping[str, Any], lib: dict[str, Any]) -> dict[str, Any]:
    libraries = report_index.get("libraries", {}) if isinstance(report_index.get("libraries"), dict) else {}
    for key in _library_match_names(lib):
        if key in libraries and isinstance(libraries[key], dict):
            return libraries[key]
    suffixes = {key.rsplit("/", 1)[-1] for key in _library_match_names(lib)}
    for key, value in libraries.items():
        if key in suffixes or str(key).rsplit("/", 1)[-1] in suffixes:
            return value if isinstance(value, dict) else {}
    return {}


def _current_effective_pointer_entry(html_out: str | Path, lib: Mapping[str, Any]) -> dict[str, Any]:
    from lib_guard.effective.pointer import load_current_pointer

    for key in _library_match_names(lib):
        pointer = load_current_pointer(html_out, key)
        if pointer:
            manifest_data: dict[str, Any] = {}
            manifest = pointer.get("manifest")
            if manifest:
                try:
                    loaded = json.loads(Path(str(manifest)).read_text(encoding="utf-8"))
                    if isinstance(loaded, dict):
                        manifest_data = loaded
                except Exception:
                    manifest_data = {}
            summary = pointer.get("summary") if isinstance(pointer.get("summary"), Mapping) else {}
            if not summary and isinstance(manifest_data.get("summary"), Mapping):
                summary = manifest_data.get("summary") or {}
            current_id = str(pointer.get("current_effective_id") or manifest_data.get("effective_id") or "")
            return {
                "current_effective": current_id,
                "effective": {
                    current_id: {
                        "manifest": pointer.get("manifest") or str(manifest or ""),
                        "html": pointer.get("html") or "",
                        "release_preview": pointer.get("release_preview") or "",
                        "summary": dict(summary or {}),
                    }
                }
                if current_id
                else {},
                "source": "current_effective_pointer",
            }
    return {}


def _effective_list_rows(data: dict[str, Any], args: Namespace) -> list[dict[str, Any]]:
    report_index = _load_report_index(args)
    rows: list[dict[str, Any]] = []
    for lib in data.get("libraries", []) or []:
        if args.library and args.library not in _library_match_names(lib):
            continue
        summary = lib.get("summary") or {}
        versions = list(lib.get("versions", []) or [])
        report_lib = _current_effective_pointer_entry(_report_index_path(args).parent, lib) or _report_library_entry(report_index, lib)
        effective = report_lib.get("effective", {}) if isinstance(report_lib.get("effective"), dict) else {}
        current_id = str(report_lib.get("current_effective") or "")
        current = effective.get(current_id, {}) if current_id and isinstance(effective.get(current_id), dict) else {}
        current_summary = current.get("summary", {}) if isinstance(current.get("summary"), dict) else {}
        latest_delivery = summary.get("latest_version") or (versions[-1].get("version_id") if versions else None)
        if not report_lib:
            source = "catalog_only"
            effective_status = "NEEDS_EFFECTIVE_CONFIRM"
        elif effective:
            source = str(report_lib.get("source") or "report_index")
            effective_status = "CURRENT_EFFECTIVE_READY" if current_id and current else "HAS_EFFECTIVE_NO_CURRENT"
        else:
            source = "report_index_no_effective"
            effective_status = "NEEDS_EFFECTIVE_CONFIRM"
        rows.append(
            {
                "库名": lib.get("formal_library_id") or lib.get("library_name"),
                "交付版本数": summary.get("version_count", len(versions)),
                "最新交付版本": latest_delivery,
                "当前Effective": current_id or None,
                "有效状态": effective_status,
                "Effective数": len(effective),
                "Effective文件数": current_summary.get("file_count"),
                "Effective组件数": current_summary.get("component_count"),
                "Manifest": current.get("manifest"),
                "ReleasePreview": current.get("release_preview"),
                "来源": source,
            }
        )
    return rows


def run_catalog_list(args: Namespace) -> int:
    data = json.loads(Path(args.catalog).read_text(encoding="utf-8"))
    if getattr(args, "plain", False) and not getattr(args, "effective", False):
        names: list[str] = []
        for lib in data.get("libraries", []) or []:
            if args.library and args.library not in _library_match_names(lib):
                continue
            if args.versions:
                names.extend(str(version.get("version_id") or "") for version in lib.get("versions", []) or [])
            else:
                names.append(str(lib.get("formal_library_id") or lib.get("library_name") or ""))
        print("\n".join(name for name in names if name))
        return 0
    if getattr(args, "effective", False):
        print_json({"status": "PASS", "rows": _effective_list_rows(data, args), "report_index": str(_report_index_path(args))})
        return 0
    rows = []
    for lib in data.get("libraries", []) or []:
        if args.library and args.library not in _library_match_names(lib):
            continue
        if args.versions:
            for version in lib.get("versions", []) or []:
                diff = version.get("diff", {}) or {}
                lineage = version.get("lineage", {}) or {}
                previous_effective = version.get("previous_effective_version")
                if not previous_effective and str(lineage.get("source") or "").lower() == "manual":
                    previous_effective = lineage.get("parent_candidate")
                diff_source = diff.get("base_source") or diff.get("base_version_source")
                diff_base = diff.get("base_version")
                if not diff_base and diff_source in {"previous_effective", "current_effective", "explicit"}:
                    diff_base = diff.get("previous_effective_version") or diff.get("current_effective_ref")
                rows.append(
                    {
                        "库名": lib.get("formal_library_id") or lib.get("library_name"),
                        "版本名": version.get("version_id"),
                        "阶段": version.get("stage"),
                        "上一有效版": previous_effective,
                        "相邻上一版": diff.get("adjacent_old_version"),
                        "当前有效引用": version.get("current_effective_ref") or version.get("latest_effective_ref"),
                        "已运行Diff来源": diff_source,
                        "已运行Diff基准": diff_base,
                        "原始路径": version.get("raw_path"),
                        "需确认": version.get("manual_review"),
                        "建议动作": version.get("recommended_action"),
                    }
                )
        else:
            summary = lib.get("summary") or {}
            rows.append(
                {
                    "库名": lib.get("formal_library_id") or lib.get("library_name"),
                    "显示名": lib.get("display_name"),
                    "版本数": summary.get("version_count"),
                    "最新版本": summary.get("latest_version"),
                    "待扫描": summary.get("scan_pending"),
                    "待对比": summary.get("diff_pending"),
                    "需确认": summary.get("manual_review"),
                }
            )
    print_json({"status": "PASS", "rows": rows})
    return 0


def run_catalog_render(args: Namespace) -> int:
    library_filter = getattr(args, "library", None)
    version_filter = getattr(args, "version", None)
    if library_filter:
        from lib_guard.render.version_detail_fast import render_version_detail_only

        version = str(version_filter or _latest_version_for_library(args.catalog, str(library_filter)))
        page = render_version_detail_only(
            catalog_path=args.catalog,
            out_dir=args.out,
            library=str(library_filter),
            version=version,
        )
        result = {
            "status": page.get("status", "PASS"),
            "mode": "version_detail_direct",
            "rendered_libraries": 0,
            "rendered_versions": 1 if page.get("status") == "PASS" else 0,
            "version_detail_pages": [page],
            "open_first": page.get("version_detail_html"),
            "library_filter": library_filter,
            "version_filter": version,
            "note": "带 library/version 过滤的 catalog render 只刷新 Version Detail，不覆盖 catalog/index 导航页。",
        }
        print_json(result)
        return 0 if result.get("status") == "PASS" else 2

    from lib_guard.catalog.index import render_catalog_html
    result = render_catalog_html(
        args.catalog,
        args.out,
    )
    print_json(result)
    return 0 if result.get("status") == "PASS" else 2


def _attach_render_output(output: dict[str, Any], render_impact: dict[str, Any]) -> None:
    output["render_impact"] = render_impact
    output["rendered_pages"] = render_impact.get("affected_pages", [])
    output["catalog_html_out"] = render_impact.get("catalog_html_out")
    render_result = render_impact.get("render_result")
    if render_result:
        output["catalog_html"] = render_result
    output["render_summary"] = _render_summary(render_impact)


def _render_summary(render_impact: Mapping[str, Any]) -> dict[str, Any]:
    render_result = render_impact.get("render_result") if isinstance(render_impact.get("render_result"), Mapping) else {}
    affected_versions = [
        {"library": item.get("library"), "version": item.get("version")}
        for item in (render_impact.get("affected_pages") or [])
        if isinstance(item, Mapping) and item.get("kind") == "version_detail"
    ]
    status = str(render_result.get("status") or "UNKNOWN")
    skipped_reason = render_result.get("reason") if status == "SKIPPED" else None
    rendered_versions = int(render_result.get("rendered_versions", 0) or 0)
    version_detail_htmls = [
        str(item.get("version_detail_html"))
        for item in (render_result.get("version_detail_pages") or [])
        if isinstance(item, Mapping) and item.get("version_detail_html")
    ]
    deferred_pages = render_result.get("deferred_pages") or []
    deferred_file = render_result.get("deferred_file") or None
    failed_versions = render_result.get("failed_versions") or []
    if status == "SKIPPED":
        message = f"版本详情未刷新：{skipped_reason or 'unknown'}"
    elif status not in {"PASS", "UNKNOWN"}:
        message = f"版本详情刷新失败：{len(failed_versions) or 'unknown'} 个版本失败"
    elif rendered_versions and deferred_pages:
        message = f"版本详情已刷新 {rendered_versions} 个版本；Catalog 导航页延迟刷新"
    elif rendered_versions:
        message = f"版本详情已刷新 {rendered_versions} 个版本；Catalog 首页已更新"
    else:
        message = "Catalog 首页已更新；没有版本详情页需要刷新"
    return {
        "status": status,
        "message": message,
        "catalog_html_out": render_impact.get("catalog_html_out"),
        "index_html": render_result.get("index_html"),
        "open_first": version_detail_htmls[0] if version_detail_htmls else render_result.get("index_html"),
        "version_detail_htmls": version_detail_htmls,
        "rendered_libraries": int(render_result.get("rendered_libraries", 0) or 0),
        "rendered_versions": rendered_versions,
        "skipped_reason": skipped_reason,
        "deferred_pages": deferred_pages,
        "deferred_file": deferred_file,
        "failed_versions": failed_versions,
        "affected_versions": affected_versions,
    }


def _version_ref_from_catalog_key(catalog: Mapping[str, Any], version_key: str) -> tuple[str, str] | None:
    for lib in catalog.get("libraries", []) or []:
        if not isinstance(lib, Mapping):
            continue
        for version in lib.get("versions", []) or []:
            if not isinstance(version, Mapping):
                continue
            if str(version.get("version_key") or "") == str(version_key):
                return str(lib.get("library_name") or lib.get("formal_library_id") or lib.get("library_id") or ""), str(version.get("version_id") or "")
    return None


def run_catalog_override(args: Namespace) -> int:
    from lib_guard.catalog.index import apply_catalog_override

    result = apply_catalog_override(
        args.catalog,
        version_key=args.version,
        stage=args.stage,
        parent_version=args.parent,
        base_version=args.base,
        release_line=args.release_line,
        display_name=args.display_name,
        package_type=getattr(args, "package_type", None),
        update_scope=getattr(args, "update_scope", None),
        standalone=getattr(args, "standalone", None),
        base_required=getattr(args, "base_required", None),
        base_full_version=getattr(args, "base_full_version", None),
        previous_effective_version=getattr(args, "previous_effective_version", None),
        compare_default=getattr(args, "compare_default", None),
        current_effective=getattr(args, "current_effective", None),
        manual_review=args.manual_review,
        note=args.note,
        updated_by=args.updated_by,
    )
    output = {k: v for k, v in result.items() if k != "catalog"}
    version_ref = _version_ref_from_catalog_key(result.get("catalog", {}) if isinstance(result.get("catalog"), Mapping) else {}, args.version)
    impacts = impacts_for_versions(version_ref[0], [version_ref[1]], "catalog_override_updated") if version_ref else []
    render_impact = render_impacted_catalog_html(args, impacts)
    _attach_render_output(output, render_impact)
    if version_ref and any(
        getattr(args, name, None)
        for name in ["package_type", "base", "base_full_version", "previous_effective_version", "current_effective", "compare_default"]
    ):
        output["recommended_next"] = f"lg next {version_ref[0]} --apply --rebuild"
    print_json(output)
    return 0 if result.get("status") == "PASS" else 2


def run_catalog_workflow(args: Namespace) -> int:
    from lib_guard.catalog.index import find_catalog_version, update_catalog_scan_status
    from lib_guard.render.html_report import render_scan_html
    from lib_guard.scan.scanner import ScanRunner

    phase_timings: list[dict[str, Any]] = []

    def start_phase() -> float:
        return time.perf_counter()

    def finish_phase(phase: str, started: float) -> None:
        phase_timings.append({"phase": phase, "elapsed_seconds": round(max(0.0, time.perf_counter() - started), 3)})

    started = start_phase()
    item = find_catalog_version(args.catalog, args.library, args.version)
    finish_phase("resolve_catalog_version", started)
    scan_id = args.scan_id or auto_scan_id()
    out_dir = args.out or str(Path(args.workdir) / "scan_out" / item["library_name"] / item["version_id"] / f"{args.mode}_{scan_id}")
    cfg = SimpleNamespace(
        root_path=item["raw_path"],
        root=item["raw_path"],
        library_type=item["library_type"],
        profile=item["library_type"],
        library_name=item["library_name"],
        name=item["library_name"],
        version=item["version_id"],
        release_version=item["version_id"],
        scan_mode=args.mode,
        mode=args.mode,
        scan_id=scan_id,
        out_dir=out_dir,
        out=out_dir,
        workdir=args.workdir,
        state_dir=args.state_dir or default_state_dir(args.workdir, item["library_type"], item["library_name"], item["version_id"]),
        cache_dir=args.cache_dir or default_cache_dir(args.workdir),
        config=args.config,
        no_progress=args.no_progress,
        console_progress=args.console_progress,
        progress_interval=args.progress_interval,
        parse_jobs=args.parse_jobs,
        skip_cache=args.skip_cache,
        no_cache=args.no_cache,
        hash_policy=getattr(args, "hash_policy", None),
        parse_file_types=split_strategy_list(getattr(args, "parse_file_types", None)),
        parse_exclude_file_types=split_strategy_list(getattr(args, "parse_exclude_file_types", None)),
        tool_version="0.5.0",
        schema_version="1.0",
        package_type=item.get("package_type"),
        update_scope=item.get("update_scope"),
        standalone=item.get("standalone"),
        base_required=item.get("base_required"),
        base_version=item.get("base_version") or (item.get("lineage", {}) or {}).get("base_candidate"),
    )
    started = start_phase()
    scan_result = ScanRunner(cfg).run()
    finish_phase("scan_runner", started)
    started = start_phase()
    scan_html = render_scan_html(scan_result.out_dir, args.html_out or str(Path(args.workdir) / "reports" / item["library_name"] / item["version_id"] / "scan_html"))
    finish_phase("render_scan_html", started)
    started = start_phase()
    update_catalog_scan_status(
        args.catalog,
        version_key=item["version_key"],
        scan_dir=scan_result.out_dir,
        scan_id=scan_result.scan_id,
        status=scan_result.status,
        scan_html=scan_html.get("index_html"),
        input_fingerprint=(scan_result.bundle.scan_meta.get("input_fingerprint") if getattr(scan_result, "bundle", None) else None),
        snapshot_identity=(scan_result.bundle.scan_meta.get("snapshot_identity") if getattr(scan_result, "bundle", None) else None),
    )
    finish_phase("update_catalog_scan_status", started)
    result = {
        "status": scan_result.status,
        "catalog": args.catalog,
        "library": item["library_name"],
        "version": item["version_id"],
        "scan_dir": scan_result.out_dir,
        "scan_html": scan_html,
    }
    scan_error = (scan_result.bundle.scan_meta or {}).get("error") if getattr(scan_result, "bundle", None) else None
    if scan_error:
        result["scan_error"] = scan_error
    started = start_phase()
    render_impact = render_impacted_catalog_html(args, impacts_for_versions(item["library_name"], [item["version_id"]], "scan_updated"))
    finish_phase("render_impacted_catalog_html", started)
    result["phase_timings"] = phase_timings
    _attach_render_output(result, render_impact)
    print_json(result)
    return 0 if scan_result.status not in {"FAILED", "BLOCK"} else 2


def _compare_scan_child(args: Namespace, library: str, version: str) -> Namespace:
    """Build a run_catalog_workflow Namespace for compare pre-scan.

    Compare mode (adjacent/cumulative) is not a scan mode, so this helper uses
    args.scan_mode for the scan workflow. Defaults match the normal run parser.
    """

    return Namespace(
        catalog=args.catalog,
        library=library,
        version=version,
        mode=getattr(args, "scan_mode", "scan"),
        workdir=getattr(args, "workdir", "work"),
        out=None,
        html_out=None,
        catalog_html_out=getattr(args, "catalog_html_out", None),
        no_catalog_render=True,
        config_dir=getattr(args, "config_dir", "configs"),
        state_dir=getattr(args, "state_dir", None),
        cache_dir=getattr(args, "cache_dir", None),
        config=getattr(args, "config", None),
        scan_id=None,
        progress_interval=getattr(args, "progress_interval", 50),
        no_progress=getattr(args, "no_progress", False),
        console_progress=getattr(args, "console_progress", None),
        parse_jobs=getattr(args, "parse_jobs", 8),
        skip_cache=getattr(args, "skip_cache", False),
        no_cache=getattr(args, "no_cache", False),
        hash_policy=getattr(args, "hash_policy", None),
        parse_file_types=getattr(args, "parse_file_types", None),
        parse_exclude_file_types=getattr(args, "parse_exclude_file_types", None),
    )


def _resolve_compare_items(catalog_path: str | Path, library: str, new_version: str, *, mode: str, base: str | None) -> tuple[dict[str, Any], dict[str, Any], str]:
    from lib_guard.catalog.index import find_catalog_version

    new_item = find_catalog_version(catalog_path, library, new_version)
    diff = new_item.get("diff", {}) or {}
    if base:
        old_version = base
        relation_mode = "base"
    elif mode == "cumulative":
        old_version = diff.get("cumulative_base_version")
        relation_mode = "cumulative"
    else:
        old_version = diff.get("adjacent_old_version")
        relation_mode = "adjacent"
    if not old_version:
        raise ValueError(f"catalog version {new_item.get('version_key')} has no {mode} comparison target; pass --base")
    old_item = find_catalog_version(catalog_path, library, str(old_version))
    return old_item, new_item, relation_mode


def _has_scan_dir(item: dict[str, Any]) -> bool:
    return bool((item.get("scan", {}) or {}).get("scan_dir"))


def _scan_needs_refresh(item: dict[str, Any]) -> bool:
    scan = item.get("scan", {}) or {}
    return scan.get("status") in {"NOT_SCANNED", "STALE_SCAN"} or not scan.get("scan_dir")


def _ensure_compare_scan_evidence(args: Namespace) -> dict[str, Any]:
    """Optionally scan old/new versions for compare.

    Default compare is read-only: it does not scan. --scan-if-missing scans only
    versions whose catalog scan_dir is missing. --rescan intentionally rebuilds
    both sides.
    """

    scan_if_missing = bool(getattr(args, "scan_if_missing", False))
    rescan = bool(getattr(args, "rescan", False))
    if scan_if_missing and rescan:
        raise ValueError("Use only one of --scan-if-missing or --rescan")

    old_item, new_item, _relation_mode = _resolve_compare_items(args.catalog, args.library, args.new, mode=args.mode, base=getattr(args, "base", None))
    plan = []
    if rescan or (scan_if_missing and _scan_needs_refresh(old_item)):
        plan.append(old_item)
    if rescan or (scan_if_missing and _scan_needs_refresh(new_item)):
        # Avoid double scan if old and new are the same by mistake.
        if new_item.get("version_key") not in {item.get("version_key") for item in plan}:
            plan.append(new_item)

    if not scan_if_missing and not rescan:
        missing = [item.get("version_id") for item in [old_item, new_item] if _scan_needs_refresh(item)]
        if missing:
            raise ValueError(
                "compare requires existing scan evidence for old/new versions. "
                f"Missing or stale scan evidence for: {', '.join(str(x) for x in missing)}. "
                "Run scan explicitly or use --scan-if-missing."
            )

    results = []
    for item in plan:
        child = _compare_scan_child(args, str(item["library_name"]), str(item["version_id"]))
        code = run_catalog_workflow(child)
        results.append({"version": item.get("version_id"), "exit_code": code})
        if code != 0:
            raise RuntimeError(f"pre-compare scan failed for {item.get('version_id')}: exit_code={code}")
    return {
        "mode": "rescan" if rescan else "scan_if_missing" if scan_if_missing else "read_existing",
        "requested": len(plan),
        "scanned_versions": [item.get("version_id") for item in plan],
        "results": results,
    }


def run_catalog_compare(args: Namespace) -> int:
    from lib_guard.catalog.index import resolve_catalog_pair, update_catalog_diff_status
    from lib_guard.diff.scan_diff import diff_scan_outputs
    from lib_guard.render.html_report import render_diff_html

    scan_precheck = _ensure_compare_scan_evidence(args)
    explicit_base = getattr(args, "base", None)
    pair = resolve_catalog_pair(args.catalog, args.library, args.new, mode=args.mode, base=explicit_base)
    requested_base_source = getattr(args, "base_source", None)
    if explicit_base and requested_base_source:
        pair["version_relation"]["base_version_source"] = requested_base_source
    new = pair["new"]
    old = pair["old"]
    relation_mode = pair["version_relation"].get("mode") or args.mode
    diff_leaf = f"base_{old['version_id']}" if explicit_base else args.mode
    diff_dir = args.out or str(Path(args.workdir) / "diff" / new["library_name"] / new["version_id"] / diff_leaf)
    diff_result = diff_scan_outputs(pair["old_scan"], pair["new_scan"], out_path=diff_dir, version_relation=pair["version_relation"])
    html_out = args.html_out or str(Path(diff_dir) / "diff_html")
    html_result = render_diff_html(diff_dir, html_out)
    update_catalog_diff_status(
        args.catalog,
        version_key=new["version_key"],
        mode=relation_mode,
        old_version=old["version_id"],
        diff_dir=diff_dir,
        status=diff_result.get("status", "DIFF"),
        diff_html=html_result.get("index_html"),
        base_source=requested_base_source or ("explicit" if explicit_base else None),
    )
    result = {
        "status": diff_result.get("status"),
        "catalog": args.catalog,
        "library": new["library_name"],
        "old_version": old["version_id"],
        "new_version": new["version_id"],
        "compare_policy": relation_mode,
        "base_version_source": pair["version_relation"].get("base_version_source"),
        "scan_precheck": scan_precheck,
        "diff_dir": str(diff_dir),
        "diff_html": html_result,
    }
    impacted_versions = [str(new["version_id"])]
    for item in scan_precheck.get("scanned_versions", []) or []:
        version_id = str(item or "")
        if version_id and version_id not in impacted_versions:
            impacted_versions.append(version_id)
    render_impact = render_impacted_catalog_html(args, impacts_for_versions(new["library_name"], impacted_versions, "compare_updated"))
    _attach_render_output(result, render_impact)
    print_json(result)
    return 0 if diff_result.get("status") in {"SAME", "DIFF", "PASS_WITH_WARNING", "BLOCK"} else 2


def _catalog_versions(catalog_path: str | Path, library: str | None = None) -> list[dict[str, Any]]:
    data = json.loads(Path(catalog_path).read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    for lib in data.get("libraries", []) or []:
        if library and library not in _library_match_names(lib):
            continue
        for version in lib.get("versions", []) or []:
            item = dict(version)
            item["library_name"] = lib.get("library_name")
            item["library_type"] = lib.get("library_type")
            item["library_id"] = lib.get("library_id")
            item["aliases"] = list(lib.get("aliases", []) or [])
            item["vendor"] = lib.get("vendor")
            item["category"] = lib.get("category")
            item["library_root"] = item.get("library_root") or lib.get("library_root")
            rows.append(item)
    return rows


def _default_catalog_html_out(catalog_path: str | Path) -> Path:
    catalog = Path(catalog_path)
    if catalog.parent.name == "catalog":
        return catalog.parent / "html"
    return catalog.parent / "html"


def _review_gate_for_catalog_version(args: Namespace) -> tuple[str | None, dict[str, Any]]:
    from lib_guard.review.io import read_json, write_json
    from lib_guard.review.state import build_review_state

    explicit = getattr(args, "review_gate", None)
    if explicit:
        return str(explicit), read_json(explicit, {}) or {}
    catalog = json.loads(Path(args.catalog).read_text(encoding="utf-8"))
    out_dir = _default_catalog_html_out(args.catalog)
    state = build_review_state(catalog, out_dir=out_dir)
    for lib in state.get("libraries", []) or []:
        if args.library not in _library_match_names(lib):
            continue
        for version in lib.get("versions", []) or []:
            if version.get("version_id") == args.version or version.get("version_key") == args.version:
                gate = dict(version.get("review_gate") or {})
                gate_file = gate.get("gate_file")
                if gate_file:
                    write_json(gate_file, gate)
                    return str(gate_file), gate
                return None, gate
    return None, {}


def _batch_run_dir(args: Namespace, batch_type: str) -> tuple[Path, str]:
    from lib_guard.batch.manifest import make_batch_run_dir

    run_id = getattr(args, "batch_run_id", None) or f"{batch_type}_{auto_scan_id()}"
    if getattr(args, "batch_out", None):
        run_dir = Path(args.batch_out)
        run_dir.mkdir(parents=True, exist_ok=True)
    else:
        run_dir = make_batch_run_dir(getattr(args, "workdir", "work"), batch_type, run_id=run_id)
    return run_dir, run_id


def _batch_manifest_item(item: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "library_name": item.get("library_name"),
        "library_id": item.get("library_id"),
        "version_id": item.get("version_id"),
        "version_key": item.get("version_key"),
        "stage": item.get("stage"),
        "reason": reason,
    }


def run_catalog_batch(args: Namespace) -> int:
    from lib_guard.batch.manifest import init_progress, update_progress, write_failed, write_rerun_failed_csh, write_result, write_selection_manifest

    run_dir, run_id = _batch_run_dir(args, "scan")
    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    selected = []
    skipped: list[dict[str, Any]] = []
    for item in _catalog_versions(args.catalog, args.library):
        if args.stage and item.get("stage") != args.stage:
            skipped.append(_batch_manifest_item(item, "stage_filter_mismatch"))
            continue
        if args.only_missing and not _scan_needs_refresh(item):
            skipped.append(_batch_manifest_item(item, "scan_evidence_current"))
            continue
        selected.append(item)
        if args.limit and len(selected) >= args.limit:
            break
    selection_manifest = write_selection_manifest(
        run_dir,
        {
            "run_id": run_id,
            "batch_type": "scan",
            "catalog": str(Path(args.catalog)),
            "library_filter": args.library,
            "stage_filter": args.stage,
            "only_missing": bool(args.only_missing),
            "only_ready": False,
            "limit": args.limit,
            "selected": [_batch_manifest_item(item, "scan.status in {NOT_SCANNED,STALE_SCAN}" if args.only_missing else "selected") for item in selected],
            "skipped": skipped,
        },
    )
    if getattr(args, "plan_only", False):
        result = {
            "status": "PLAN_ONLY",
            "run_id": run_id,
            "selected": len(selected),
            "skipped": len(skipped),
            "selection_manifest": str(selection_manifest),
        }
        write_result(run_dir, result)
        print_json(result)
        return 0
    init_progress(run_dir, len(selected), run_id)
    completed_by_library: dict[str, list[str]] = {}
    for item in selected:
        child = Namespace(**vars(args))
        child.library = item["library_name"]
        child.version = item["version_id"]
        child.out = None
        child.html_out = None
        child.no_catalog_render = True
        try:
            started_at = auto_scan_id()
            code = run_catalog_workflow(child)
            row = {**_batch_manifest_item(item, "executed"), "status": "PASS" if code == 0 else "FAILED", "exit_code": code, "started_at": started_at, "finished_at": auto_scan_id()}
            results.append(row)
            update_progress(run_dir, row)
            if code == 0:
                completed_by_library.setdefault(str(item.get("library_name") or ""), []).append(str(item.get("version_id") or ""))
            if code != 0:
                failures.append(row)
        except Exception as exc:
            row = {**_batch_manifest_item(item, "executed"), "status": "FAILED", "exit_code": 2, "error": str(exc), "finished_at": auto_scan_id()}
            failures.append(row)
            update_progress(run_dir, row)
    impacts = []
    for library_name, versions in completed_by_library.items():
        impacts.extend(impacts_for_versions(library_name, versions, "batch_scan_updated"))
    render_impact = render_impacted_catalog_html(args, impacts)
    output = {
        "status": "PASS" if not failures else "FAILED",
        "run_id": run_id,
        "run_dir": str(run_dir),
        "selection_manifest": str(selection_manifest),
        "selected": len(selected),
        "skipped_existing": sum(1 for item in skipped if item.get("reason") in {"already_scanned", "scan_evidence_current"}),
        "skipped_stage": sum(1 for item in skipped if item.get("reason") == "stage_filter_mismatch"),
        "selected_versions": [item.get("version_id") for item in selected],
        "results": results,
        "failures": failures,
    }
    _attach_render_output(output, render_impact)
    write_failed(run_dir, failures)
    write_rerun_failed_csh(run_dir, failures, "scan")
    write_result(run_dir, output)
    print_json(output)
    return 0 if not failures else 2


def run_catalog_compare_batch(args: Namespace) -> int:
    from lib_guard.batch.manifest import init_progress, update_progress, write_failed, write_rerun_failed_csh, write_result, write_selection_manifest

    run_dir, run_id = _batch_run_dir(args, "compare")
    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    selected = []
    skipped: list[dict[str, Any]] = []
    for item in _catalog_versions(args.catalog, args.library):
        if args.stage and item.get("stage") != args.stage:
            skipped.append(_batch_manifest_item(item, "stage_filter_mismatch"))
            continue
        diff = item.get("diff", {}) or {}
        scan = item.get("scan", {}) or {}
        old_version = diff.get("cumulative_base_version") if args.mode == "cumulative" else diff.get("adjacent_old_version")
        if args.only_ready:
            if not scan.get("scan_dir") or not old_version:
                skipped.append(_batch_manifest_item(item, "missing_new_scan_or_compare_target"))
                continue
            old = next((v for v in _catalog_versions(args.catalog, item["library_name"]) if v.get("version_id") == old_version), None)
            if not old or not old.get("scan", {}).get("scan_dir"):
                skipped.append(_batch_manifest_item(item, "missing_old_scan_evidence"))
                continue
        status_key = "cumulative_status" if args.mode == "cumulative" else "adjacent_status"
        if args.only_pending and diff.get(status_key) != "PENDING":
            skipped.append(_batch_manifest_item(item, "diff_not_pending"))
            continue
        selected.append(item)
        if args.limit and len(selected) >= args.limit:
            break
    selection_manifest = write_selection_manifest(
        run_dir,
        {
            "run_id": run_id,
            "batch_type": "compare",
            "catalog": str(Path(args.catalog)),
            "library_filter": args.library,
            "stage_filter": args.stage,
            "only_missing": False,
            "only_ready": bool(args.only_ready),
            "only_pending": bool(args.only_pending),
            "limit": args.limit,
            "selected": [_batch_manifest_item(item, "compare_selected") for item in selected],
            "skipped": skipped,
        },
    )
    if getattr(args, "plan_only", False):
        result = {
            "status": "PLAN_ONLY",
            "run_id": run_id,
            "selected": len(selected),
            "skipped": len(skipped),
            "selection_manifest": str(selection_manifest),
        }
        write_result(run_dir, result)
        print_json(result)
        return 0
    init_progress(run_dir, len(selected), run_id)
    completed_by_library: dict[str, list[str]] = {}
    for item in selected:
        child = Namespace(**vars(args))
        child.library = item["library_name"]
        child.new = item["version_id"]
        child.base = None
        child.out = None
        child.html_out = None
        child.no_catalog_render = True
        try:
            started_at = auto_scan_id()
            code = run_catalog_compare(child)
            row = {**_batch_manifest_item(item, "executed"), "status": "PASS" if code == 0 else "FAILED", "exit_code": code, "started_at": started_at, "finished_at": auto_scan_id()}
            results.append(row)
            update_progress(run_dir, row)
            if code == 0:
                completed_by_library.setdefault(str(item.get("library_name") or ""), []).append(str(item.get("version_id") or ""))
            if code != 0:
                failures.append(row)
        except Exception as exc:
            row = {**_batch_manifest_item(item, "executed"), "status": "FAILED", "exit_code": 2, "error": str(exc), "finished_at": auto_scan_id()}
            failures.append(row)
            update_progress(run_dir, row)
    impacts = []
    for library_name, versions in completed_by_library.items():
        impacts.extend(impacts_for_versions(library_name, versions, "batch_compare_updated"))
    render_impact = render_impacted_catalog_html(args, impacts)
    output = {
        "status": "PASS" if not failures else "FAILED",
        "run_id": run_id,
        "run_dir": str(run_dir),
        "selection_manifest": str(selection_manifest),
        "selected": len(selected),
        "skipped_existing": sum(1 for item in skipped if item.get("reason") == "diff_not_pending"),
        "skipped_stage": sum(1 for item in skipped if item.get("reason") == "stage_filter_mismatch"),
        "skipped_not_ready": sum(1 for item in skipped if item.get("reason") in {"missing_new_scan_or_compare_target", "missing_old_scan_evidence"}),
        "selected_versions": [item.get("version_id") for item in selected],
        "results": results,
        "failures": failures,
    }
    _attach_render_output(output, render_impact)
    write_failed(run_dir, failures)
    write_rerun_failed_csh(run_dir, failures, "compare")
    write_result(run_dir, output)
    print_json(output)
    return 0 if not failures else 2


def run_catalog_release_check(args: Namespace) -> int:
    from lib_guard.catalog.index import find_catalog_version, update_catalog_release_status
    from lib_guard.release.explain import explain_release_check
    from lib_guard.release.checker import check_release_scan
    from lib_guard.release.result import release_result_from_check, write_release_result

    item = find_catalog_version(args.catalog, args.library, args.version)
    scan_dir = item.get("scan", {}).get("scan_dir")
    if not scan_dir:
        raise ValueError(f"catalog version {item['version_key']} has no scan_dir; run it first")
    diff_dir = getattr(args, "diff", None)
    if not diff_dir and args.diff_mode:
        diff = item.get("diff", {}) or {}
        diff_dir = diff.get("cumulative_diff_dir") if args.diff_mode == "cumulative" else diff.get("adjacent_diff_dir")
    review_gate_path, review_gate = _review_gate_for_catalog_version(args)
    result = check_release_scan(
        scan_dir,
        policy_path=args.policy,
        diff_dir=diff_dir,
        alias=getattr(args, "alias", None),
        review_gate_path=review_gate_path,
        review_gate=review_gate if not review_gate_path else None,
    )
    if getattr(args, "explain", False):
        print_json(explain_release_check(result))
        return 0
    result_path = Path(scan_dir) / "release" / "release_check.json"
    release_result_path = Path(scan_dir) / "release" / "release_result.json"
    write_release_result(release_result_path, release_result_from_check(result))
    update_catalog_release_status(args.catalog, version_key=item["version_key"], action="check", status=result.get("release_check_status", "UNKNOWN"), result_path=result_path)
    print_json(result)
    return 0 if str(result.get("release_check_status") or "") in RELEASE_CHECK_PASS_STATUSES else 2


def run_catalog_release_link(args: Namespace) -> int:
    from lib_guard.catalog.index import find_catalog_version, update_catalog_release_status
    from lib_guard.release.bundle import create_manifest_template_from_catalog
    from lib_guard.release.linker import link_release_from_manifest
    from lib_guard.release.result import release_result_from_link, write_release_result

    item = find_catalog_version(args.catalog, args.library, args.version)
    scan_dir = item.get("scan", {}).get("scan_dir")
    if not scan_dir:
        raise ValueError(f"catalog version {item['version_key']} has no scan_dir; run it first")
    manifest_path = Path(scan_dir) / "release" / "release_manifest.json"
    create_manifest_template_from_catalog(
        args.catalog,
        manifest_path,
        release_root=args.release_root,
        alias=args.alias,
        versions=[item["version_key"]],
    )
    result = link_release_from_manifest(
        manifest_path,
        apply=bool(args.apply),
        mode=getattr(args, "link_mode", None) or "symlink",
        overwrite=getattr(args, "overwrite", False),
        force=bool(getattr(args, "force", False)),
        force_reason=getattr(args, "force_reason", None),
        force_by=getattr(args, "force_by", None),
    )
    result_path = Path(scan_dir) / "release" / "release_link_result.json"
    release_result_path = result_path.parent / "release_result.json"
    write_release_result(release_result_path, release_result_from_link(result))
    update_catalog_release_status(
        args.catalog,
        version_key=item["version_key"],
        action="link",
        status=result.get("status", "UNKNOWN"),
        result_path=result_path,
        release_dir=result.get("release_dir"),
        alias=args.alias,
        manifest_path=manifest_path,
    )
    print_json(result)
    return 0 if result.get("status") not in {"FAILED", "BLOCKED"} else 2


def run_catalog_release_batch(args: Namespace) -> int:
    from lib_guard.catalog.index import update_catalog_release_status
    from lib_guard.release.bundle import create_manifest_from_effective_manifest, create_manifest_template_from_catalog
    from lib_guard.release.linker import link_release_from_manifest
    from lib_guard.release.postcheck import verify_release_manifest
    from lib_guard.release.result import release_result_from_link, write_release_result

    catalog_path = Path(args.catalog)
    release_id = getattr(args, "release_id", None) or f"{str(args.alias).upper()}_{auto_scan_id()}"
    if getattr(args, "out", None):
        run_dir = Path(args.out)
    elif catalog_path.parent.name == "catalog":
        run_dir = catalog_path.parent.parent / "release_runs" / release_id
    else:
        run_dir = catalog_path.parent / "release_runs" / release_id
    manifest_path = run_dir / "release_manifest.json"
    effective_manifest = getattr(args, "effective_manifest", None)
    selected: list[dict[str, Any]] = []
    if effective_manifest:
        manifest = create_manifest_from_effective_manifest(
            effective_manifest,
            manifest_path,
            release_root=args.release_root,
            alias=args.alias,
            release_id=release_id,
        )
    else:
        requested_versions = set(args.version or [])
        for item in _catalog_versions(args.catalog, args.library):
            if requested_versions and item.get("version_id") not in requested_versions and item.get("version_key") not in requested_versions:
                continue
            if args.stage and item.get("stage") != args.stage:
                continue
            if not item.get("scan", {}).get("scan_dir"):
                continue
            release = item.get("release", {}) or {}
            check_status = str(release.get("check_status") or "")
            if not getattr(args, "force", False) and check_status not in RELEASE_CHECK_PASS_STATUSES:
                continue
            if args.only_checked and check_status not in RELEASE_CHECK_PASS_STATUSES:
                continue
            if args.only_ready:
                if item.get("manual_review") or check_status in {"BLOCK", "FAILED"}:
                    continue
            selected.append(item)
            if args.limit and len(selected) >= args.limit:
                break
        if not requested_versions:
            latest_by_library: dict[str, dict[str, Any]] = {}
            for item in selected:
                latest_by_library[str(item.get("library_id") or item.get("library_name"))] = item
            selected = list(latest_by_library.values())
        if not selected:
            output = {"status": "FAILED", "selected": 0, "message": "no scanned catalog versions selected for release"}
            print_json(output)
            return 2
        selected_keys = [str(item["version_key"]) for item in selected]
        manifest = create_manifest_template_from_catalog(
            args.catalog,
            manifest_path,
            release_root=args.release_root,
            alias=args.alias,
            release_id=release_id,
            library=args.library,
            versions=selected_keys,
        )
    link_result = link_release_from_manifest(
        manifest_path,
        apply=bool(args.apply),
        mode=getattr(args, "link_mode", None) or "symlink",
        overwrite=bool(args.overwrite),
        force=bool(getattr(args, "force", False)),
        force_reason=getattr(args, "force_reason", None),
        force_by=getattr(args, "force_by", None),
        verify_skipped=bool(getattr(args, "no_verify", False)),
        verify_skip_reason="no_verify requested" if getattr(args, "no_verify", False) else "",
    )
    verify_result = None
    if bool(args.apply) and not getattr(args, "no_verify", False):
        verify_result = verify_release_manifest(manifest_path, render=not getattr(args, "no_render", False))
    release_result_path = run_dir / "release_result.json"
    release_html = ""
    if verify_result and verify_result.get("html"):
        release_html = str((verify_result.get("html") or {}).get("index_html") or "")
    write_release_result(release_result_path, release_result_from_link(link_result, verify_result=verify_result, html=release_html))
    link_status = str(link_result.get("status") or "UNKNOWN")
    verify_status = str((verify_result or {}).get("status") or "")
    final_status = verify_status or link_status
    success_statuses = {"PASS", "PASS_WITH_WARNING", "APPLIED", "FORCED_APPLIED", "DRY_RUN", "FORCE_DRY_RUN"}
    release_failed = final_status not in success_statuses
    failures = list(link_result.get("failed_links", []) or [])
    verify_issues = list((verify_result or {}).get("issues", []) or [])
    if verify_result and release_failed and not failures:
        failures = verify_issues
    for item in selected:
        postcheck_path = Path(verify_result["postcheck_path"]) if verify_result else None
        html_path = Path((verify_result.get("html") or {}).get("index_html")) if verify_result and verify_result.get("html") else None
        update_catalog_release_status(
            args.catalog,
            version_key=item["version_key"],
            action="verify" if verify_result else "link",
            status=(verify_result or link_result).get("status", "UNKNOWN"),
            result_path=postcheck_path or (run_dir / "release_link_result.json"),
            release_dir=link_result.get("release_dir"),
            alias=args.alias,
            manifest_path=manifest_path,
            postcheck_path=postcheck_path,
            html_path=html_path,
        )
    catalog_html = refresh_catalog_html(args)
    output = {
        "status": "PASS" if not release_failed else "FAILED",
        "phase": "postcheck" if verify_result and release_failed else "link",
        "link_status": link_status,
        "verify_status": verify_status or None,
        "release_id": release_id,
        "selected": len(selected) if not effective_manifest else 1,
        "manifest": str(manifest_path),
        "manifest_source": "current_effective" if effective_manifest else "catalog_raw_version",
        "dry_run": not bool(args.apply),
        "release_root": args.release_root,
        "alias": args.alias,
        "overwrite": bool(args.overwrite),
        "link_result": link_result,
        "verify_result": verify_result,
        "failures": failures,
        "verify_issues": verify_issues,
        "library_count": len(manifest.get("libraries", []) or []),
    }
    if catalog_html:
        output["catalog_html"] = catalog_html
    print_json(output)
    return 0 if not release_failed else 2
