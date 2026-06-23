"""Package-related CLI command handlers."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path
import json

from .common import print_json


def run_package_classify(args: Namespace) -> int:
    from lib_guard.package.classifier import classify_package

    result = classify_package(args.root, library_type=args.library_type)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print_json(result)
    return 0 if result.get("package_type") != "UNKNOWN_PACKAGE" else 2


def run_package_attach(args: Namespace) -> int:
    from lib_guard.package.attach import attach_base

    result = attach_base(args.catalog, package_key=args.package, base_version=args.base, updated_by=args.updated_by or "package.attach")
    print_json({k: v for k, v in result.items() if k != "catalog"})
    return 0


def run_package_assemble(args: Namespace) -> int:
    from lib_guard.package.assemble import assemble_snapshot

    result = assemble_snapshot(
        args.catalog,
        library=args.library,
        base_version=args.base,
        updates=args.update or [],
        out_path=args.out,
        snapshot_id=args.snapshot_id,
    )
    html_result = None
    if args.render:
        from lib_guard.render.snapshot_report import render_snapshot_html

        html_out = args.html_out or str(Path(args.out).with_suffix("")) + "_html"
        html_result = render_snapshot_html(result, html_out)
        result["html"] = html_result
        if args.out:
            Path(args.out).write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print_json({"status": result.get("status"), "snapshot": args.out, "snapshot_id": result.get("snapshot_id"), "file_count": len(result.get("resolved_files", []) or []), "html": html_result})
    return 0 if result.get("status") == "PASS" else 2

