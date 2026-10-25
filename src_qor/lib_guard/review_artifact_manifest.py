"""Build and verify a small, relocatable manifest for selected review artifacts."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path, PurePosixPath
import sys
from typing import Any, Iterable
from urllib.parse import unquote, urlsplit
from uuid import uuid4


MANIFEST_SCHEMA = "review_artifact_manifest.v1"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _review_record(root: Path, artifact: Path) -> dict[str, Any]:
    candidates = [artifact] if artifact.name == "review_result.json" else []
    candidates.extend(parent / "review_result.json" for parent in artifact.parents if parent != root.parent)
    for candidate in candidates:
        try:
            candidate.resolve().relative_to(root)
        except ValueError:
            continue
        if not candidate.is_file():
            continue
        try:
            value = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            return value
    return {}


def _role(path: str) -> str:
    lowered = path.casefold()
    if lowered.endswith("review_result.json"):
        return "review_result"
    if "/evidence/" in f"/{lowered}/" or lowered.endswith(".json"):
        return "evidence"
    if lowered.endswith(".xlsx"):
        return "workbook"
    if lowered.endswith(".html"):
        return "html_report"
    return "artifact"


def _relative_path(root: Path, value: str | Path) -> tuple[str, Path]:
    root = root.expanduser().resolve()
    candidate = Path(value).expanduser()
    if candidate.is_absolute():
        try:
            relative = Path(os.path.abspath(candidate)).relative_to(root)
        except ValueError as exc:
            raise ValueError(f"归档文件必须位于归档根目录内：{value}") from exc
    else:
        relative = candidate
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"清单路径必须是归档根目录内的相对路径：{value}")
    normalized = PurePosixPath(*relative.parts).as_posix()
    resolved = (root / Path(*relative.parts)).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"归档文件必须位于归档根目录内：{value}") from exc
    if not resolved.is_file():
        raise FileNotFoundError(f"归档文件不存在：{normalized}")
    return normalized, resolved


def build_manifest(root: str | Path, paths: Iterable[str | Path]) -> dict[str, Any]:
    """Describe only explicitly selected files; no directory walk is performed."""
    archive_root = Path(root).expanduser().resolve()
    if not archive_root.is_dir():
        raise NotADirectoryError(f"归档根目录不存在：{archive_root}")
    artifacts = []
    seen = set()
    for value in paths:
        relative, resolved = _relative_path(archive_root, value)
        if relative in seen:
            continue
        seen.add(relative)
        review = _review_record(archive_root, resolved)
        artifacts.append({
            "path": relative,
            "role": _role(relative),
            "size_bytes": resolved.stat().st_size,
            "sha256": _sha256(resolved),
            "library_id": str(review.get("library_id") or ""),
            "review_id": str(review.get("review_id") or ""),
            "source_revision": review.get("source_revision") or {},
        })
    if not artifacts:
        raise ValueError("归档清单至少需要一个显式选择的文件")
    return {
        "schema_version": MANIFEST_SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
    }


def write_manifest(root: str | Path, output: str | Path,
                   paths: Iterable[str | Path]) -> Path:
    archive_root = Path(root).expanduser().resolve()
    selected_paths = list(paths)
    manifest = build_manifest(archive_root, selected_paths)
    relative_output, output_path = _relative_path_for_output(archive_root, output)
    selected_targets = {
        _relative_path(archive_root, item["path"])[1]
        for item in manifest["artifacts"]
    }
    if relative_output in {item["path"] for item in manifest["artifacts"]} or output_path in selected_targets:
        raise ValueError("清单输出不能覆盖清单中的归档文件")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(f".{output_path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(output_path)
    finally:
        temporary.unlink(missing_ok=True)
    return output_path


def _relative_path_for_output(root: Path, value: str | Path) -> tuple[str, Path]:
    candidate = Path(value).expanduser()
    if candidate.is_absolute():
        try:
            relative = Path(os.path.abspath(candidate)).relative_to(root)
        except ValueError as exc:
            raise ValueError(f"清单输出必须位于归档根目录内：{value}") from exc
    else:
        relative = candidate
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"清单输出必须是归档根目录内的相对路径：{value}")
    if not relative.parts or relative == Path("."):
        raise ValueError(f"清单输出必须是归档根目录内的文件路径：{value}")
    if (root / Path(*relative.parts)).is_symlink():
        raise ValueError("清单输出不能是软链接")
    normalized = PurePosixPath(*relative.parts).as_posix()
    resolved = (root / Path(*relative.parts)).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"清单输出必须位于归档根目录内：{value}") from exc
    return normalized, resolved


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for name, value in attrs:
            if name.casefold() in {"href", "src"} and value:
                self.links.append(value)


def _html_link_errors(root: Path, html_path: Path, included_files: set[Path]) -> list[str]:
    try:
        parser = _LinkParser()
        parser.feed(html_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError):
        return [f"HTML 无法读取：{html_path.relative_to(root).as_posix()}"]
    errors = []
    for raw in parser.links:
        url = urlsplit(raw)
        scheme = url.scheme.casefold()
        if scheme == "file":
            errors.append(f"HTML 包含本机 file:// 链接不可迁移：{html_path.relative_to(root).as_posix()} -> {raw}")
            continue
        if scheme or url.netloc or not url.path or url.path.startswith(("data:", "javascript:")):
            continue
        linked = unquote(url.path)
        target = (root / linked.lstrip("/")) if linked.startswith("/") else (html_path.parent / linked)
        resolved = target.resolve()
        try:
            resolved.relative_to(root)
        except ValueError:
            errors.append(f"HTML 链接越出归档根目录：{html_path.relative_to(root).as_posix()} -> {raw}")
            continue
        if not resolved.exists():
            errors.append(f"HTML 链接目标缺失：{html_path.relative_to(root).as_posix()} -> {raw}")
            continue
        dependency = resolved / "index.html" if resolved.is_dir() else resolved
        if dependency not in included_files:
            errors.append(f"HTML 本地依赖未纳入归档清单：{html_path.relative_to(root).as_posix()} -> {raw}")
    return errors


def verify_manifest(root: str | Path, manifest_path: str | Path) -> dict[str, Any]:
    archive_root = Path(root).expanduser().resolve()
    manifest_file = Path(manifest_path).expanduser()
    if not manifest_file.is_absolute():
        manifest_file = archive_root / manifest_file
    try:
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return {"status": "INCOMPLETE", "checked_count": 0, "errors": [f"清单无法读取：{exc}"]}
    if (not isinstance(manifest, dict) or manifest.get("schema_version") != MANIFEST_SCHEMA
            or not isinstance(manifest.get("artifacts"), list)):
        return {"status": "INCOMPLETE", "checked_count": 0, "errors": ["清单结构或版本无效"]}
    errors = []
    if not manifest["artifacts"]:
        errors.append("清单至少包含一个文件记录")
    if manifest.get("artifact_count") != len(manifest["artifacts"]):
        errors.append("清单文件数量与 artifact_count 不一致")
    checked = 0
    html_paths = []
    included_files: set[Path] = set()
    seen_paths: set[str] = set()
    for item in manifest["artifacts"]:
        if not isinstance(item, dict):
            errors.append("清单包含无效文件记录")
            continue
        relative = str(item.get("path") or "")
        try:
            safe_relative, artifact = _relative_path(archive_root, relative)
        except (ValueError, FileNotFoundError) as exc:
            errors.append(str(exc))
            continue
        if safe_relative != relative:
            errors.append(f"清单路径格式无效：{relative}")
            continue
        if relative in seen_paths:
            errors.append(f"清单包含重复归档路径：{relative}")
            continue
        seen_paths.add(relative)
        digest = _sha256(artifact)
        size = artifact.stat().st_size
        if digest != str(item.get("sha256") or ""):
            errors.append(f"SHA-256 不匹配：{relative}")
        if size != item.get("size_bytes"):
            errors.append(f"文件大小不匹配：{relative}")
        checked += 1
        included_files.add(artifact)
        if relative.casefold().endswith(".html"):
            html_paths.append(artifact)
    for html_path in html_paths:
        errors.extend(_html_link_errors(archive_root, html_path, included_files))
    return {"status": "COMPLETE" if not errors else "INCOMPLETE",
            "checked_count": checked, "errors": errors}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="构建或验证可迁移的 IP 检查报告归档清单")
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build", help="为显式选择的报告文件生成清单")
    build.add_argument("--root", required=True, help="归档根目录")
    build.add_argument("--output", default="artifact_manifest.json", help="根目录内的清单输出路径")
    build.add_argument("paths", nargs="+", help="归档根目录内的相对文件路径")
    verify = subparsers.add_parser("verify", help="验证清单哈希与 HTML 相对链接")
    verify.add_argument("--root", required=True, help="归档根目录，可已移动到新位置")
    verify.add_argument("--manifest", default="artifact_manifest.json", help="清单相对路径")
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            path = write_manifest(args.root, args.output, args.paths)
            print(json.dumps({"status": "CREATED", "manifest": str(path)}, ensure_ascii=False))
            return 0
        result = verify_manifest(args.root, args.manifest)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["status"] == "COMPLETE" else 2
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
