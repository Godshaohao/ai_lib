"""console CLI command handlers."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace
from typing import Any
import json

from .common import print_json


def run_console_build(args: Namespace) -> int:
    from lib_guard.history.index import resolve_scan_dir
    from lib_guard.render.control_console import render_console

    scan_dir = resolve_scan_dir(scan=args.scan, latest=args.latest, library_id=args.library_id, mode=args.mode, workdir=args.workdir)
    out_dir = args.out
    if not out_dir:
        lid = (args.library_id or "manual").replace("/", "_")
        out_dir = str(Path(args.workdir) / "reports" / lid / "console_latest")
    result = render_console(scan_dir, out_dir, workdir=args.workdir, config_dir=args.config_dir)
    print_json(result)
    return 0 if result.get("status") == "PASS" else 2


def run_console_config(args: Namespace) -> int:
    from lib_guard.render.control_data import build_config_view, write_json

    result = build_config_view(config_dir=args.config_dir)
    write_json(args.out, result)
    print_json({"status": "PASS", "out": args.out, "config_count": len(result.get("configs", []))})
    return 0


def run_console_review(args: Namespace) -> int:
    from lib_guard.history.index import resolve_scan_dir
    from lib_guard.render.control_data import build_review_items, write_json

    scan_dir = resolve_scan_dir(scan=args.scan, latest=args.latest, library_id=args.library_id, mode=args.mode, workdir=args.workdir)
    result = build_review_items(scan_dir, config_dir=args.config_dir)
    write_json(args.out, result)
    print_json({"status": "PASS", "out": args.out, "review_items": len(result.get("review_items", []))})
    return 0

