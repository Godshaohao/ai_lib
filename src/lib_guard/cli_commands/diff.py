"""Diff-related CLI command handlers."""

from __future__ import annotations

from argparse import Namespace

from .common import print_json


def run_diff_scan(args: Namespace) -> int:
    from lib_guard.diff.scan_diff import diff_scan_outputs

    version_relation = {
        "diff_mode": args.diff_mode,
        "old_version_type": args.old_version_type,
        "new_version_type": args.new_version_type,
        "release_line": args.release_line,
        "parent_version": args.parent_version,
        "base_version": args.base_version,
    }
    result = diff_scan_outputs(args.old, args.new, out_path=args.out, version_relation=version_relation)
    print_json(result)
    return 0 if result.get("status") in {"SAME", "DIFF", "PASS_WITH_WARNING"} else 2


def run_diff_adjacent(args: Namespace) -> int:
    from lib_guard.diff.scan_diff import diff_scan_outputs
    from lib_guard.version.index import resolve_adjacent_pair

    if args.scan_if_missing:
        raise NotImplementedError("--scan-if-missing is reserved but not implemented in this release")
    pair = resolve_adjacent_pair(args.library_id, args.new_version, workdir=args.workdir)
    result = diff_scan_outputs(pair["old_scan"], pair["new_scan"], out_path=args.out, version_relation=pair["version_relation"])
    print_json(result)
    return 0 if result.get("status") in {"SAME", "DIFF", "PASS_WITH_WARNING"} else 2


def run_diff_cumulative(args: Namespace) -> int:
    from lib_guard.diff.scan_diff import diff_scan_outputs
    from lib_guard.version.index import resolve_cumulative_pair

    if args.scan_if_missing:
        raise NotImplementedError("--scan-if-missing is reserved but not implemented in this release")
    pair = resolve_cumulative_pair(args.library_id, args.new_version, workdir=args.workdir)
    result = diff_scan_outputs(pair["old_scan"], pair["new_scan"], out_path=args.out, version_relation=pair["version_relation"])
    print_json(result)
    return 0 if result.get("status") in {"SAME", "DIFF", "PASS_WITH_WARNING"} else 2


def run_diff_render(args: Namespace) -> int:
    from lib_guard.render.html_report import render_diff_html

    result = render_diff_html(args.diff, args.out)
    print_json(result)
    return 0 if result.get("status") == "PASS" else 2


def run_file_diff(args: Namespace) -> int:
    from lib_guard.diff.file_diff import diff_pairwise_files

    result = diff_pairwise_files(
        args.file_type,
        args.old,
        args.new,
        args.out,
        task_id=getattr(args, "task_id", None),
        library_id=getattr(args, "library_id", None),
        version_id=getattr(args, "version_id", None),
        base_version=getattr(args, "base_version", None),
    )
    print_json(result)
    return 0 if result.get("status") in {"SAME", "DIFF"} else 2
