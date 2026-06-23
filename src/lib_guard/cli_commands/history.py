"""history CLI command handlers."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace
from typing import Any
import json

from .common import print_json


def run_history_list(args: Namespace) -> int:
    from lib_guard.history.index import HistoryIndex
    runs = HistoryIndex(args.workdir).list_runs(args.library_id)
    print_json({"runs": runs})
    return 0


def run_history_latest(args: Namespace) -> int:
    from lib_guard.history.index import HistoryIndex
    out = HistoryIndex(args.workdir).latest(args.library_id, mode=args.mode, kind=args.kind)
    print_json({"library_id": args.library_id, "mode": args.mode, "kind": args.kind, "latest": out})
    return 0 if out else 2

