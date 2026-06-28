from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from lib_guard.effective.compare import build_compare_manifest, write_compare_manifest
from lib_guard.effective.manifest import (
    add_update_to_manifest,
    build_effective_manifest,
    read_json,
    release_preview,
    write_json,
    write_release_preview_outputs,
)
from lib_guard.effective.pointer import load_current_pointer, write_current_pointer
from lib_guard.render.compare_report import write_compare_report
from lib_guard.render.effective_report import write_effective_report


def _parse_include(values: list[str] | None, scope_values: list[str] | None) -> list[tuple[str, str | None]]:
    includes = values or []
    scope_map: dict[str, str] = {}
    for item in scope_values or []:
        if ":" in item:
            version, scope = item.split(":", 1)
            scope_map[version.strip()] = scope.strip()
        else:
            scope_map["__default__"] = item.strip()
    return [(v, scope_map.get(v, scope_map.get("__default__"))) for v in includes]


def _load_optional_json(path: str | None) -> dict[str, Any] | None:
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        return None
    return read_json(p)


def _normalized_link_mode(value: str) -> str:
    return "link" if value == "symlink" else value


def cmd_build(args: argparse.Namespace) -> int:
    catalog = read_json(args.catalog)
    manifest = build_effective_manifest(
        catalog,
        args.library,
        args.base_full,
        _parse_include(args.include, args.scope),
        effective_id=args.effective_id,
        delete_files=args.delete_file,
        note=args.note,
    )
    write_json(args.out, manifest)
    preview = None
    release_preview_html = None
    if args.release_preview:
        preview = release_preview(manifest, release_root=args.release_root, release_id=args.release_id, link_mode=_normalized_link_mode(args.link_mode))
        write_release_preview_outputs(args.release_preview, preview)
        release_preview_html = str(Path(args.release_preview) / "index.html")
        write_effective_report(manifest, preview, release_preview_html)
    if args.html:
        write_effective_report(manifest, preview, args.html)
    print(json.dumps({"status": "PASS", "effective_manifest": args.out, "html": args.html, "release_preview_html": release_preview_html}, ensure_ascii=False, indent=2))
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    catalog = read_json(args.catalog)
    current = read_json(args.current)
    manifest = add_update_to_manifest(current, catalog, args.library, args.version, args.scope, effective_id=args.effective_id)
    write_json(args.out, manifest)
    preview = None
    release_preview_html = None
    if args.release_preview:
        previous = _load_optional_json(args.previous_release)
        preview = release_preview(manifest, previous_release=previous, release_root=args.release_root, release_id=args.release_id, link_mode=_normalized_link_mode(args.link_mode))
        write_release_preview_outputs(args.release_preview, preview)
        release_preview_html = str(Path(args.release_preview) / "index.html")
        write_effective_report(manifest, preview, release_preview_html)
    if args.html:
        write_effective_report(manifest, preview, args.html)
    print(json.dumps({"status": "PASS", "effective_manifest": args.out, "html": args.html, "release_preview_html": release_preview_html}, ensure_ascii=False, indent=2))
    return 0


def cmd_release_preview(args: argparse.Namespace) -> int:
    manifest = read_json(args.effective)
    previous = _load_optional_json(args.previous_release)
    preview = release_preview(manifest, previous_release=previous, release_root=args.release_root, release_id=args.release_id, link_mode=_normalized_link_mode(args.link_mode))
    outputs = write_release_preview_outputs(args.out_dir, preview)
    html = args.html or str(Path(args.out_dir) / "index.html")
    write_effective_report(manifest, preview, html)
    print(json.dumps({"status": "PASS", **outputs, "html": html}, ensure_ascii=False, indent=2))
    return 0


def cmd_render(args: argparse.Namespace) -> int:
    manifest = read_json(args.effective)
    preview = _load_optional_json(args.release_preview)
    write_effective_report(manifest, preview, args.html)
    print(json.dumps({"status": "PASS", "html": args.html}, ensure_ascii=False, indent=2))
    return 0


def cmd_accept(args: argparse.Namespace) -> int:
    pointer_path = write_current_pointer(
        args.effective,
        out=args.out,
        html=args.html,
        release_preview=args.release_preview,
        status=args.status,
        accepted_by=args.accepted_by,
        note=args.note,
    )
    print(json.dumps({"status": "PASS", "current_effective": str(pointer_path)}, ensure_ascii=False, indent=2))
    return 0


