from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from lib_guard.effective.pointer import write_current_pointer
from lib_guard.window.resolver import read_json, resolve_review_window, write_json


def _print_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def _quote(value: Any) -> str:
    text = str(value)
    if not text or any(ch.isspace() for ch in text):
        return repr(text)
    return text


def _run_commands(commands: list[list[str]]) -> int:
    from lib_guard.cli import main as cli_main

    for command in commands:
        print("python -m lib_guard.cli " + " ".join(_quote(item) for item in command))
        code = int(cli_main(command))
        if code != 0:
            return code
    return 0


def cmd_intake(args: argparse.Namespace) -> int:
    window = resolve_review_window(
        catalog_path=args.catalog,
        library=args.library,
        workdir=args.workdir,
        catalog_html_out=args.catalog_html_out,
        since=args.since,
        window_path=args.window_file,
        force_rebuild=args.rebuild,
        parse_jobs=str(args.parse_jobs or ""),
        hash_policy=args.hash_policy or "",
        parse_file_types=args.parse_file_types or "",
        parse_exclude_file_types=args.parse_exclude_file_types or "",
    )
    if window.get("state") != "EMPTY":
        write_json(window["pending_window_path"], window)
    _print_json(
        {
            "status": "PASS",
            "window": window.get("pending_window_path"),
            "state": window.get("state"),
            "base": window.get("base_effective"),
            "candidate_effective": window.get("candidate_effective"),
            "compare": window.get("compare"),
            "scan_versions": window.get("scan_versions", []),
            "warnings": window.get("warnings", []),
            "command_count": len(window.get("commands", []) or []),
            "message": window.get("message", ""),
        }
    )
    if args.plan_only or window.get("state") == "EMPTY":
        return 0
    return _run_commands(list(window.get("commands", []) or []))


def cmd_show(args: argparse.Namespace) -> int:
    if args.window_file:
        data = read_json(args.window_file, {}) or {"status": "MISSING", "window": args.window_file}
    else:
        resolved = resolve_review_window(
            catalog_path=args.catalog,
            library=args.library,
            workdir=args.workdir,
            catalog_html_out=args.catalog_html_out,
            since=args.since,
            parse_jobs=str(args.parse_jobs or ""),
        )
        data = read_json(resolved.get("pending_window_path", ""), {}) or resolved
    _print_json(data)
    return 0


def cmd_accept(args: argparse.Namespace) -> int:
    data = read_json(args.window_file, {}) or {}
    if not data:
        raise ValueError(f"window file not found or empty: {args.window_file}")
    manifest = (data.get("candidate_effective") or {}).get("manifest")
    if not manifest:
        raise ValueError("pending window has no candidate effective manifest")
    manifest_path = Path(str(manifest))
    if not manifest_path.exists():
        raise ValueError(f"candidate effective manifest does not exist: {manifest_path}. Run intake first.")
    pointer = write_current_pointer(
        manifest_path,
        status="accepted",
        accepted_by=args.accepted_by,
        note=args.note or "accepted from review window",
    )
    data["state"] = "ACCEPTED"
    data["accepted_by"] = args.accepted_by
    data["current_effective_pointer"] = str(pointer)
    write_json(args.window_file, data)
    _print_json({"status": "PASS", "current_effective": str(pointer), "window": args.window_file})
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Review-window intake tools")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--catalog", required=True)
        p.add_argument("--library", required=True)
        p.add_argument("--workdir", default="work")
        p.add_argument("--catalog-html-out", required=True)
        p.add_argument("--window-file")
        p.add_argument("--since")
        p.add_argument("--parse-jobs", default="")
        p.add_argument("--hash-policy", choices=["none", "smart", "full"])
        p.add_argument("--parse-file-types")
        p.add_argument("--parse-exclude-file-types")

    p = sub.add_parser("intake")
    add_common(p)
    p.add_argument("--plan-only", action="store_true")
    p.add_argument("--rebuild", action="store_true")
    p.set_defaults(func=cmd_intake)

    p = sub.add_parser("show")
    add_common(p)
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("accept")
    p.add_argument("--window-file", required=True)
    p.add_argument("--accepted-by", default="manual")
    p.add_argument("--note")
    p.set_defaults(func=cmd_accept)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
