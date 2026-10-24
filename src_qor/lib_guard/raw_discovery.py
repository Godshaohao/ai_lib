"""Read-only RAW inventory using the legacy Catalog/Discover tree semantics."""

from __future__ import annotations

import os
from collections import Counter
from pathlib import Path
import re
import json
from html import escape
from uuid import uuid4
from typing import Any


_VIEW_SUFFIXES = {
    ".lef": "LEF", ".lib": "LIB", ".db": "DB", ".gds": "GDS", ".oas": "OAS",
    ".cdl": "CDL", ".sp": "SPICE", ".spi": "SPICE", ".v": "VERILOG", ".sv": "VERILOG",
    ".sdc": "SDC", ".upf": "UPF", ".cpf": "CPF", ".spef": "SPEF", ".ndm": "NDM",
}
_IGNORED_DIRS = {
    ".git", ".svn", "__pycache__", "catalog", "diff", "reports", "release_area", "scan_out",
    "work", "tmp", "temp", "_simulation", "configs", "config",
}
_VIEW_DIR_NAMES = {
    "lef", "lib", "db", "gds", "oas", "cdl", "spice", "verilog", "rtl", "timing", "spef",
    "sdc", "upf", "cpf", "nldm", "ccs", "ecsm", "ccs_lvf",
}
_IGNORED_PREFIXES = ("upstream_",)
_VERSION_NAME = re.compile(
    r"(?:\d{2,8}(?:[._-]\d+)*.*|\d{4}q[1-4].*|v\d+.*|r\d+.*|rev.*|beta.*|release.*|final.*|"
    r"stable.*|candidate.*|drop.*|update.*|build.*|snapshot.*|golden.*|tapeout.*)",
    re.IGNORECASE,
)
_MAX_DEPTH = 8
_MAX_DIRS = 5000
_HINT_DEPTH = 4
_HINT_ENTRIES = 400


def _atomic_write(path: Path, content: str) -> None:
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _ignored(name: str) -> bool:
    lowered = name.lower()
    return lowered in _IGNORED_DIRS or lowered.startswith(_IGNORED_PREFIXES)


def _view_for_name(name: str) -> str | None:
    lowered = name.lower()
    if lowered.endswith(".gz"):
        lowered = lowered[:-3]
    return _VIEW_SUFFIXES.get(Path(lowered).suffix)


def _record_access_error(errors: list[dict[str, str]] | None, path: Path, error: OSError) -> None:
    if errors is None or any(item["path"] == str(path) for item in errors):
        return
    errors.append({"path": str(path), "error": str(error)})


def _children(path: Path, errors: list[dict[str, str]] | None = None) -> list[Path]:
    try:
        return sorted((child for child in path.iterdir()
                       if child.is_dir() and not child.is_symlink() and not _ignored(child.name)),
                      key=lambda item: item.name.casefold())
    except OSError as exc:
        _record_access_error(errors, path, exc)
        return []


def _view_hints(path: Path, errors: list[dict[str, str]] | None = None) -> tuple[set[str], bool]:
    """Inspect bounded filenames only; never follows directory symlinks."""
    views: set[str] = set()
    queue: list[tuple[Path, int]] = [(path, 0)]
    visited = 0
    while queue and visited < _HINT_ENTRIES:
        current, depth = queue.pop(0)
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    visited += 1
                    if visited > _HINT_ENTRIES:
                        break
                    if entry.is_dir(follow_symlinks=False):
                        if depth < _HINT_DEPTH and not _ignored(entry.name):
                            queue.append((Path(entry.path), depth + 1))
                    elif entry.is_file(follow_symlinks=False):
                        view = _view_for_name(entry.name)
                        if view:
                            views.add(view)
        except OSError as exc:
            _record_access_error(errors, current, exc)
            continue
    return views, bool(queue or visited >= _HINT_ENTRIES)


