"""version CLI command handlers."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace
from typing import Any
import json

from .common import print_json


def run_version_register(args: Namespace) -> int:
    from lib_guard.version.index import register_scan_version

    result = register_scan_version(
        args.scan,
        workdir=args.workdir,
        library_id=args.library_id,
        version_id=args.version_id,
        version_type=args.version_type,
        release_line=args.release_line,
        parent_version=args.parent_version,
        base_version=args.base_version,
        raw_root=args.raw_root,
        overwrite=args.overwrite,
    )
    print_json({"status": "PASS", "version": result})
    return 0


def run_version_list(args: Namespace) -> int:
    from lib_guard.version.index import VersionIndex

    rows = VersionIndex(args.workdir).list_versions(args.library_id)
    print_json({"status": "PASS", "versions": rows})
    return 0

