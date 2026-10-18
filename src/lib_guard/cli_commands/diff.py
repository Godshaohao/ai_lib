"""Diff-related CLI command handlers."""

from __future__ import annotations

from argparse import Namespace
import sys
import time

from .common import print_json


COMPLETED_DIFF_STATUSES = {"SAME", "DIFF", "PASS_WITH_WARNING", "UNVERIFIED"}


def _diff_exit_code(result: dict[str, object]) -> int:
    return 0 if result.get("status") in COMPLETED_DIFF_STATUSES else 2


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
    return _diff_exit_code(result)


def run_diff_adjacent(args: Namespace) -> int:
    from lib_guard.diff.scan_diff import diff_scan_outputs
    from lib_guard.version.index import resolve_adjacent_pair

    if args.scan_if_missing:
        raise NotImplementedError("--scan-if-missing is reserved but not implemented in this release")
    pair = resolve_adjacent_pair(args.library_id, args.new_version, workdir=args.workdir)
    result = diff_scan_outputs(pair["old_scan"], pair["new_scan"], out_path=args.out, version_relation=pair["version_relation"])
    print_json(result)
    return _diff_exit_code(result)


def run_diff_cumulative(args: Namespace) -> int:
    from lib_guard.diff.scan_diff import diff_scan_outputs
    from lib_guard.version.index import resolve_cumulative_pair

    if args.scan_if_missing:
        raise NotImplementedError("--scan-if-missing is reserved but not implemented in this release")
    pair = resolve_cumulative_pair(args.library_id, args.new_version, workdir=args.workdir)
    result = diff_scan_outputs(pair["old_scan"], pair["new_scan"], out_path=args.out, version_relation=pair["version_relation"])
    print_json(result)
    return _diff_exit_code(result)


def run_diff_render(args: Namespace) -> int:
    from lib_guard.render.html_report import render_diff_html

    result = render_diff_html(args.diff, args.out)
    print_json(result)
    return 0 if result.get("status") == "PASS" else 2


def run_file_diff(args: Namespace) -> int:
    from lib_guard.diff.file_diff import diff_pairwise_files

    started_epoch = time.time()
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
    if result.get('status') in {'SAME', 'DIFF'} and getattr(args, 'catalog', None) and getattr(args, 'catalog_html_out', None):
        try:
            from lib_guard.review.publication import publish_file_diff
            publish_file_diff(args.catalog, args.catalog_html_out, args.library_id, args.version_id, args.out,
                              updated_by='cli', started_epoch=started_epoch)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            print(f'阅读报告未同步；深度对比结果已保留，可重新刷新：{exc}', file=sys.stderr)
    elif result.get('status') in {'SAME', 'DIFF'} and getattr(args, 'library_id', None) and getattr(args, 'version_id', None):
        print('阅读报告未同步：请同时指定 --catalog 和 --catalog-html-out。', file=sys.stderr)
    print_json(result)
    return 0 if result.get("status") in {"SAME", "DIFF"} else 2