def _is_delivery(path: Path, errors: list[dict[str, str]] | None = None) -> tuple[bool, set[str], bool]:
    if _ignored(path.name) or path.name.lower() in _VIEW_DIR_NAMES:
        return False, set(), False
    children = _children(path, errors)
    # A named release container is not a version when it contains release directories.
    if not _VERSION_NAME.fullmatch(path.name) and any(_VERSION_NAME.fullmatch(item.name) for item in children):
        return False, set(), False
    hints, truncated = _view_hints(path, errors)
    return bool(hints), hints, truncated


def _library_id(relative_parts: tuple[str, ...]) -> str:
    parts = [re.sub(r"[^0-9A-Za-z_.-]+", "_", part).strip("._-") or "unknown" for part in relative_parts]
    return ".".join(parts)


def discover_raw_report(raw_root: str | Path) -> dict[str, Any]:
    """Find candidates and return the legacy Discover report model."""
    root = Path(raw_root).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"RAW 根目录不存在或不是目录：{root}")

    results: list[dict[str, Any]] = []
    truncated_hints: list[str] = []
    scan_errors: list[dict[str, str]] = []
    depth_limited_paths: list[str] = []
    stack: list[tuple[Path, int]] = [(root, 0)]
    visited = 0
    while stack and visited < _MAX_DIRS:
        path, depth = stack.pop()
        visited += 1
        if depth:
            relative = path.relative_to(root)
            is_top_vendor = len(relative.parts) == 1 and relative.parts[0].lower().startswith("vendor")
            if not is_top_vendor and not any(_VERSION_NAME.fullmatch(part) for part in relative.parts[:-1]):
                deliveries = []
                for child in _children(path, scan_errors):
                    is_delivery, views, hints_truncated = _is_delivery(child, scan_errors)
                    if hints_truncated:
                        truncated_hints.append(str(child))
                    if is_delivery and views:
                        deliveries.append({"id": child.name, "path": str(child.resolve()), "views": sorted(views),
                                           "hints_truncated": hints_truncated,
                                           "detection_basis": "文件名后缀与直接子目录"})
                if deliveries:
                    parts = relative.parts
                    vendor = parts[0]
                    library_name = parts[-1]
                    middle_path = "/".join(parts[1:-1])
                    library_id = _library_id(parts)
                    version_names = [item["id"] for item in sorted(deliveries, key=lambda item: item["id"].casefold())]
                    view_types = sorted({view for item in deliveries for view in item["views"]})
                    results.append({
                        "status": "REVIEW",
                        "library_id": library_id,
                        "root_abs": str(path.resolve()),
                        "root": str(path.resolve()),
                        "display_name": library_name,
                        "library_name": library_name,
                        "vendor": vendor,
                        "middle_path": middle_path,
                        "version_count": len(deliveries),
                        "example_versions": version_names[:5],
                        "confidence": 0.0,
                        "reason": f"delivery_instances={len(deliveries)};views={','.join(view_types)}",
                        "view_types": view_types,
                        "version_names": version_names,
                        "versions": sorted(deliveries, key=lambda item: item["id"].casefold()),
                    })
        if depth >= _MAX_DEPTH:
            if not _ignored(path.name) and not _VERSION_NAME.fullmatch(path.name):
                unvisited = [child for child in _children(path, scan_errors)
                             if child.name.lower() not in _VIEW_DIR_NAMES
                             and not _VERSION_NAME.fullmatch(child.name)]
                if unvisited:
                    depth_limited_paths.append(str(path))
            continue
        if _ignored(path.name) or _VERSION_NAME.fullmatch(path.name):
            continue
        for child in reversed(_children(path, scan_errors)):
            try:
                child.resolve().relative_to(root)
            except (OSError, ValueError):
                continue
            stack.append((child, depth + 1))

    candidate_paths = [Path(item["root_abs"]) for item in results]
    results = [item for item in results if not any(
        Path(item["root_abs"]) != other and Path(item["root_abs"]) in other.parents
        for other in candidate_paths
    )]
    results.sort(key=lambda item: (item["vendor"].casefold(), item["middle_path"].casefold(),
                                   item["display_name"].casefold(), item["root_abs"].casefold()))
    id_counts = Counter(item["library_id"] for item in results)
    identity_conflicts = sorted(key for key, count in id_counts.items() if count > 1)
    partial = bool(stack or truncated_hints or scan_errors or depth_limited_paths)
    warnings = []
    if stack:
        warnings.append(f"发现达到目录访问上限 {_MAX_DIRS}，结果可能不完整。")
    if scan_errors:
        warnings.append(f"有 {len(scan_errors)} 个目录访问失败，发现结果可能不完整。")
    if depth_limited_paths:
        warnings.append(f"有 {len(depth_limited_paths)} 个目录达到目录深度上限 {_MAX_DEPTH}，未继续检查其下级目录。")
    return {
        "raw_root": str(root),
        "start_root": str(root),
        "max_depth": _MAX_DEPTH,
        "min_versions": 1,
        "max_dirs": _MAX_DIRS,
        "max_candidates": None,
        "visited_dirs": visited,
        "truncated": bool(stack),
        "partial_discovery": partial,
        "truncated_hints": truncated_hints,
        "scan_errors": scan_errors,
        "depth_limited_paths": depth_limited_paths,
        "identity_conflicts": identity_conflicts,
        "warnings": warnings,
        "candidates": results,
    }


