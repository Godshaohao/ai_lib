"""update CLI command handlers."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace
from typing import Any
import json

from .common import print_json


def run_update_file(args: Namespace) -> int:
    from lib_guard.update.updater import update_file
    result = update_file(
        library_id=args.library_id,
        file=args.file,
        scope=args.scope,
        mode=args.mode,
        workdir=args.workdir,
        policy_path=args.policy,
        rebuild_summary=not args.no_rebuild_summary,
    )
    print_json(result)
    return 0 if result.get("status") in {"PASS", "WARNING"} else 2


def run_update_type(args: Namespace) -> int:
    from lib_guard.update.updater import update_type
    result = update_type(
        library_id=args.library_id,
        file_type=args.type,
        scope=args.scope,
        mode=args.mode,
        workdir=args.workdir,
        policy_path=args.policy,
        skip_cache=args.skip_cache,
        rebuild_summary=not args.no_rebuild_summary,
    )
    print_json(result)
    return 0 if result.get("status") == "PASS" else 2

