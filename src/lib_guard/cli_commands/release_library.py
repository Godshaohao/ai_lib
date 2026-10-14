"""CLI handlers for the read-only formal release-library projection."""

from __future__ import annotations

from argparse import Namespace
from typing import Any

from .common import print_json


def run_release_library_refresh(args: Namespace) -> int:
    from lib_guard.release.library_index import build_release_library_index, write_release_library_index

    index = build_release_library_index(
        args.root,
        max_depth=args.max_depth,
        max_manifests=args.max_manifests,
    )
    output = write_release_library_index(args.out, index)
    print_json(
        {
            "status": "PASS",
            "message": "正式发布库目录已更新；未扫描 RAW，也未执行发布。",
            "index": str(output),
            "release_root": index["release_root"],
            "summary": index["summary"],
            "warnings": index["warnings"],
            "truncated": index["truncated"],
        }
    )
    return 0


def _row_summary(row: dict[str, Any]) -> dict[str, Any]:
    current = row.get("current") if isinstance(row.get("current"), dict) else {}
    return {
        "正式库": row.get("library_id"),
        "当前发布": current.get("release_id") or "-",
        "当前版本": current.get("version_id") or "-",
        "当前来源": current.get("source") or "-",
        "发布历史数": row.get("release_count", 0),
    }


def run_release_library_list(args: Namespace) -> int:
    from lib_guard.release.library_index import load_release_library_index

    index = load_release_library_index(args.input)
    if index.get("status") == "MISSING":
        print_json(
            {
                "status": "MISSING",
                "message": "尚未生成正式发布库目录；请先运行 release-library refresh。",
                "input": args.input,
            }
        )
        return 2
    rows = list(index["libraries"])
    if args.library:
        rows = [row for row in rows if row.get("library_id") == args.library]
    if args.plain:
        for row in rows:
            print(row.get("library_id", ""))
        return 0
    print_json(
        {
            "status": "PASS",
            "message": "以下为正式发布库查询结果；不包含 RAW 候选、扫描状态或待发布版本。",
            "release_root": index["release_root"],
            "refreshed_at": index["refreshed_at"],
            "summary": index["summary"],
            "rows": [_row_summary(row) for row in rows],
            "warnings": index["warnings"],
            "truncated": index["truncated"],
        }
    )
    return 0
