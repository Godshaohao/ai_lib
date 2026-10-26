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
    "work", "tmp", "temp", "_simulation", "configs", "config",
}
_VIEW_DIR_NAMES = {
    "lef", "lib", "db", "gds", "oas", "cdl", "spice", "verilog", "rtl", "timing", "spef",
    "sdc", "upf", "cpf", "nldm", "ccs", "ecsm", "ccs_lvf", "netlist", "spi",
    "def", "ndm", "hack_lef",
}
_PACKAGING_DIR_NAMES = {"package", "source_package", "delivery_package", "release_package"}
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


def _direct_view_payload(path: Path, errors: list[dict[str, str]]) -> bool:
    """A version's own View files/directories, excluding nested Cell packages."""
    try:
        with os.scandir(path) as entries:
            return any(
                (entry.is_file(follow_symlinks=False) and _view_for_name(entry.name))
                or (entry.is_dir(follow_symlinks=False) and entry.name.lower() in _VIEW_DIR_NAMES)
                for entry in entries
            )
    except OSError as exc:
        _record_access_error(errors, path, exc)
        return False


def _cell_view_roots(version: Path, errors: list[dict[str, str]]) -> tuple[list[tuple[Path, set[str], bool]], bool]:
    """Find bounded Cell/View leaves below a release, without descending into Views."""
    roots: list[tuple[Path, set[str], bool]] = []
    queue: list[tuple[Path, int]] = [(version, 0)]
    visited = 0
    while queue and visited < _HINT_ENTRIES:
        path, depth = queue.pop(0)
        visited += 1
        if depth and _direct_view_payload(path, errors):
            views, truncated = _view_hints(path, errors)
            if views:
                roots.append((path, views, truncated))
            continue
        if depth < _HINT_DEPTH:
            queue.extend((child, depth + 1) for child in _children(path, errors)
                         if child.name.lower() not in _VIEW_DIR_NAMES)
    return roots, bool(queue)


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
        if depth:
            relative = path.relative_to(root)
            is_top_vendor = len(relative.parts) == 1 and relative.parts[0].lower().startswith("vendor")
            if (not is_top_vendor and not _VERSION_NAME.fullmatch(path.name)
                    and not any(_VERSION_NAME.fullmatch(part) for part in relative.parts[:-1])):
                deliveries = []
                cell_deliveries: dict[tuple[str, ...], list[dict[str, Any]]] = {}
                nested_by_version: dict[str, list[tuple[Path, set[str], bool]]] = {}
                for child in _children(path, scan_errors):
                    if _VERSION_NAME.fullmatch(child.name) and not _direct_view_payload(child, scan_errors):
                        nested, truncated = _cell_view_roots(child, scan_errors)
                        if truncated:
                            truncated_hints.append(str(child))
                        nested_by_version[child.name] = nested
                nested_names = Counter(
                    leaf.relative_to(path / version).as_posix()
                    for version, leaves in nested_by_version.items() for leaf, _, _ in leaves
                )
                for child in _children(path, scan_errors):
                    nested = nested_by_version.get(child.name, [])
                    # One packaging wrapper is ambiguous. Repeated Cell identities,
                    # deeper Cell paths, or multiple Cells establish this layout.
                    confirmed = [item for item in nested if (
                        item[0].name.lower() not in _PACKAGING_DIR_NAMES
                        and (len(nested) > 1 or len(item[0].relative_to(child).parts) > 1
                             or nested_names[item[0].relative_to(child).as_posix()] > 1)
                    )]
                    if confirmed:
                        for leaf, views, hints_truncated in confirmed:
                            key = leaf.relative_to(child).parts
                            cell_deliveries.setdefault(key, []).append({
                                "id": child.name, "path": str(leaf.resolve()), "views": sorted(views),
                                "hints_truncated": hints_truncated,
                                "detection_basis": "日期发布/Cell/View",
                            })
                        continue
                    is_delivery, views, hints_truncated = _is_delivery(child, scan_errors)
                    if hints_truncated:
                        truncated_hints.append(str(child))
                    if is_delivery and views:
                        deliveries.append({"id": child.name, "path": str(child.resolve()), "views": sorted(views),
                                           "hints_truncated": hints_truncated,
                                           "detection_basis": "文件名后缀与直接子目录"})
                if deliveries:
                    results.append(_candidate(path, relative.parts, deliveries))
                for cell_parts, versions in cell_deliveries.items():
                    results.append(_candidate(path, relative.parts + cell_parts, versions,
                                              basis="日期发布/Cell/View"))
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
