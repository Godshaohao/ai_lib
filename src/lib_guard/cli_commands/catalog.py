"""Catalog and catalog-driven workflow CLI command handlers."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace
from typing import Any
import json

from .common import auto_scan_id, default_cache_dir, default_state_dir, print_json, refresh_catalog_html


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
        result["html"] = render_catalog_html(Path(args.out) / "catalog.json", html_out)
    print_json({k: v for k, v in result.items() if k != "catalog"})
    return 0 if result.get("status") == "PASS" else 2


def _library_match_names(lib: dict[str, Any]) -> set[str]:
    names = {str(lib.get("library_name") or ""), str(lib.get("library_id") or "")}
    names.update(str(a) for a in lib.get("aliases", []) or [] if str(a))
    return {name for name in names if name}


def run_catalog_list(args: Namespace) -> int:
    data = json.loads(Path(args.catalog).read_text(encoding="utf-8"))
    rows = []
    for lib in data.get("libraries", []) or []:
        if args.library and args.library not in _library_match_names(lib):
            continue
        if args.versions:
            for version in lib.get("versions", []) or []:
                rows.append(
                    {
                        "library_id": lib.get("library_id"),
                        "version_id": version.get("version_id"),
                        "stage": version.get("stage"),
                        "raw_path": version.get("raw_path"),
                        "manual_review": version.get("manual_review"),
                        "recommended_action": version.get("recommended_action"),
                    }
                )
        else:
            rows.append({"library_id": lib.get("library_id"), "library_name": lib.get("library_name"), **(lib.get("summary") or {})})
    print_json({"status": "PASS", "rows": rows})
    return 0


def run_catalog_render(args: Namespace) -> int:
    from lib_guard.catalog.index import render_catalog_html

    result = render_catalog_html(args.catalog, args.out)
    print_json(result)
    return 0 if result.get("status") == "PASS" else 2


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
        manual_review=args.manual_review,
        note=args.note,
        updated_by=args.updated_by,
    )
    print_json({k: v for k, v in result.items() if k != "catalog"})
    return 0 if result.get("status") == "PASS" else 2


def run_catalog_workflow(args: Namespace) -> int:
    from lib_guard.catalog.index import find_catalog_version, update_catalog_scan_status
    from lib_guard.render.control_console import render_console
    from lib_guard.render.html_report import render_scan_html
    from lib_guard.scan.scanner import ScanRunner

    item = find_catalog_version(args.catalog, args.library, args.version)
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
        tool_version="0.5.0",
        schema_version="1.0",
        package_type=item.get("package_type"),
        update_scope=item.get("update_scope"),
        standalone=item.get("standalone"),
        base_required=item.get("base_required"),
        base_version=item.get("base_version") or (item.get("lineage", {}) or {}).get("base_candidate"),
    )
    scan_result = ScanRunner(cfg).run()
    scan_html = render_scan_html(scan_result.out_dir, args.html_out or str(Path(args.workdir) / "reports" / item["library_name"] / item["version_id"] / "scan_html"))
    console_html = render_console(scan_result.out_dir, args.console_out or str(Path(args.workdir) / "reports" / item["library_name"] / item["version_id"] / "console"), workdir=args.workdir, config_dir=args.config_dir)
    update_catalog_scan_status(
        args.catalog,
        version_key=item["version_key"],
        scan_dir=scan_result.out_dir,
        scan_id=scan_result.scan_id,
        status=scan_result.status,
        scan_html=scan_html.get("index_html"),
        console_html=console_html.get("index_html"),
    )
    catalog_html = refresh_catalog_html(args)
    result = {
        "status": scan_result.status,
        "catalog": args.catalog,
        "library": item["library_name"],
        "version": item["version_id"],
        "scan_dir": scan_result.out_dir,
        "scan_html": scan_html,
        "console_html": console_html,
    }
    if catalog_html:
        result["catalog_html"] = catalog_html
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
        mode=getattr(args, "scan_mode", "signature"),
        workdir=getattr(args, "workdir", "work"),
        out=None,
        html_out=None,
        console_out=None,
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
    if rescan or (scan_if_missing and not _has_scan_dir(old_item)):
        plan.append(old_item)
    if rescan or (scan_if_missing and not _has_scan_dir(new_item)):
        # Avoid double scan if old and new are the same by mistake.
        if new_item.get("version_key") not in {item.get("version_key") for item in plan}:
            plan.append(new_item)

    if not scan_if_missing and not rescan:
        missing = [item.get("version_id") for item in [old_item, new_item] if not _has_scan_dir(item)]
        if missing:
            raise ValueError(
                "compare requires existing scan evidence for old/new versions. "
                f"Missing scan_dir for: {', '.join(str(x) for x in missing)}. "
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
    new = pair["new"]
    old = pair["old"]
    relation_mode = pair["version_relation"].get("mode") or args.mode
    diff_leaf = f"base_{old['version_id']}" if explicit_base else args.mode
    diff_dir = args.out or str(Path(args.workdir) / "diff" / new["library_name"] / new["version_id"] / diff_leaf)
    diff_result = diff_scan_outputs(pair["old_scan"], pair["new_scan"], out_path=diff_dir, version_relation=pair["version_relation"])
    html_out = args.html_out or str(Path(diff_dir).parent / "diff_html")
    html_result = render_diff_html(diff_dir, html_out)
    update_catalog_diff_status(
        args.catalog,
        version_key=new["version_key"],
        mode=relation_mode,
        old_version=old["version_id"],
        diff_dir=diff_dir,
        status=diff_result.get("status", "DIFF"),
        diff_html=html_result.get("index_html"),
    )
    catalog_html = refresh_catalog_html(args)
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
    if catalog_html:
        result["catalog_html"] = catalog_html
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


def run_catalog_batch(args: Namespace) -> int:
    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    selected = []
    skipped_existing = 0
    skipped_stage = 0
    for item in _catalog_versions(args.catalog, args.library):
        if args.stage and item.get("stage") != args.stage:
            skipped_stage += 1
            continue
        if args.only_missing and item.get("scan", {}).get("status") != "NOT_SCANNED":
            skipped_existing += 1
            continue
        selected.append(item)
        if args.limit and len(selected) >= args.limit:
            break
    for item in selected:
        child = Namespace(**vars(args))
        child.library = item["library_name"]
        child.version = item["version_id"]
        child.out = None
        child.html_out = None
        child.console_out = None
        child.no_catalog_render = True
        try:
            code = run_catalog_workflow(child)
            results.append({"version": item["version_id"], "exit_code": code})
            if code != 0:
                failures.append({"version": item["version_id"], "exit_code": code})
        except Exception as exc:
            failures.append({"version": item["version_id"], "error": str(exc)})
    catalog_html = refresh_catalog_html(args)
    output = {
        "status": "PASS" if not failures else "FAILED",
        "selected": len(selected),
        "skipped_existing": skipped_existing,
        "skipped_stage": skipped_stage,
        "selected_versions": [item.get("version_id") for item in selected],
        "results": results,
        "failures": failures,
    }
    if catalog_html:
        output["catalog_html"] = catalog_html
    print_json(output)
    return 0 if not failures else 2


def run_catalog_compare_batch(args: Namespace) -> int:
    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    selected = []
    skipped_existing = 0
    skipped_stage = 0
    skipped_not_ready = 0
    for item in _catalog_versions(args.catalog, args.library):
        if args.stage and item.get("stage") != args.stage:
            skipped_stage += 1
            continue
        diff = item.get("diff", {}) or {}
        scan = item.get("scan", {}) or {}
        old_version = diff.get("cumulative_base_version") if args.mode == "cumulative" else diff.get("adjacent_old_version")
        if args.only_ready:
            if not scan.get("scan_dir") or not old_version:
                skipped_not_ready += 1
                continue
            old = next((v for v in _catalog_versions(args.catalog, item["library_name"]) if v.get("version_id") == old_version), None)
            if not old or not old.get("scan", {}).get("scan_dir"):
                skipped_not_ready += 1
                continue
        status_key = "cumulative_status" if args.mode == "cumulative" else "adjacent_status"
        if args.only_pending and diff.get(status_key) != "PENDING":
            skipped_existing += 1
            continue
        selected.append(item)
        if args.limit and len(selected) >= args.limit:
            break
    for item in selected:
        child = Namespace(**vars(args))
        child.library = item["library_name"]
        child.new = item["version_id"]
        child.base = None
        child.out = None
        child.html_out = None
        child.no_catalog_render = True
        try:
            code = run_catalog_compare(child)
            results.append({"version": item["version_id"], "exit_code": code})
            if code != 0:
                failures.append({"version": item["version_id"], "exit_code": code})
        except Exception as exc:
            failures.append({"version": item["version_id"], "error": str(exc)})
    catalog_html = refresh_catalog_html(args)
    output = {
        "status": "PASS" if not failures else "FAILED",
        "selected": len(selected),
        "skipped_existing": skipped_existing,
        "skipped_stage": skipped_stage,
        "skipped_not_ready": skipped_not_ready,
        "selected_versions": [item.get("version_id") for item in selected],
        "results": results,
        "failures": failures,
    }
    if catalog_html:
        output["catalog_html"] = catalog_html
    print_json(output)
    return 0 if not failures else 2


def run_catalog_release_check(args: Namespace) -> int:
    from lib_guard.catalog.index import find_catalog_version, update_catalog_release_status
    from lib_guard.release.checker import check_release_scan
    from lib_guard.review.release_result import release_result_from_check, write_release_result

    item = find_catalog_version(args.catalog, args.library, args.version)
    scan_dir = item.get("scan", {}).get("scan_dir")
    if not scan_dir:
        raise ValueError(f"catalog version {item['version_key']} has no scan_dir; run it first")
    diff_dir = getattr(args, "diff", None)
    if not diff_dir and args.diff_mode:
        diff = item.get("diff", {}) or {}
        diff_dir = diff.get("cumulative_diff_dir") if args.diff_mode == "cumulative" else diff.get("adjacent_diff_dir")
    result = check_release_scan(scan_dir, policy_path=args.policy, diff_dir=diff_dir)
    result_path = Path(scan_dir) / "release" / "release_check.json"
    release_result_path = Path(scan_dir) / "release" / "release_result.json"
    write_release_result(release_result_path, release_result_from_check(result))
    update_catalog_release_status(args.catalog, version_key=item["version_key"], action="check", status=result.get("release_check_status", "UNKNOWN"), result_path=result_path)
    print_json(result)
    return 0


def run_catalog_release_link(args: Namespace) -> int:
    from lib_guard.catalog.index import find_catalog_version, update_catalog_release_status
    from lib_guard.release.bundle import create_manifest_template_from_catalog
    from lib_guard.release.linker import link_release_from_manifest
    from lib_guard.review.release_result import release_result_from_link, write_release_result

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
    from lib_guard.release.bundle import create_manifest_template_from_catalog
    from lib_guard.release.linker import link_release_from_manifest
    from lib_guard.release.postcheck import verify_release_manifest
    from lib_guard.review.release_result import release_result_from_link, write_release_result

    requested_versions = set(args.version or [])
    selected = []
    for item in _catalog_versions(args.catalog, args.library):
        if requested_versions and item.get("version_id") not in requested_versions and item.get("version_key") not in requested_versions:
            continue
        if args.stage and item.get("stage") != args.stage:
            continue
        if not item.get("scan", {}).get("scan_dir"):
            continue
        release = item.get("release", {}) or {}
        if args.only_checked and release.get("check_status") not in {"PASS", "PASS_WITH_WARNING"}:
            continue
        if args.only_ready:
            if item.get("manual_review") or release.get("check_status") in {"BLOCK", "FAILED"}:
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
    catalog_path = Path(args.catalog)
    release_id = getattr(args, "release_id", None) or f"{str(args.alias).upper()}_{auto_scan_id()}"
    if getattr(args, "out", None):
        run_dir = Path(args.out)
    elif catalog_path.parent.name == "catalog":
        run_dir = catalog_path.parent.parent / "release_runs" / release_id
    else:
        run_dir = catalog_path.parent / "release_runs" / release_id
    manifest_path = run_dir / "release_manifest.json"
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
    )
    verify_result = None
    if bool(args.apply) and not getattr(args, "no_verify", False):
        verify_result = verify_release_manifest(manifest_path, render=not getattr(args, "no_render", False))
    release_result_path = run_dir / "release_result.json"
    release_html = ""
    if verify_result and verify_result.get("html"):
        release_html = str((verify_result.get("html") or {}).get("index_html") or "")
    write_release_result(release_result_path, release_result_from_link(link_result, verify_result=verify_result, html=release_html))
    failures = list(link_result.get("failed_links", []) or [])
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
        "status": "PASS" if not failures else "FAILED",
        "release_id": release_id,
        "selected": len(selected),
        "manifest": str(manifest_path),
        "dry_run": not bool(args.apply),
        "release_root": args.release_root,
        "alias": args.alias,
        "overwrite": bool(args.overwrite),
        "link_result": link_result,
        "verify_result": verify_result,
        "failures": failures,
        "library_count": len(manifest.get("libraries", []) or []),
    }
    if catalog_html:
        output["catalog_html"] = catalog_html
    print_json(output)
    return 0 if not failures else 2