def cmd_current(args: argparse.Namespace) -> int:
    pointer = load_current_pointer(args.out_dir, args.library)
    if not pointer:
        print(json.dumps({"status": "MISSING", "library": args.library}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps({"status": "PASS", "current_effective": pointer}, ensure_ascii=False, indent=2))
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    catalog = read_json(args.catalog) if args.catalog else None
    search_roots = args.search_root or []
    if args.out_dir:
        out_dir_path = Path(args.out_dir)
        search_roots.append(str(out_dir_path.parent.parent.parent if len(out_dir_path.parts) > 3 else out_dir_path.parent))
    manifest = build_compare_manifest(
        catalog,
        args.library,
        args.old,
        args.new,
        search_roots=search_roots,
        mode=args.mode,
        compare_id=args.compare_id,
        owner_target=args.owner_target,
    )
    out_dir = Path(args.out_dir)
    write_compare_manifest(out_dir, manifest)
    html = args.html or str(out_dir / "index.html")
    write_compare_report(manifest, html)
    print(json.dumps({"status": "PASS", "compare_manifest": str(out_dir / "compare_manifest.json"), "html": html}, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="lib_guard effective manifest tools")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("build", help="Build an effective manifest from base full + accepted updates")
    p.add_argument("--catalog", required=True)
    p.add_argument("--library", required=True)
    p.add_argument("--base-full", required=True)
    p.add_argument("--include", action="append", default=[])
    p.add_argument("--scope", action="append", default=[], help="Scope mapping: version:liberty,lef or default scope")
    p.add_argument("--delete-file", action="append", default=[])
    p.add_argument("--effective-id")
    p.add_argument("--note")
    p.add_argument("--out", required=True)
    p.add_argument("--html")
    p.add_argument("--release-preview")
    p.add_argument("--release-root", default="release_area")
    p.add_argument("--release-id")
    p.add_argument("--link-mode", choices=["link", "symlink", "copy"], default="link")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("add", help="Add one update to an existing effective manifest")
    p.add_argument("--catalog", required=True)
    p.add_argument("--library", required=True)
    p.add_argument("--current", required=True)
    p.add_argument("--version", required=True)
    p.add_argument("--scope")
    p.add_argument("--effective-id")
    p.add_argument("--out", required=True)
    p.add_argument("--html")
    p.add_argument("--release-preview")
    p.add_argument("--previous-release")
    p.add_argument("--release-root", default="release_area")
    p.add_argument("--release-id")
    p.add_argument("--link-mode", choices=["link", "symlink", "copy"], default="link")
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("release-preview", help="Generate release manifest/delta from effective manifest")
    p.add_argument("--effective", required=True)
    p.add_argument("--previous-release")
    p.add_argument("--release-root", default="release_area")
    p.add_argument("--release-id")
    p.add_argument("--link-mode", choices=["link", "symlink", "copy"], default="link")
    p.add_argument("--out-dir", required=True)
    p.add_argument("--html")
    p.set_defaults(func=cmd_release_preview)

    p = sub.add_parser("render", help="Render effective report HTML")
    p.add_argument("--effective", required=True)
    p.add_argument("--release-preview")
    p.add_argument("--html", required=True)
    p.set_defaults(func=cmd_render)

    p = sub.add_parser("accept", help="Set an effective manifest as current effective by writing current_effective.json")
    p.add_argument("--effective", required=True)
    p.add_argument("--out", help="Default: <effective_root>/current_effective.json")
    p.add_argument("--html")
    p.add_argument("--release-preview")
    p.add_argument("--status", default="accepted", choices=["accepted", "current", "candidate", "released"])
    p.add_argument("--accepted-by", default="manual")
    p.add_argument("--note")
    p.set_defaults(func=cmd_accept)

    p = sub.add_parser("current", help="Print current_effective.json for a library")
    p.add_argument("--library", required=True)
    p.add_argument("--out-dir", default="reports")
    p.set_defaults(func=cmd_current)

    p = sub.add_parser("compare", help="Generate file-map compare report for raw/effective/release targets")
    p.add_argument("--catalog", help="Required for raw:<version> targets")
    p.add_argument("--library", required=True)
    p.add_argument("--old", required=True, help="raw:<version>, effective:<id-or-manifest>, release:<manifest>")
    p.add_argument("--new", required=True, help="raw:<version>, effective:<id-or-manifest>, release:<manifest>")
    p.add_argument("--out-dir", required=True)
    p.add_argument("--html")
    p.add_argument("--mode")
    p.add_argument("--compare-id")
    p.add_argument("--owner-target")
    p.add_argument("--search-root", action="append", default=[])
    p.set_defaults(func=cmd_compare)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
