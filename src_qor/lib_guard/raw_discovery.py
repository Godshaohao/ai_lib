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
    ".def": "DEF",
}
_IGNORED_DIRS = {
    ".git", ".svn", "__pycache__", "catalog", "diff", "reports", "release_area", "scan_out",
    "work", "tmp", "temp", "_simulation", "configs", "config", "hack_lef",
}
_IGNORED_PREFIXES = ("upstream_",)
_VERSION_NAME = re.compile(
    r"(?:\d{2,8}(?:[._-]\d+)*.*|\d{4}q[1-4].*|v\d+.*|r\d+.*|rev.*|beta.*|release.*|final.*|"
    r"stable.*|candidate.*|drop.*|update.*|build.*|snapshot.*|golden.*|tapeout.*)",
    re.IGNORECASE,
)
_MAX_DEPTH = 8
_MAX_DIRS = 5000
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


_VIEW_DIR_TYPES = {
    "lef": "LEF", "lib": "LIB", "db": "DB", "gds": "GDS", "oas": "OAS",
    "cdl": "CDL", "spice": "SPICE", "verilog": "VERILOG", "rtl": "VERILOG",
    "timing": "OTHER", "spef": "SPEF", "sdc": "SDC", "upf": "UPF",
    "cpf": "CPF", "nldm": "LIB", "ccs": "LIB", "ecsm": "LIB",
    "ccs_lvf": "LIB", "netlist": "VERILOG", "spi": "SPICE", "def": "DEF",
    "ndm": "NDM", "gdsii": "GDS",
}


def _dir_views_deep(path: Path, errors: list[dict[str, str]] | None = None) -> tuple[set[str], bool, bool]:
    """Find View folders and file suffixes through MAX_DEPTH, without following symlinks."""
    views: set[str] = set()
    queue: list[tuple[Path, int]] = [(path, 0)]
    visited_entries = 0
    truncated = False
    depth_limited = False
    while queue:
        current, depth = queue.pop(0)
        try:
            with os.scandir(current) as iterator:
                entries = sorted(iterator, key=lambda entry: entry.name.casefold())
            for entry in entries:
                visited_entries += 1
                if visited_entries > _HINT_ENTRIES:
                    truncated = True
                    queue.clear()
                    break
                if entry.is_dir(follow_symlinks=False):
                    if _ignored(entry.name):
                        continue
                    view = _VIEW_DIR_TYPES.get(entry.name.casefold())
                    if view:
                        views.add(view)
                    elif depth < _MAX_DEPTH:
                        queue.append((Path(entry.path), depth + 1))
                    else:
                        truncated = True
                        depth_limited = True
                elif entry.is_file(follow_symlinks=False):
                    suffix = Path(entry.name.lower()).suffix
                    if entry.name.casefold() not in {"readme", "license", "notice", "changelog"} \
                            and suffix not in {".md", ".txt", ".rst", ".pdf", ".html", ".htm"}:
                        views.add(_view_for_name(entry.name) or "OTHER")
        except OSError as exc:
            _record_access_error(errors, current, exc)
    return views, truncated, depth_limited


def _candidate(root: Path, relative_parts: tuple[str, ...], deliveries: list[dict[str, Any]],
               *, basis: str = "文件名后缀与直接子目录") -> dict[str, Any]:
    ordered = sorted(deliveries, key=lambda item: item["id"].casefold())
    views = sorted({view for item in ordered for view in item["views"]})
    return {
        "status": "REVIEW", "library_id": _library_id(relative_parts),
        "root_abs": str(root.resolve()), "root": str(root.resolve()),
        "display_name": relative_parts[-1], "library_name": relative_parts[-1],
        "vendor": relative_parts[0], "middle_path": "/".join(relative_parts[1:-1]),
        "version_count": len(ordered), "example_versions": [item["id"] for item in ordered[:5]],
        "confidence": 0.0, "reason": f"delivery_instances={len(ordered)};views={','.join(views)}",
        "view_types": views, "version_names": [item["id"] for item in ordered],
        "versions": ordered, "detection_basis": basis,
    }


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
        if depth == 2:
            relative = path.relative_to(root)
            versions = []
            named_versions = [child for child in _children(path, scan_errors)
                              if _VERSION_NAME.fullmatch(child.name)]
            if named_versions:
                for version in named_versions:
                    views, truncated, depth_limited = _dir_views_deep(version, scan_errors)
                    if truncated:
                        truncated_hints.append(str(version))
                    if depth_limited:
                        depth_limited_paths.append(str(version))
                    versions.append({
                        "id": version.name, "path": str(version.resolve()),
                        "views": sorted(views), "hints_truncated": truncated,
                        "detection_basis": "版本目录名与深层 View 扫描",
                    })
            else:
                direct_payload = False
                try:
                    with os.scandir(path) as iterator:
                        for entry in iterator:
                            if entry.is_dir(follow_symlinks=False):
                                direct_payload = entry.name.casefold() in _VIEW_DIR_TYPES
                            elif entry.is_file(follow_symlinks=False):
                                suffix = Path(entry.name.lower()).suffix
                                direct_payload = (
                                    entry.name.casefold() not in {"readme", "license", "notice", "changelog"}
                                    and suffix not in {".md", ".txt", ".rst", ".pdf", ".html", ".htm"}
                                )
                            if direct_payload:
                                break
                except OSError as exc:
                    _record_access_error(scan_errors, path, exc)
                views, truncated, depth_limited = _dir_views_deep(path, scan_errors) if direct_payload else (set(), False, False)
                if direct_payload and (views or not named_versions):
                    if truncated:
                        truncated_hints.append(str(path))
                    if depth_limited:
                        depth_limited_paths.append(str(path))
                    versions.append({
                        "id": path.name, "path": str(path.resolve()),
                        "views": sorted(views), "hints_truncated": truncated,
                        "detection_basis": "产品线目录自身交付",
                    })
            view_types = sorted({view for item in versions for view in item["views"]})
            if not versions or not view_types or view_types == ["OTHER"]:
                continue
            results.append(_candidate(path, relative.parts, versions,
                                      basis="Vendor/产品线与深层 View 目录"))
            continue
        if depth >= 2 or _ignored(path.name):
            continue
        for child in reversed(_children(path, scan_errors)):
            try:
                child.resolve().relative_to(root)
            except (OSError, ValueError):
                continue
            stack.append((child, depth + 1))
    if stack:
        depth_limited_paths.extend(str(path) for path, depth in stack if depth >= _MAX_DEPTH)

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
    """Find Vendor/product-line roots with named versions or a flat self-delivery."""
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
