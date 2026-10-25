#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import fnmatch
import glob
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from typing import Any, Iterable


BUNDLE_FORMAT = "engineering_agent_kernel_text_bundle"
BUNDLE_VERSION = 1
SUPPORTED_FORMATS = {BUNDLE_FORMAT, "engineering_agent_kernel_text_bundle", "ic_pd_text_bundle"}

DEFAULT_EXCLUDES = [
    ".git/**",
    "__pycache__/**",
    "**/__pycache__/**",
    ".pytest_cache/**",
    "**/.pytest_cache/**",
    "work/**",
    "archive/**",
    "_tmp_*/**",
    "*.pyc",
    "*.pyo",
    "*.png",
    "*.jpg",
    "*.jpeg",
    "*.gif",
    "*.bmp",
    "*.ico",
    "*.pdf",
    "*.doc",
    "*.docx",
    "*.ppt",
    "*.pptx",
    "*.xls",
    "*.xlsx",
    "*.zip",
    "*.tar",
    "*.gz",
    "*.7z",
    "*.rar",
    "*_bundle.json",
    "*.part*.json",
]


def rel_posix(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def is_excluded(rel: str, patterns: Iterable[str]) -> bool:
    return any(fnmatch.fnmatch(rel, pattern) for pattern in patterns)


def looks_text(data: bytes) -> bool:
    if b"\x00" in data:
        return False
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def entry_for(path: Path, root: Path, include_binary: bool) -> dict[str, Any] | None:
    data = path.read_bytes()
    if not include_binary and not looks_text(data):
        return None
    return {
        "path": rel_posix(path, root),
        "mode": oct(path.stat().st_mode & 0o777),
        "sha256": sha256(data),
        "size": len(data),
        "encoding": "base64",
        "content": base64.b64encode(data).decode("ascii"),
    }


def iter_paths(root: Path, includes: list[str], excludes: list[str]) -> list[Path]:
    if includes:
        found: dict[str, Path] = {}
        for raw in includes:
            candidate = Path(raw)
            path = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
            if path != root and root not in path.parents:
                raise ValueError(f"include path is outside root: {raw}")
            if not path.exists():
                raise FileNotFoundError(f"include path not found: {raw}")
            paths = sorted(path.rglob("*")) if path.is_dir() else [path]
            for item in paths:
                if item.is_file():
                    rel = rel_posix(item, root)
                    if not is_excluded(rel, excludes):
                        found[rel] = item
        return [found[key] for key in sorted(found)]

    return [
        path
        for path in sorted(root.rglob("*"))
        if path.is_file() and not is_excluded(rel_posix(path, root), excludes)
    ]


def collect_entries(root: Path, includes: list[str], excludes: list[str], include_binary: bool) -> tuple[list[dict[str, Any]], list[str]]:
    entries: list[dict[str, Any]] = []
    skipped: list[str] = []
    for path in iter_paths(root, includes, excludes):
        entry = entry_for(path, root, include_binary)
        if entry is None:
            skipped.append(rel_posix(path, root))
        else:
            entries.append(entry)
    return entries, skipped


def encoded_len(entry: dict[str, Any]) -> int:
    return len(json.dumps(entry, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def split_entries(entries: list[dict[str, Any]], max_files: int, max_bytes: int) -> list[list[dict[str, Any]]]:
    max_files = max(1, max_files)
    max_bytes = max(1024, max_bytes)
    parts: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_bytes = 0
    for entry in entries:
        size = encoded_len(entry)
        would_exceed_files = len(current) >= max_files
        would_exceed_bytes = current and current_bytes + size > max_bytes
        if would_exceed_files or would_exceed_bytes:
            parts.append(current)
            current = []
            current_bytes = 0
        current.append(entry)
        current_bytes += size
    if current:
        parts.append(current)
    return parts or [[]]


def write_json(path: Path, data: Any, force: bool) -> None:
    if path.exists() and not force:
        raise FileExistsError(f"output exists, use --force: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def csh_quote(path: str) -> str:
    return "'" + path.replace("'", "'\\''").replace("\\", "/") + "'"


def script_path() -> str:
    return str(Path(__file__).resolve()).replace("\\", "/")


def pack(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"not a directory: {root}", file=sys.stderr)
        return 2

    excludes = DEFAULT_EXCLUDES + list(args.exclude or [])
    try:
        entries, skipped = collect_entries(root, list(args.include or []), excludes, bool(args.include_binary))
    except (FileNotFoundError, ValueError) as err:
        print(str(err), file=sys.stderr)
        return 2

    output_dir = Path(args.output_dir).resolve()
    name = args.name
    parts = split_entries(entries, int(args.max_files), int(args.max_bytes))
    part_count = len(parts)
    bundle_id = f"{name}-{int(time.time())}-{sha256(str(root).encode('utf-8'))[:10]}"
    paths: list[Path] = []
    for index, part_entries in enumerate(parts, start=1):
        suffix = f".part{index:03d}-of{part_count:03d}.json" if part_count > 1 else ".json"
        out = output_dir / f"{name}{suffix}"
        bundle = {
            "format": BUNDLE_FORMAT,
            "version": BUNDLE_VERSION,
            "bundle_id": bundle_id,
            "root_name": root.name,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "part_index": index,
            "part_count": part_count,
            "file_count": len(part_entries),
            "total_file_count": len(entries),
            "files": part_entries,
        }
        try:
            write_json(out, bundle, bool(args.force))
        except FileExistsError as err:
            print(str(err), file=sys.stderr)
            return 2
        paths.append(out)

    if args.list:
        for item in entries:
            print(item["path"])
    restore_glob = str(output_dir / (f"{name}.part*.json" if part_count > 1 else f"{name}.json"))
    restore_cmd = (
        "set PACK_SCRIPT=/path/to/project_bundle.py\n"
        "set RESTORE_DIR=/path/to/restore_dir\n"
        f"foreach bundle ( {csh_quote(restore_glob)} )\n"
        "  python $PACK_SCRIPT restore $bundle $RESTORE_DIR -f\n"
        "end"
    )

    print(f"packed {len(entries)} files into {len(paths)} bundle part(s)")
    for path in paths:
        print(f"bundle: {path}")
    if skipped:
        print(f"skipped non-text files: {len(skipped)}")
    print("csh restore command:")
    print(restore_cmd)
    return 0


def safe_target(root: Path, rel: str) -> Path:
    if Path(rel).is_absolute():
        raise ValueError(f"unsafe absolute path in bundle: {rel}")
    target = (root / rel).resolve()
    root_resolved = root.resolve()
    if target != root_resolved and root_resolved not in target.parents:
        raise ValueError(f"unsafe path in bundle: {rel}")
    return target


def decode_entry(item: dict[str, Any]) -> bytes:
    encoding = item.get("encoding")
    if encoding == "base64":
        data = base64.b64decode(str(item["content"]).encode("ascii"))
    elif encoding in (None, "utf-8"):
        data = str(item["content"]).encode("utf-8")
    else:
        raise ValueError(f"unsupported entry encoding: {encoding}")
    expected = item.get("sha256")
    if expected and sha256(data) != expected:
        raise ValueError(f"checksum mismatch for {item.get('path', '<unknown>')}")
    return data


def bundle_entries(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    if bundle.get("files") is not None:
        return list(bundle.get("files", []))
    if bundle.get("items") is not None:
        return [{"path": item["path"], "encoding": "utf-8", "content": item["content"]} for item in bundle.get("items", [])]
    raise ValueError("bundle has neither files nor items")


def expand_bundle_args(values: list[str]) -> list[Path]:
    paths: list[Path] = []
    for raw in values:
        matches = sorted(glob.glob(raw)) if any(ch in raw for ch in "*?[]") else []
        if matches:
            paths.extend(Path(path).resolve() for path in matches)
        else:
            paths.append(Path(raw).resolve())
    return paths


def restore(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir).resolve()
    bundle_paths = expand_bundle_args(list(args.bundles or []))
    if not bundle_paths:
        print("restore requires at least one bundle JSON", file=sys.stderr)
        return 2
    output_dir.mkdir(parents=True, exist_ok=True)
    restored = 0
    seen: set[str] = set()
    try:
        for bundle_path in bundle_paths:
            bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
            if bundle.get("format") not in SUPPORTED_FORMATS:
                raise ValueError(f"unsupported bundle format: {bundle.get('format')}")
            for item in bundle_entries(bundle):
                rel = str(item["path"])
                target = safe_target(output_dir, rel)
                if rel in seen and not args.force:
                    raise ValueError(f"duplicate file across bundle parts: {rel}")
                if target.exists() and not args.force:
                    raise FileExistsError(f"exists, use --force: {target}")
                data = decode_entry(item)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                if "mode" in item:
                    try:
                        os.chmod(target, int(str(item.get("mode", "0o644")), 8))
                    except OSError:
                        pass
                seen.add(rel)
                restored += 1
    except (OSError, KeyError, ValueError, json.JSONDecodeError) as err:
        print(str(err), file=sys.stderr)
        return 2
    print(f"restored {restored} files into {output_dir}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Pack or restore project text files as split JSON bundles.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_pack = sub.add_parser("pack", help="pack a project into JSON bundle parts")
    p_pack.add_argument("--root", required=True, help="project root directory")
    p_pack.add_argument("--output-dir", required=True, help="directory for bundle parts")
    p_pack.add_argument("--name", default="project_scripts", help="bundle file prefix")
    p_pack.add_argument("--include", action="append", default=[], help="file or directory to include; repeatable")
    p_pack.add_argument("--exclude", action="append", default=[], help="extra fnmatch exclude pattern")
    p_pack.add_argument("--include-binary", action="store_true", help="include non-UTF8 files")
    p_pack.add_argument("--max-files", type=int, default=100, help="maximum files per JSON part")
    p_pack.add_argument("--max-bytes", type=int, default=500_000, help="approximate maximum payload bytes per JSON part")
    p_pack.add_argument("--force", action="store_true", help="overwrite existing bundle parts")
    p_pack.add_argument("--list", action="store_true", help="print included file paths")
    p_pack.set_defaults(func=pack)

    p_restore = sub.add_parser("restore", help="restore one or more JSON bundle parts")
    p_restore.add_argument("paths", nargs="+", help="bundle JSON files/globs; if --output-dir is omitted, the final positional argument is the output directory")
    p_restore.add_argument("--output-dir", default=None, help="restore target directory")
    p_restore.add_argument("-f", "--force", action="store_true", help="overwrite existing files")
    p_restore.set_defaults(func=restore)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "restore":
        if args.output_dir is None:
            if len(args.paths) < 2:
                parser.error("restore requires --output-dir or positional OUTPUT_DIR")
            args.output_dir = args.paths[-1]
            args.bundles = args.paths[:-1]
        else:
            args.bundles = args.paths
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
