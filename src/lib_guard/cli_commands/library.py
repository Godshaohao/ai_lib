"""Library registry CLI command handlers."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path

from .common import print_json


def run_library_discover(args: Namespace) -> int:
    from lib_guard.library_registry import discover_to_files

    result = discover_to_files(
        args.root,
        list_out=args.out,
        json_out=args.json_out,
        html_out=args.html_out,
        max_depth=args.max_depth,
        min_versions=args.min_versions,
        default_status=args.default_status,
    )
    print_json(result)
    return 0 if result.get("status") == "PASS" else 2


def run_library_apply(args: Namespace) -> int:
    from lib_guard.library_registry import apply_list_to_catalog

    result = apply_list_to_catalog(
        args.root,
        list_path=args.input,
        out_path=args.out,
        library_type=args.library_type,
    )
    print_json(result)
    return 0 if result.get("status") == "PASS" else 2