def discover_raw_libraries(raw_root: str | Path) -> list[dict[str, Any]]:
    """Find Catalog-style library roots at any depth under a RAW root.

    Candidate roots are directories with one or more direct delivery/version
    children. The relative path is retained as Vendor, middle_path and library;
    only filenames are inspected to summarize views.
    """
    return discover_raw_report(raw_root)["candidates"]


def write_discovery_artifacts(report: dict[str, Any], output_dir: str | Path, *,
                              include_human: bool = False,
                              human_formats: set[str] | None = None) -> dict[str, Path]:
    """Persist machine facts; create human exports only when explicitly requested."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / "library_discovery.json"
    artifacts = {"json": json_path}
    _atomic_write(json_path, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    formats = set(human_formats or ())
    if include_human:
        formats.update({"list", "html"})
    unsupported = formats - {"list", "html"}
    if unsupported:
        raise ValueError(f"不支持的人工导出格式：{', '.join(sorted(unsupported))}")
    if not formats:
        return artifacts

    columns = ("status", "library_id", "root_abs", "display_name", "vendor", "middle_path")
    if "list" in formats:
        list_path = out / "library.list"
        lines = [
            "# Candidate snapshot; REVIEW rows require operator confirmation.",
            "# RAW directories are read-only; this file does not modify the Catalog registry.",
            "\t".join(columns),
        ]
        for item in report["candidates"]:
            lines.append("\t".join(str(item.get(column) or "") for column in columns))
        _atomic_write(list_path, "\n".join(lines) + "\n")
        artifacts["list"] = list_path

    if "html" in formats:
        html_path = out / "library_discovery.html"
        rows = []
        for item in report["candidates"]:
            rows.append("<tr>" + "".join(
                f"<td>{escape(str(value))}</td>" for value in (
                    "待确认", item["library_id"], item["vendor"], item["middle_path"] or "—",
                    item["display_name"], item["root_abs"], item["version_count"],
                    ", ".join(item["version_names"]), "、".join(item["view_types"]),
                )
            ) + "</tr>")
        _atomic_write(html_path,
            "<!doctype html><html lang='zh-CN'><meta charset='utf-8'><title>RAW 库候选发现</title>"
            "<h1>RAW 库候选发现</h1><p>候选仅供确认，未自动登记或修改 RAW。</p>"
            "<table border='1' cellpadding='6'><thead><tr><th>状态</th><th>库标识</th><th>Vendor</th>"
            "<th>中间路径</th><th>显示名</th><th>库根目录</th><th>版本数</th><th>版本</th><th>View</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table></html>\n",
        )
        artifacts["html"] = html_path
    return artifacts
