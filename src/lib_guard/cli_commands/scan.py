"""scan CLI command handlers."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace
from typing import Any
import json
import logging

from lib_guard.artifacts import canonical_scan_dir, scan_artifacts, write_run_manifest
from .common import auto_scan_id, default_cache_dir, default_state_dir, print_json


LOGGER = logging.getLogger("lib_guard")


def split_strategy_list(value: Any) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        items = value.replace(";", ",").replace(" ", ",").split(",")
    elif isinstance(value, (list, tuple, set)):
        items = list(value)
    else:
        items = [value]
    return [str(item).strip().lower() for item in items if str(item).strip()]


def library_id_from_args(args: Namespace) -> str:
    if getattr(args, "library_id", None):
        return args.library_id
    return "/".join([str(args.profile or "unknown"), str(args.name or "unknown"), str(args.version or "unknown")])


def format_out_template(template: str, *, library_type: str, library_name: str, version: str, mode: str, scan_id: str) -> str:
    return template.format(
        library_type=library_type or "unknown",
        library_name=library_name or "unknown",
        version=version or "unknown",
        mode=mode or "scan",
        scan_id=scan_id,
    )


def build_scan_config(args: Namespace) -> SimpleNamespace:
    scan_id = args.scan_id or auto_scan_id()
    out_dir = args.out
    if not out_dir:
        if args.out_template:
            out_dir = format_out_template(
                args.out_template,
                library_type=args.profile,
                library_name=args.name,
                version=args.version,
                mode=args.mode,
                scan_id=scan_id,
            )
        else:
            out_dir = str(
                canonical_scan_dir(
                    args.workdir,
                    library_type=args.profile,
                    library_name=args.name,
                    version=args.version,
                    mode=args.mode,
                    scan_id=scan_id,
                )
            )

    cfg = SimpleNamespace(
        root_path=args.root,
        root=args.root,
        library_type=args.profile,
        profile=args.profile,
        library_name=args.name,
        name=args.name,
        version=args.version,
        release_version=args.version,
        scan_mode=args.mode,
        mode=args.mode,
        scan_id=scan_id,
        out_dir=out_dir,
        out=out_dir,
        workdir=args.workdir,
        state_dir=args.state_dir or default_state_dir(args.workdir, args.profile, args.name, args.version),
        cache_dir=args.cache_dir or default_cache_dir(args.workdir),
        config=args.config,
        no_progress=args.no_progress,
        console_progress=args.console_progress,
        progress_interval=args.progress_interval,
        parse_jobs=args.parse_jobs,
        skip_cache=args.skip_cache,
        no_cache=args.no_cache,
        hash_policy=getattr(args, "hash_policy", None),
        force_hash_file_types=split_strategy_list(getattr(args, "force_hash_file_types", None)),
        skip_hash_file_types=split_strategy_list(getattr(args, "skip_hash_file_types", None)),
        parse_file_types=split_strategy_list(getattr(args, "parse_file_types", None)),
        parse_exclude_file_types=split_strategy_list(getattr(args, "parse_exclude_file_types", None)),
        tool_version="0.5.0",
        schema_version="1.0",
        package_type=getattr(args, "package_type", None),
        update_scope=getattr(args, "update_scope", None),
        standalone=getattr(args, "standalone", None),
        base_required=getattr(args, "base_required", None),
        base_version=getattr(args, "base_version", None),
        # Keep the large aggregate Parser JSON for direct/legacy callers only.
        # The normal CLI retains parser_manifest plus per-file evidence.
        write_raw_parser_results=getattr(args, "write_raw_parser_results", False),
    )
    return cfg


def run_scan_command(args: Namespace) -> int:
    from lib_guard.scan.scanner import ScanRunner
    from lib_guard.history.index import register_scan_run

    cfg = build_scan_config(args)
    result = ScanRunner(cfg).run()

    if args.register_history:
        try:
            register_scan_run(result.out_dir, workdir=args.workdir, update_latest=args.update_latest)
        except Exception as exc:
            LOGGER.warning("failed to register scan history: %s", exc)

    scan_html: str | None = None
    if args.render:
        html_out = args.html_out
        if not html_out:
            html_out = str(Path(args.workdir) / "reports" / cfg.library_type / cfg.library_name / cfg.version / f"{cfg.mode}_{cfg.scan_id}_html")
        try:
            from lib_guard.render.html_report import render_scan_html
            render_result = render_scan_html(result.out_dir, html_out)
            scan_html = render_result.get("index_html")
            LOGGER.info("html report generated: %s", scan_html)
        except Exception as exc:
            LOGGER.warning("render failed: %s", exc)

    manifest_path = write_run_manifest(
        result.out_dir,
        operation="scan",
        status=result.status,
        run_id=result.scan_id,
        library_type=cfg.library_type,
        library_name=cfg.library_name,
        version=cfg.version,
        inputs={"raw_root": str(cfg.root_path), "workdir": str(cfg.workdir)},
        artifacts=scan_artifacts(result.out_dir, scan_html=scan_html),
        warnings=["scan HTML 未生成或生成失败"] if args.render and not scan_html else [],
    )
    print_json({
        "status": result.status,
        "scan_id": result.scan_id,
        "out_dir": result.out_dir,
        "run_manifest": str(manifest_path),
        "scan_html": scan_html,
        "stats": result.stats,
    })
    return 0 if result.status not in {"FAILED", "BLOCK"} else 2


def build_scan_status(scan_dir: str | Path) -> dict[str, Any]:
    scan = Path(scan_dir)

    def read(rel: str, default: Any) -> Any:
        path = scan / rel
        try:
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            return {"read_error": str(exc), "path": str(path)}
        return default

    latest = read("logs/scan_progress_latest.json", {})
    meta = read("scan_meta.json", {})
    manifest = read("parser_manifest.json", {"files": []})
    task_list = read("parser_task_list.json", {"task_count": 0})
    parser_result_files = list((scan / "parser_results").glob("**/*.json")) if (scan / "parser_results").exists() else []
    outputs = {
        "scan_meta": (scan / "scan_meta.json").exists(),
        "file_inventory": (scan / "file_inventory.json").exists(),
        "parser_task_list": (scan / "parser_task_list.json").exists(),
        "parser_manifest": (scan / "parser_manifest.json").exists(),
        "parser_results_json": (scan / "parser_results.json").exists(),
        "parser_results_dir": (scan / "parser_results").exists(),
        "parser_results_available": (scan / "parser_results.json").exists() or bool(parser_result_files),
        "parser_quality": (scan / "summary" / "parser_quality.json").exists(),
        "release_readiness": (scan / "summary" / "release_readiness.json").exists(),
    }
    status = str(meta.get("status") or latest.get("status") or "RUNNING")
    if latest.get("event") == "finish":
        status = "FINISHED" if status not in {"FAILED", "BLOCK"} else status
    return {
        "schema_version": "1.0",
        "status": status,
        "scan_dir": str(scan),
        "scan_id": meta.get("scan_id") or latest.get("scan_id"),
        "library_id": meta.get("library_id"),
        "stage": latest.get("stage"),
        "event": latest.get("event"),
        "message": latest.get("message"),
        "done": latest.get("done"),
        "total": latest.get("total"),
        "percent": latest.get("percent"),
        "summary": latest.get("summary") or {},
        "by_type": latest.get("by_type") or {},
        "active_workers": latest.get("active_workers") or [],
        "slowest_files": latest.get("slowest_files") or [],
        "performance": latest.get("performance") or {},
        "task_count": task_list.get("task_count", 0),
        "manifest_file_count": len(manifest.get("files", []) or []),
        "parser_result_file_count": len(parser_result_files),
        "outputs": outputs,
    }


def run_scan_status(args: Namespace) -> int:
    from lib_guard.history.index import resolve_scan_dir

    scan_dir = resolve_scan_dir(scan=args.scan, latest=args.latest, library_id=args.library_id, mode=args.mode, workdir=args.workdir)
    print_json(build_scan_status(scan_dir))
    return 0
