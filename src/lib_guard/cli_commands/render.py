"""render CLI command handlers."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace
from typing import Any
import json

from .common import print_json


def run_render_command(args: Namespace) -> int:
    from lib_guard.history.index import resolve_scan_dir
    from lib_guard.render.html_report import render_scan_html

    scan_dir = resolve_scan_dir(scan=args.scan, latest=args.latest, library_id=args.library_id, mode=args.mode, workdir=args.workdir)
    out_dir = args.out
    if not out_dir:
        out_dir = str(Path(args.workdir) / "reports" / (args.library_id or "manual").replace("/", "_") / f"{args.mode or 'scan'}_html")
    result = render_scan_html(scan_dir, out_dir)
    print_json(result)
    return 0 if result.get("status") == "PASS" else 2

