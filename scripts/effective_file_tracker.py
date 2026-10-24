#!/usr/bin/env python3
"""Read-only inventory of one selected formal NL stage for an IP."""

from __future__ import annotations

import argparse
from collections import Counter
import json
import os
import re
import sys
from pathlib import Path
from typing import Any


NL_VERSION_RE = re.compile(r"^lib_NL(?P<version>.+)$", re.IGNORECASE)
NUMBERS_RE = re.compile(r"\d+")
PROCESS_CORNER_RE = re.compile(
    r"(?:^|[_.-])(FFPG|SSPG|TTNOMINAL|FAST|SLOW|TYP|TT|SS|FF|SF|FS)(?=$|[_.-])",
    re.IGNORECASE,
)
RC_CORNER_RE = re.compile(r"(?:^|[_.-])(SIGRCMIN|SIGRCMAX)(?=$|[_.-])", re.IGNORECASE)
VIEW_DIRECTORIES = {
    "LEF": "lef", "LIB": "liberty", "LIBERTY": "liberty",
    "DB": "db", "GDS": "gds", "OAS": "oas", "OASIS": "oas",
    "VERILOG": "verilog", "RTL": "verilog", "CDL": "cdl",
    "SPICE": "spice", "SPEF": "spef", "SDF": "sdf", "NDM": "ndm",
    "NDM_WO_LIB": "ndm", "QRC": "qrc", "TECHNOLOGY": "technology",
}
VIEW_SUFFIXES = (
    (".lib.gz", "liberty"), (".lib", "liberty"), (".lef.gz", "lef"), (".lef", "lef"),
    (".gds", "gds"), (".gds.gz", "gds"), (".oas", "oas"),
    (".db", "db"), (".v", "verilog"), (".sv", "verilog"),
    (".cdl", "cdl"), (".spice.gz", "spice"), (".spice", "spice"),
    (".spi.gz", "spice"), (".spi", "spice"), (".sp.gz", "spice"), (".sp", "spice"),
)


def _version_from_path(path: Path) -> tuple[str, tuple[int, ...]] | None:
    for part in reversed(path.parts):
        match = NL_VERSION_RE.match(part)
        if not match:
            continue
        numbers = [int(value) for value in NUMBERS_RE.findall(match.group("version"))]
        if not numbers:
            return None
        if numbers[-1] >= 10000000 and len(str(numbers[-1])) == 8:
            numbers.pop()
        return part, tuple(numbers)
    return None


def _is_within_ip_target(target: Path, ip_name: str) -> bool:
    return ip_name in target.parts


def discover_formal_ip_links(
    formal_root: str | Path, ip_name: str, raw_root: str | Path | None = None,
) -> dict[str, Any]:
    """Find IP-directory links or NL view files sourced from the configured raw IP."""
    root = Path(formal_root).expanduser().resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"正式 NL 根目录不存在或不是目录：{root}")
    name = str(ip_name or "").strip()
    if not name or name in {".", ".."} or "/" in name or "\\" in name:
        raise ValueError("ip_directory_name 必须是单个目录名")

    candidates: list[dict[str, Any]] = []
    broken: list[str] = []
    flat_roots: list[Path] = []
    scoped_version = _version_from_path(root.parent) if root.name.upper() == "IP" else None
    formal_scope = "SINGLE_STAGE" if scoped_version is not None else "MULTI_STAGE_DISCOVERY"
    if scoped_version is not None and raw_root is not None:
        # A configured root may intentionally point at one package's IP view
        # tree rather than the parent that contains all lib_NL* packages.
        # Keep this scoped to the supplied raw IP root; a single such input
        # cannot establish which other NL package is newer or older.
        candidates.append({
            "link_path": str(root),
            "target_path": str(root),
            "nl_version": scoped_version[0],
            "layout": "FLAT_FILE_LINKS",
            "source_root": str(Path(raw_root).expanduser().resolve()),
            "_version_key": scoped_version[1],
        })
    else:
        for current, dirs, files in os.walk(root, followlinks=False):
            current_path = Path(current)
            if NL_VERSION_RE.match(current_path.name) and (current_path / "IP").is_dir():
                flat_roots.append(current_path)
            entries = [current_path / item for item in [*dirs, *files] if item == name]
            for entry in entries:
                if not entry.is_symlink():
                    continue
                try:
                    target = entry.resolve(strict=True)
                except (FileNotFoundError, OSError):
                    broken.append(str(entry))
                    continue
                if not target.is_dir() or not _is_within_ip_target(target, name):
                    continue
                version = _version_from_path(target)
                if version is None:
                    continue
                version_name, version_key = version
                candidates.append({
                    "link_path": str(entry),
                    "target_path": str(target),
                    "nl_version": version_name,
                    "layout": "IP_DIRECTORY_LINK",
                    "_version_key": version_key,
                })

    if raw_root is not None:
        source_root = Path(raw_root).expanduser().resolve()
        directory_link_versions = {item["nl_version"] for item in candidates}
        for version_root in flat_roots:
            version = _version_from_path(version_root)
            if version is None or version[0] in directory_link_versions:
                continue
            ip_directory = version_root / "IP"
            inventory = inventory_for_ip_target(ip_directory, source_root=source_root)
            if not inventory["files"]:
                continue
            candidates.append({
                "link_path": str(ip_directory),
                "target_path": str(ip_directory),
                "nl_version": version[0],
                "layout": "FLAT_FILE_LINKS",
                "source_root": str(source_root),
                "_version_key": version[1],
            })

    by_version: dict[str, dict[str, Any]] = {}
    ambiguous_versions: list[dict[str, Any]] = []
    for item in candidates:
        version = item["nl_version"]
        previous = by_version.get(version)
        if previous is None:
            by_version[version] = item
        elif previous["target_path"] != item["target_path"]:
            ambiguous_versions.append({
                "nl_version": version,
                "link_paths": sorted([previous["link_path"], item["link_path"]]),
                "target_paths": sorted([previous["target_path"], item["target_path"]]),
            })

    ambiguous_names = {item["nl_version"] for item in ambiguous_versions}
    ranked = [item for version, item in by_version.items() if version not in ambiguous_names]
    ranked.sort(key=lambda item: (item["_version_key"], item["nl_version"]), reverse=True)
    for index, item in enumerate(ranked):
        item["classification"] = (
            "SELECTED_STAGE" if formal_scope == "SINGLE_STAGE" else
            "LATEST" if index == 0 else "SECOND_LATEST" if index == 1 else "OLDER"
        )
        item.pop("_version_key", None)

    if ambiguous_versions:
        status = "AMBIGUOUS"
    elif ranked:
        status = "MATCHED"
    else:
        status = "NOT_FOUND"
    return {
        "schema_version": "formal_nl_ip_links.v5",
        "status": status,
        "formal_scope": formal_scope,
        "formal_nl_root": str(root),
        "ip_directory_name": name,
        "matches": ranked,
        "ambiguous_versions": ambiguous_versions,
        "broken_links": sorted(broken),
        "classification_note": (
            "正式 lib_NL 阶段目录名只用于标识所选阶段，不据此推断阶段新旧；原始版本的新旧候选按 library.root 下版本目录名的数字字段排序。"
            "单阶段报告比较原始最新与次新目录的文件路径清单，不读内容或 Hash；文件级链接只统计目标落在 library.root 内的文件。"
            "多阶段正式目录发现仅为兼容入口；链接存在不证明交付完整或当前有效。"
        ),
    }


def _view_for_path(relative: Path) -> str:
    name = relative.name.lower()
    for suffix, view in VIEW_SUFFIXES:
        if name.endswith(suffix):
            return view
    if name.startswith(("readme", "license", "copying")) or name.endswith(
        (".md", ".txt", ".tcl", ".json", ".yml", ".yaml", ".cfg", ".sdc", ".sh", ".csh")
    ):
        return "other"
    if len(relative.parts) > 1:
        view = next(
            (VIEW_DIRECTORIES.get(part.upper()) for part in relative.parts[:-1]
             if VIEW_DIRECTORIES.get(part.upper())),
            None,
        )
        if view:
            return view
    return "other"


def inventory_for_ip_target(
    target: str | Path, source_root: str | Path | None = None,
) -> dict[str, Any]:
    """List files through view links, optionally scoped to one raw IP root."""
    root = Path(target)
    source_prefix = Path(source_root).expanduser().resolve() if source_root is not None else None
    files: list[dict[str, str]] = []
    issues: list[dict[str, str]] = []
    ignored_outside_source_count = 0
    stack: list[tuple[Path, Path, frozenset[tuple[int, int]]]] = [(root, Path(), frozenset())]
    while stack:
        directory, relative_dir, ancestors = stack.pop()
        try:
            stat = directory.stat()
            identity = (stat.st_dev, stat.st_ino)
            if identity in ancestors:
                issues.append({"relative_path": relative_dir.as_posix(), "reason": "目录链接形成循环"})
                continue
            with os.scandir(directory) as entries:
                children = sorted(entries, key=lambda item: item.name, reverse=True)
        except OSError as exc:
            issues.append({"relative_path": relative_dir.as_posix(), "reason": str(exc)})
            continue
        lineage = ancestors | {identity}
        for entry in children:
            child = Path(entry.path)
            relative = relative_dir / entry.name
            try:
                if entry.is_dir(follow_symlinks=True):
                    stack.append((child, relative, lineage))
                elif entry.is_file(follow_symlinks=True):
                    source = child.resolve(strict=True)
                    if source_prefix is not None and not source.is_relative_to(source_prefix):
                        ignored_outside_source_count += 1
                        continue
                    files.append({
                        "relative_path": relative.as_posix(),
                        "view": _view_for_path(relative),
                        "source_path": str(source),
                        "published_path": str(root / relative),
                    })
                elif entry.is_symlink():
                    issues.append({"relative_path": relative.as_posix(), "reason": "链接目标不存在或不是普通文件/目录"})
            except OSError as exc:
                issues.append({"relative_path": relative.as_posix(), "reason": str(exc)})
    files.sort(key=lambda item: item["relative_path"])
    counts = Counter(item["view"] for item in files)
    return {
        "status": "INCOMPLETE" if issues else "COMPLETE",
        "target_path": str(root.resolve()),
        "file_count": len(files),
        "unique_source_count": len({item["source_path"] for item in files}),
        "ignored_outside_source_count": ignored_outside_source_count,
        "view_counts": dict(sorted(counts.items())),
        "files": files,
        "issues": sorted(issues, key=lambda item: item["relative_path"]),
    }


def _view_relative_key(relative_path: str, view: str) -> tuple[str, tuple[str, ...]]:
    """Normalize the path below a view directory, ignoring package wrappers."""
    parts = Path(relative_path).parts
    for index, part in enumerate(parts):
        if VIEW_DIRECTORIES.get(part.upper()) == view:
            return view, tuple(value.casefold() for value in parts[index + 1:])
    return view, tuple(value.casefold() for value in parts)


def _pair_side_record(file: dict[str, Any], *, version: str, root: str | Path,
                      formal: bool) -> dict[str, Any] | None:
    source_path = str(file.get("source_path") or "")
    if formal:
        try:
            source_relative = Path(source_path).resolve(strict=False).relative_to(
                Path(root).expanduser().resolve(strict=False)
            ).as_posix()
        except ValueError:
            return None
    else:
        source_relative = str(file.get("relative_path") or "")
        if not source_relative:
            return None
    view = str(file.get("view") or _view_for_path(Path(source_relative))).lower()
    record = {
        "view": view, "relative_path": str(file.get("relative_path") or ""),
        "source_relative_path": source_relative, "source_path": source_path,
        "raw_version": version, "match_key": _view_relative_key(source_relative, view),
    }
    if formal:
        record["published_path"] = str(file.get("published_path") or "")
    return record


def resolve_file_pairs(
    result: dict[str, Any], *, formal_version: str | None = None,
    raw_version: str | None = None,
) -> dict[str, Any]:
    """Pair new RAW files to formal RAW sources using paths only."""
    matches = result.get("matches") or []
    inventories = result.get("inventories") or {}
    raw = result.get("raw_library") or {}
    versions = {item.get("version_id"): item for item in raw.get("versions", [])}
    if formal_version is None:
        if result.get("formal_scope") != "SINGLE_STAGE" or len(matches) != 1:
            return {
                "schema_version": "formal_raw_file_pairs.v1", "status": "NEEDS_FORMAL_STAGE",
                "formal_stage_candidates": [item.get("nl_version") for item in matches],
                "raw_version": raw_version or (raw.get("version_candidates") or {}).get("latest"),
                "pairs": [], "basis": "只使用路径和文件名；不读取内容、不计算 Hash、不作放行判断",
            }
        formal_version = matches[0].get("nl_version")
    if formal_version not in inventories:
        return {
            "schema_version": "formal_raw_file_pairs.v1", "status": "FORMAL_STAGE_NOT_FOUND",
            "formal_stage": formal_version, "raw_version": raw_version,
            "pairs": [], "basis": "只使用路径和文件名；不读取内容、不计算 Hash、不作放行判断",
        }
    raw_version = raw_version or (raw.get("version_candidates") or {}).get("latest")
    raw_version_info = versions.get(raw_version)
    raw_inventory = (raw.get("inventories") or {}).get(raw_version)
    if raw_version_info is None or raw_inventory is None:
        return {
            "schema_version": "formal_raw_file_pairs.v1", "status": "RAW_VERSION_NOT_FOUND",
            "formal_stage": formal_version, "raw_version": raw_version,
            "available_raw_versions": sorted(value for value in versions if value),
            "pairs": [], "basis": "只使用路径和文件名；不读取内容、不计算 Hash、不作放行判断",
        }

    raw_root = raw_version_info.get("resolved_path") or raw_version_info.get("path")
    raw_version_roots = {
        key: item.get("resolved_path") or item.get("path")
        for key, item in versions.items() if key and (item.get("resolved_path") or item.get("path"))
    }
    formal_records = []
    unresolved_formal_source_count = 0
    for file in inventories[formal_version].get("files", []):
        owner = file.get("raw_version")
        owner_root = raw_version_roots.get(owner)
        if not owner_root:
            unresolved_formal_source_count += 1
            continue
        record = _pair_side_record(file, version=owner, root=owner_root, formal=True)
        if record is None:
            unresolved_formal_source_count += 1
        else:
            formal_records.append(record)
    raw_records = [
        record for file in raw_inventory.get("files", [])
        if (record := _pair_side_record(file, version=raw_version, root=raw_root, formal=False)) is not None
    ]

    formal_by_key: dict[tuple[str, tuple[str, ...]], list[dict[str, Any]]] = {}
    formal_by_name: dict[tuple[str, str], list[dict[str, Any]]] = {}
    raw_key_counts: Counter[tuple[str, tuple[str, ...]]] = Counter(item["match_key"] for item in raw_records)
    for item in formal_records:
        formal_by_key.setdefault(item["match_key"], []).append(item)
        formal_by_name.setdefault(
            (item["view"], Path(item["source_relative_path"]).name.casefold()), []
        ).append(item)

    pairs = []
    for item in raw_records:
        key = item["match_key"]
        exact = formal_by_key.get(key, [])
        if raw_key_counts[key] > 1 or len(exact) > 1:
            status, method, selected, candidates = "AMBIGUOUS", "VIEW_RELATIVE_PATH", None, exact
        elif len(exact) == 1:
            status, method, selected, candidates = "MATCHED", "VIEW_RELATIVE_PATH", exact[0], exact
        else:
            basename_key = (item["view"], Path(item["source_relative_path"]).name.casefold())
            candidates = formal_by_name.get(basename_key, [])
            if len(candidates) == 1:
                status, method, selected = "REVIEW_CANDIDATE", "VIEW_AND_BASENAME_CANDIDATE", None
            elif candidates:
                status, method, selected = "AMBIGUOUS", "VIEW_AND_BASENAME_CANDIDATE", None
            else:
                status, method, selected = "UNMATCHED", "NONE", None
        pairs.append({
            "status": status, "match_method": method,
            "raw_file": {key: value for key, value in item.items() if key != "match_key"},
            "formal_source": ({key: value for key, value in selected.items() if key != "match_key"}
                              if selected else None),
            "candidates": [
                {key: value for key, value in candidate.items() if key != "match_key"}
                for candidate in candidates
            ],
        })
    counts = Counter(item["status"] for item in pairs)
    return {
        "schema_version": "formal_raw_file_pairs.v1",
        "status": "COMPLETE" if raw_inventory.get("status") == "COMPLETE"
                  and inventories[formal_version].get("status") == "COMPLETE" else "INCOMPLETE",
        "formal_stage": formal_version, "raw_version": raw_version,
        "summary": {
            "new_raw_file_count": len(pairs), "matched": counts["MATCHED"],
            "review_candidate": counts["REVIEW_CANDIDATE"], "ambiguous": counts["AMBIGUOUS"],
            "unmatched": counts["UNMATCHED"],
            "formal_sources_without_raw_origin": unresolved_formal_source_count,
        },
        "basis": "View 目录下相对路径唯一匹配；同 View 同名仅作为人工复核候选。不读取内容、不计算 Hash、不作放行判断",
        "pairs": pairs,
    }


def build_candidate_filemap(
    raw_library: dict[str, Any], package_metadata: dict[str, dict[str, Any]],
    candidate_version: str, *, explicit_deletions: dict[str, list[str]] | None = None,
    explicit_resets: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Build a read-only cumulative file map from confirmed Catalog ancestry."""
    inventories = raw_library.get("inventories") or {}
    deletions = explicit_deletions or {}
    resets = explicit_resets or {}
    chain: list[str] = []
    visited: set[str] = set()
    current = candidate_version
    supported_overlays = {"PARTIAL_UPDATE", "HOTFIX", "DOC_UPDATE", "DOC_ONLY"}

    def failed(status: str, message: str) -> dict[str, Any]:
        return {
            "schema_version": "candidate_filemap.v1", "status": status,
            "candidate_version": candidate_version, "chain": list(reversed(chain)),
            "files": [], "changes": [], "operations": {}, "message": message,
            "basis": "仅使用 Catalog 包类型、前序关系和路径；不读文件内容、不计算 Hash、不作放行判断",
        }

    while current:
        if current in visited:
            return failed("ANCESTRY_CYCLE", f"Catalog 前序关系形成循环：{current}")
        visited.add(current)
        metadata = package_metadata.get(current)
        if metadata is None:
            return failed("PACKAGE_METADATA_NOT_FOUND", f"Catalog 未提供版本 {current} 的包元数据")
        package_type = str(metadata.get("package_type") or "UNKNOWN_PACKAGE").upper()
        if package_type == "FULL_PACKAGE":
            chain.append(current)
            break
        if package_type not in supported_overlays:
            return failed("PACKAGE_TYPE_UNCONFIRMED", f"版本 {current} 的包类型未确认：{package_type}")
        previous = str(metadata.get("previous_effective_version") or "").strip()
        if not previous:
            chain.append(current)
            return failed("NEEDS_CONFIRMED_BASE", f"增量版本 {current} 没有 Catalog 前序有效版本，不能推断叠加顺序")
        chain.append(current)
        current = previous
    if not chain:
        return failed("PACKAGE_METADATA_NOT_FOUND", f"找不到候选版本 {candidate_version}")
    chain.reverse()
    full_base = chain[0]
    for version in chain[1:]:
        declared_base = str(package_metadata[version].get("base_full_version") or "").strip()
        if declared_base and declared_base != full_base:
            return failed("BASE_FULL_MISMATCH",
                          f"增量版本 {version} 声明基线 {declared_base}，依赖链的 FULL 基线为 {full_base}")

    filemap: dict[tuple[str, tuple[str, ...]], dict[str, Any]] = {}
    changes: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    for version in chain:
        inventory = inventories.get(version)
        if not inventory or inventory.get("status") != "COMPLETE":
            return failed("INVENTORY_INCOMPLETE", f"版本 {version} 的 RAW 文件清单不完整")
        metadata = package_metadata[version]
        package_type = str(metadata.get("package_type") or "UNKNOWN_PACKAGE").upper()
        if package_type == "FULL_PACKAGE":
            if version != chain[0]:
                return failed("MULTIPLE_FULL_BASES", "同一叠加链包含多个 FULL 基线")
            filemap.clear()
            changes.append({"version": version, "operation": "RESET", "reason": "FULL_PACKAGE 建立完整基线"})
            counts["RESET"] += 1
        else:
            declared_views = {str(value).strip().casefold() for value in resets.get(version, []) if str(value).strip()}
            unsupported_views = declared_views - set(VIEW_DIRECTORIES.values()) - {"other"}
            if unsupported_views:
                return failed("RESET_VIEW_UNSUPPORTED", f"版本 {version} 声明了未知 View：{', '.join(sorted(unsupported_views))}")
            for view in sorted(declared_views):
                filemap = {key: value for key, value in filemap.items() if key[0] != view}
                changes.append({"version": version, "operation": "RESET", "view": view})
                counts["RESET"] += 1

        files = inventory.get("files") or []
        records: dict[tuple[str, tuple[str, ...]], dict[str, Any]] = {}
        for source in files:
            view = str(source.get("view") or _view_for_path(Path(source.get("relative_path") or "")))
            relative_path = str(source.get("relative_path") or "")
            key = _view_relative_key(relative_path, view)
            if not relative_path or key in records:
                return failed("AMBIGUOUS_PACKAGE_FILES", f"版本 {version} 在同一规范化路径下存在重复文件")
            records[key] = {"view": view, "relative_path": relative_path,
                            "source_path": str(source.get("source_path") or ""),
                            "source_version": version, "identity_path": "/".join((view, *key[1]))}
        for key, record in sorted(records.items(), key=lambda item: item[1]["identity_path"]):
            previous = filemap.get(key)
            operation = "REPLACE" if previous else "ADD"
            filemap[key] = {**record, "operation": operation,
                            "replaces": ({"source_version": previous["source_version"],
                                          "relative_path": previous["relative_path"]} if previous else None)}
            changes.append({"version": version, "operation": operation,
                            "identity_path": record["identity_path"],
                            "old_source_version": previous["source_version"] if previous else None,
                            "new_source_version": version})
            counts[operation] += 1

        for removed_path in deletions.get(version, []):
            path = Path(str(removed_path))
            view = _view_for_path(path)
            key = _view_relative_key(path.as_posix(), view)
            previous = filemap.pop(key, None)
            if previous is None:
                return failed("DELETE_TARGET_NOT_FOUND", f"版本 {version} 声明删除了候选集合中不存在的文件：{removed_path}")
            changes.append({"version": version, "operation": "DELETE",
                            "identity_path": previous["identity_path"],
                            "old_source_version": previous["source_version"],
                            "old_relative_path": previous["relative_path"]})
            counts["DELETE"] += 1

    return {
        "schema_version": "candidate_filemap.v1", "status": "COMPLETE",
        "candidate_version": candidate_version, "chain": chain,
        "selection_basis": "FULL 包类型 + previous_effective_version 显式关系；不按目录名推断增量叠加顺序",
        "files": sorted(({
            **item,
            "candidate_operation": "KEEP" if item["source_version"] != candidate_version else item["operation"],
        } for item in filemap.values()), key=lambda item: item["identity_path"]),
        "changes": changes,
        "version_transitions": [
            {"version": version, "operations": dict(sorted(Counter(
                item["operation"] for item in changes if item.get("version") == version
            ).items()))}
            for version in chain
        ],
        "operations": {key.lower(): value for key, value in sorted(counts.items())},
        "basis": "只描述候选文件来源与路径更新关系，不代表文件内容变化或候选已被接受",
    }


def compare_formal_to_filemap(
    formal_inventory: dict[str, Any], candidate_filemap: dict[str, Any],
) -> dict[str, Any]:
    """Compare visible formal sources to a complete cumulative candidate set."""
    if candidate_filemap.get("status") != "COMPLETE" or formal_inventory.get("status") != "COMPLETE":
        return {"status": "INCOMPLETE", "changes": [], "counts": {}}
    formal_by_key: dict[tuple[str, tuple[str, ...]], list[dict[str, Any]]] = {}
    candidate_by_key: dict[tuple[str, tuple[str, ...]], list[dict[str, Any]]] = {}
    for item in formal_inventory.get("files", []):
        view = str(item.get("view") or "other")
        key = _view_relative_key(str(item.get("relative_path") or ""), view)
        formal_by_key.setdefault(key, []).append(item)
    for item in candidate_filemap.get("files", []):
        view = str(item.get("view") or "other")
        key = _view_relative_key(str(item.get("relative_path") or ""), view)
        candidate_by_key.setdefault(key, []).append(item)
    changes: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    for key in sorted(formal_by_key.keys() | candidate_by_key.keys()):
        old_items, new_items = formal_by_key.get(key, []), candidate_by_key.get(key, [])
        if len(old_items) > 1 or len(new_items) > 1:
            operation = "UNRESOLVED"
        elif not old_items:
            operation = "ADD"
        elif not new_items:
            operation = "DELETE"
        else:
            old_source = str(old_items[0].get("source_path") or "")
            new_source = str(new_items[0].get("source_path") or "")
            operation = "KEEP" if old_source and old_source == new_source else "REPLACE"
        counts[operation] += 1
        old = old_items[0] if len(old_items) == 1 else None
        new = new_items[0] if len(new_items) == 1 else None
        changes.append({
            "operation": operation, "identity_path": "/".join((key[0], *key[1])),
            "formal_raw_version": old.get("raw_version") if old else None,
            "candidate_raw_version": new.get("source_version") if new else None,
            "formal_source_path": old.get("source_path") if old else None,
            "candidate_source_path": new.get("source_path") if new else None,
        })
    return {"status": "COMPLETE", "counts": dict(sorted(counts.items())), "changes": changes,
            "basis": "正式链接来源与累积候选按同一 View 下相对路径匹配；不表示文件内容已比较"}


def _catalog_package_metadata(
    catalog_path: Path, library_config: dict[str, Any], raw_versions: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    libraries = catalog.get("libraries") or []
    identifiers = {
        str(library_config.get(key) or "").strip()
        for key in ("id", "library_id", "library_name", "formal_library_id", "ip_directory_name")
    } - {""}
    raw_root = str(Path(str(library_config.get("root") or "")).expanduser().resolve())
    matching = [item for item in libraries if identifiers.intersection({
        str(item.get(key) or "").strip()
        for key in ("library_id", "typed_library_id", "library_name", "formal_library_id")
    })]
    if not matching:
        matching = [item for item in libraries if str(item.get("library_root") or "").strip() == raw_root]
    if len(matching) != 1:
        raise ValueError(f"Catalog 中按库标识/根目录找到 {len(matching)} 个候选库，必须唯一：{catalog_path}")

    by_path: dict[str, list[dict[str, Any]]] = {}
    by_id: dict[str, list[dict[str, Any]]] = {}
    for item in matching[0].get("versions", []):
        version_path = item.get("raw_path") or item.get("version_path")
        if version_path:
            by_path.setdefault(str(Path(version_path).expanduser().resolve()), []).append(item)
        version_id = str(item.get("version_id") or "")
        if version_id:
            by_id.setdefault(version_id, []).append(item)
    metadata: dict[str, dict[str, Any]] = {}
    for raw in raw_versions:
        version_id = str(raw.get("version_id") or "")
        path = str(Path(raw.get("resolved_path") or raw.get("path") or "").resolve())
        records = by_path.get(path) or by_id.get(version_id, [])
        if len(records) == 1:
            metadata[version_id] = records[0]
    return metadata


def _candidate_filemap_markdown(filemap: dict[str, Any], formal_comparison: dict[str, Any]) -> list[str]:
    lines = ["## 正式文件与候选文件集合", ""]
    if filemap.get("status") == "NOT_CONFIGURED":
        lines.append("未配置 Catalog，无法取得已确认的 FULL/FIX 包类型与叠加关系；不生成累积候选文件集合。")
        return lines
    lines.append(f"候选版本：`{_md(filemap.get('candidate_version', ''))}`；叠加链："
                 f"{' → '.join(f'`{_md(item)}`' for item in filemap.get('chain', [])) or '未建立'}。")
    if filemap.get("status") != "COMPLETE":
        lines.append(f"候选文件集合未生成：{_md(filemap.get('status'))}。{_md(filemap.get('message', ''))}")
        lines.append("不会按版本目录名猜测增量次序；未知包类型、缺少基线或清单不完整时停止累积。")
        return lines
    totals = formal_comparison.get("counts") or {}
    lines.append("与当前正式链接来源的路径级结果：" + "、".join(
        f"{name} {count}" for name, count in totals.items()) + "。" if totals else "与当前正式目录的配对比较未完成。")
    lines.append("ADD/REPLACE/DELETE 只表示文件集合和来源关系；不代表内容差异、兼容性或发布结论。")
    lines.extend(["", "| 操作 | View 内路径 | 正式来源版本 | 候选来源版本 |", "| --- | --- | --- | --- |"])
    for item in formal_comparison.get("changes", [])[:100]:
        if item["operation"] == "KEEP":
            continue
        lines.append(f"| {item['operation']} | `{_md(item['identity_path'])}` | "
                     f"{_md(item.get('formal_raw_version') or '—')} | {_md(item.get('candidate_raw_version') or '—')} |")
    if len(formal_comparison.get("changes", [])) > 100:
        lines.append("其余记录见 JSON 的 `formal_candidate_comparison.changes`。")
    lines.extend(["", "候选文件集合（按来源版本汇总；最多显示 100 条）：", "",
                  "| 候选文件 | 来源 RAW | 相对前序包的关系 |", "| --- | --- | --- |"])
    for item in filemap.get("files", [])[:100]:
        operation = item.get("candidate_operation") or item.get("operation")
        replaced = item.get("replaces") or {}
        relation = (f"替换 {replaced.get('source_version')}" if operation == "REPLACE" and replaced
                    else "继承保留" if operation == "KEEP" else "新增")
        lines.append(f"| `{_md(item.get('identity_path', ''))}` | {_md(item.get('source_version', ''))} | {relation} |")
    if len(filemap.get("files", [])) > 100:
        lines.append(f"候选集合共 {len(filemap['files'])} 条，其余完整文件映射见 JSON 的 `candidate_filemap.files`。")
    return lines


def add_delivery_evidence(result: dict[str, Any]) -> None:
    """Attach inventories and path/source comparison for two unambiguous versions."""
    result["inventories"] = {}
    result["chart_data"] = {
        "version_file_counts": [], "view_counts": [],
        "transition_counts": [], "view_transition_counts": [],
        "candidate_operation_counts": [], "formal_candidate_operation_counts": [],
    }
    result["chart_data_meta"] = {
        "version_file_counts": {"unit": "正式目录可见文件路径；另列去重来源路径", "scope": "按本次指定阶段统计"},
        "view_counts": {"unit": "正式目录可见文件路径", "scope": "按指定阶段和 view 分组"},
        "transition_counts": {"unit": "正式目录相对文件路径", "scope": "仅兼容多阶段目录输入时生成；source_updated 只表示链接目标路径不同"},
        "view_transition_counts": {"unit": "正式目录相对文件路径", "scope": "仅兼容多阶段目录输入时生成；不判断文件内容变化"},
        "raw_version_file_counts": {"unit": "原始目录可见文件路径；未盘点用 null，不是零", "scope": "列出并盘点 library.root 下全部直接子版本目录"},
        "raw_view_counts": {"unit": "原始目录可见文件路径", "scope": "仅已盘点的原始版本，按 raw_version 和 view 分组"},
        "formal_source_mix": {"unit": "正式目录可见文件路径", "scope": "按指定阶段与原始版本分组"},
        "formal_source_views": {"unit": "正式目录可见文件路径", "scope": "按 nl_version、raw_version 和 view 分组"},
        "raw_formal_view_coverage": {"unit": "去重后的原始文件来源路径", "scope": "本次指定正式阶段引用的原始版本，按 raw_version 和 view 分组"},
        "candidate_operation_counts": {"unit": "候选文件路径记录数", "scope": "由明确 Catalog 前序链累积的 ADD/REPLACE/DELETE/RESET 操作"},
        "formal_candidate_operation_counts": {"unit": "正式相对路径记录数", "scope": "正式文件集合与累积候选集合的路径级操作"},
    }
    if result["status"] != "MATCHED":
        result["comparison"] = {"status": result["status"], "counts": {}, "changes": []}
        return
    selected = result["matches"][:2]
    for match in selected:
        inventory = inventory_for_ip_target(match["target_path"], source_root=match.get("source_root"))
        version = match["nl_version"]
        result["inventories"][version] = inventory
        if (result.get("formal_scope") == "SINGLE_STAGE"
                and not inventory["files"] and not inventory["issues"]):
            result["status"] = "NOT_FOUND"
        match["inventory_status"] = inventory["status"]
        match["file_count"] = inventory["file_count"]
        match["unique_source_count"] = inventory["unique_source_count"]
        match["view_counts"] = inventory["view_counts"]
        result["chart_data"]["version_file_counts"].append({
            "nl_version": version, "classification": match["classification"],
            "file_count": inventory["file_count"], "inventory_status": inventory["status"],
            "unique_source_count": inventory["unique_source_count"],
        })
        for view, count in inventory["view_counts"].items():
            result["chart_data"]["view_counts"].append({
                "nl_version": version, "view": view, "file_count": count,
            })
    if result.get("formal_scope") == "SINGLE_STAGE":
        result["comparison"] = {"status": "NOT_REQUESTED", "counts": {}, "changes": []}
        return
    if len(selected) < 2:
        result["comparison"] = {"status": "NO_SECOND_VERSION", "counts": {}, "changes": []}
        return
    new_version, old_version = (item["nl_version"] for item in selected)
    new_inventory = result["inventories"][new_version]
    old_inventory = result["inventories"][old_version]
    if any(item["status"] != "COMPLETE" for item in (new_inventory, old_inventory)):
        result["comparison"] = {
            "status": "INCOMPLETE", "old_version": old_version,
            "new_version": new_version, "counts": {}, "changes": [],
        }
        return
    new_files = {item["relative_path"]: item for item in new_inventory["files"]}
    old_files = {item["relative_path"]: item for item in old_inventory["files"]}
    counts = dict.fromkeys(("added", "removed", "source_updated", "same_source"), 0)
    view_transitions: Counter[tuple[str, str]] = Counter()
    changes: list[dict[str, str]] = []
    for path in sorted(new_files.keys() | old_files.keys()):
        old, new = old_files.get(path), new_files.get(path)
        kind = ("added" if old is None else "removed" if new is None else
                "same_source" if old["source_path"] == new["source_path"] else "source_updated")
        counts[kind] += 1
        view_transitions[((new or old)["view"], kind)] += 1
        if kind != "same_source":
            changes.append({
                "relative_path": path, "view": (new or old)["view"],
                "change": kind, "old_source_path": old["source_path"] if old else "",
                "new_source_path": new["source_path"] if new else "",
            })
    result["comparison"] = {
        "status": "COMPLETE", "old_version": old_version, "new_version": new_version,
        "counts": counts, "changes": changes,
        "comparison_basis": "相对路径与解析后的来源路径；不读取文件内容",
    }
    result["chart_data"]["transition_counts"] = [
        {"old_version": old_version, "new_version": new_version, "change": kind, "file_count": count}
        for kind, count in counts.items()
    ]
    result["chart_data"]["view_transition_counts"] = [
        {"old_version": old_version, "new_version": new_version,
         "view": view, "change": kind, "file_count": count}
        for (view, kind), count in sorted(view_transitions.items())
    ]


def add_filename_coverage(result: dict[str, Any]) -> None:
    """Summarize published LIB/DB names without treating names as content evidence."""
    result["filename_coverage"] = {}
    suffixes = {"liberty": (".lib.gz", ".lib"), "db": (".db",)}
    for version, inventory in result.get("inventories", {}).items():
        rows: list[dict[str, str]] = []
        groups: dict[str, dict[str, list[str]]] = {}
        corner_counts: dict[str, Counter[str]] = {"liberty": Counter(), "db": Counter()}
        rc_corner_counts: dict[str, Counter[str]] = {"liberty": Counter(), "db": Counter()}
        for file in inventory["files"]:
            view = file["view"]
            if view not in suffixes:
                continue
            name = Path(file["relative_path"]).name
            lowered = name.lower()
            suffix = next((item for item in suffixes[view] if lowered.endswith(item)), None)
            if suffix is None:
                continue
            stem = name[:-len(suffix)]
            labels = sorted({match.group(1).upper() for match in PROCESS_CORNER_RE.finditer(stem)})
            corner = labels[0] if len(labels) == 1 else "标签冲突" if labels else "未识别"
            rc_labels = sorted({match.group(1).upper() for match in RC_CORNER_RE.finditer(stem)})
            rc_corner = rc_labels[0] if len(rc_labels) == 1 else "标签冲突" if rc_labels else "未标注"
            key = stem.lower()
            rows.append({"view": view, "relative_path": file["relative_path"],
                         "source_path": file["source_path"], "pair_key": key,
                         "corner_label": corner, "rc_corner_label": rc_corner})
            corner_counts[view][corner] += 1
            rc_corner_counts[view][rc_corner] += 1
            groups.setdefault(key, {"liberty": [], "db": []})[view].append(file["relative_path"])
        pairs = []
        for key, paths in sorted(groups.items()):
            libs, dbs = sorted(paths["liberty"]), sorted(paths["db"])
            status = ("AMBIGUOUS" if len(libs) > 1 or len(dbs) > 1 else
                      "PAIRED" if libs and dbs else "LIB_ONLY" if libs else "DB_ONLY")
            pairs.append({"key": key, "status": status, "liberty_files": libs, "db_files": dbs})
        result["filename_coverage"][version] = {
            "basis": "正式目录可见链接名；LIB/DB 仅按去扩展名后的完整文件名配对，不读取内容",
            "corner_counts": {view: dict(sorted(counts.items())) for view, counts in corner_counts.items()},
            "rc_corner_counts": {view: dict(sorted(counts.items())) for view, counts in rc_corner_counts.items()},
            "files": sorted(rows, key=lambda row: row["relative_path"]),
            "lib_db_pairs": pairs,
        }


def add_raw_library_evidence(result: dict[str, Any], raw_root: str | Path | None) -> None:
    """Correlate formal file sources with direct child versions of one raw IP root."""
    result["chart_data"].update({
        "raw_version_file_counts": [], "raw_view_counts": [],
        "formal_source_mix": [], "formal_source_views": [],
        "raw_formal_view_coverage": [], "raw_version_comparison": [],
        "candidate_operation_counts": [], "formal_candidate_operation_counts": [],
    })
    result["formal_sources"] = {}
    if raw_root is None:
        result["raw_library"] = {
            "status": "NOT_CONFIGURED", "root_path": "", "version_count": 0,
            "versions": [], "inventories": {}, "formal_coverage": {},
            "version_candidates": {"latest": None, "next_latest": None},
        "comparison": {"status": "NOT_AVAILABLE"}, "version_evolution": [],
            "issues": ["未配置 library.root"],
        }
        return
    root = Path(raw_root).expanduser().resolve()
    raw: dict[str, Any] = {
        "status": "COMPLETE", "root_path": str(root), "version_count": 0,
        "versions": [], "inventories": {}, "formal_coverage": {},
        "version_candidates": {"latest": None, "next_latest": None},
        "comparison": {"status": "NOT_AVAILABLE"}, "version_evolution": [], "issues": [],
    }
    result["raw_library"] = raw
    if not root.is_dir():
        raw["status"] = "ROOT_NOT_FOUND"
        raw["issues"].append(f"原始库根目录不存在或不是目录：{root}")
        return
    try:
        children = sorted((path for path in root.iterdir() if path.is_dir()), key=lambda path: path.name)
    except OSError as exc:
        raw["status"] = "INCOMPLETE"
        raw["issues"].append(f"无法读取原始版本目录：{exc}")
        return
    if not children:
        raw["status"] = "EMPTY"
        raw["issues"].append("原始库根目录下没有直接子版本目录")
        return
    children.sort(key=lambda path: _raw_version_sort_key(path.name), reverse=True)
    raw["versions"] = [
        {"version_id": path.name, "path": str(path), "resolved_path": str(path.resolve()),
         "inventory_status": "NOT_SCANNED"}
        for path in children
    ]
    raw["version_count"] = len(children)
    candidates = [path.name for path in children[:2]]
    raw["version_candidates"] = {
        "ordering_basis": "原始版本目录名中的数字字段，自然降序；不使用正式 NL 阶段编号",
        "latest": candidates[0] if candidates else None,
        "next_latest": candidates[1] if len(candidates) > 1 else None,
    }
    referenced: set[str] = set()
    for match in result.get("matches", [])[:2]:
        version = match["nl_version"]
        inventory = result["inventories"][version]
        counts: Counter[str] = Counter()
        unique_sources: dict[str, set[str]] = {}
        unmapped: list[dict[str, str]] = []
        view_mix: Counter[tuple[str, str]] = Counter()
        for file in inventory["files"]:
            source = Path(file["source_path"])
            owners = []
            for candidate in raw["versions"]:
                try:
                    source.relative_to(candidate["resolved_path"])
                except ValueError:
                    continue
                owners.append(candidate["version_id"])
            if len(owners) == 1:
                owner = owners[0]
                file["raw_version"] = owner
                referenced.add(owner)
                counts[owner] += 1
                unique_sources.setdefault(owner, set()).add(file["source_path"])
                view_mix[(owner, file["view"])] += 1
            else:
                file["raw_version"] = None
                unmapped.append({"relative_path": file["relative_path"],
                                 "source_path": file["source_path"],
                                 "reason": "多个版本路径匹配" if owners else "来源不在原始版本目录下"})
        result["formal_sources"][version] = {
            "counts_by_raw_version": dict(sorted(counts.items())),
            "unique_sources_by_raw_version": {
                key: len(values) for key, values in sorted(unique_sources.items())
            },
            "unmapped_count": len(unmapped), "unmapped_files": unmapped,
        }
        for owner, count in sorted(counts.items()):
            result["chart_data"]["formal_source_mix"].append({
                "nl_version": version, "raw_version": owner, "file_count": count,
            })
        for (owner, view), count in sorted(view_mix.items()):
            result["chart_data"]["formal_source_views"].append({
                "nl_version": version, "raw_version": owner, "view": view,
                "file_count": count,
            })
    for item in raw["versions"]:
        version = item["version_id"]
        inventory = inventory_for_ip_target(item["path"])
        raw["inventories"][version] = inventory
        item["inventory_status"] = inventory["status"]
        item["file_count"] = inventory["file_count"]
        item["unique_source_count"] = inventory["unique_source_count"]
        item["view_counts"] = inventory["view_counts"]
        if inventory["status"] != "COMPLETE":
            raw["status"] = "INCOMPLETE"
        for view, count in inventory["view_counts"].items():
            result["chart_data"]["raw_view_counts"].append({
                "raw_version": version, "view": view, "file_count": count,
            })
        result["chart_data"]["raw_version_file_counts"].append({
            "raw_version": version, "file_count": item.get("file_count"),
            "inventory_status": item["inventory_status"],
        })
    raw["comparison"] = _compare_raw_version_inventories(raw, candidates)
    ordered_versions = [item["version_id"] for item in raw["versions"]]
    raw["version_evolution"] = []
    for newer, older in zip(ordered_versions, ordered_versions[1:]):
        newer_inventory = raw["inventories"][newer]
        older_inventory = raw["inventories"][older]
        newer_paths = {item["relative_path"] for item in newer_inventory["files"]}
        older_paths = {item["relative_path"] for item in older_inventory["files"]}
        newer_views = Counter(item["view"] for item in newer_inventory["files"])
        older_views = Counter(item["view"] for item in older_inventory["files"])
        raw["version_evolution"].append({
            "newer": newer, "older": older,
            "status": "COMPLETE" if newer_inventory["status"] == older_inventory["status"] == "COMPLETE" else "INCOMPLETE",
            "same_path": len(newer_paths & older_paths),
            "only_newer": len(newer_paths - older_paths),
            "only_older": len(older_paths - newer_paths),
            "view_counts": {
                view: {"newer": newer_views[view], "older": older_views[view],
                       "delta": newer_views[view] - older_views[view]}
                for view in sorted(newer_views.keys() | older_views.keys())
            },
        })
    if raw["comparison"]["status"] == "INCOMPLETE":
        raw["status"] = "INCOMPLETE"
    if raw["comparison"].get("status") == "COMPLETE":
        for view, counts in raw["comparison"].get("view_counts", {}).items():
            result["chart_data"]["raw_version_comparison"].append({
                "latest": raw["comparison"]["latest"],
                "next_latest": raw["comparison"]["next_latest"],
                "view": view, **counts,
            })
    latest = result.get("matches", [])[:1]
    if not latest:
        return
    latest_version = latest[0]["nl_version"]
    latest_inventory = result["inventories"][latest_version]
    if latest_inventory["status"] != "COMPLETE":
        return
    selected_by_version: dict[str, set[str]] = {}
    for file in latest_inventory["files"]:
        version = file.get("raw_version")
        if version:
            selected_by_version.setdefault(version, set()).add(file["source_path"])
    for version, selected_sources in sorted(selected_by_version.items()):
        raw_inventory = raw["inventories"][version]
        if raw_inventory["status"] != "COMPLETE":
            raw["formal_coverage"][version] = {"status": "INCOMPLETE"}
            continue
        raw_view_by_source: dict[str, str] = {}
        for file in raw_inventory["files"]:
            raw_view_by_source.setdefault(file["source_path"], file["view"])
        unknown_sources = selected_sources - raw_view_by_source.keys()
        if unknown_sources:
            raw["formal_coverage"][version] = {"status": "INCOMPLETE"}
            raw["issues"].append(f"原始版本 {version} 有 {len(unknown_sources)} 个正式来源未进入原始文件清单")
            raw["status"] = "INCOMPLETE"
            continue
        original_by_view: dict[str, set[str]] = {}
        selected_by_view: dict[str, set[str]] = {}
        for source, view in raw_view_by_source.items():
            original_by_view.setdefault(view, set()).add(source)
            if source in selected_sources:
                selected_by_view.setdefault(view, set()).add(source)
        unlinked_sources = raw_view_by_source.keys() - selected_sources
        seen: set[str] = set()
        unlinked_files = []
        for file in raw_inventory["files"]:
            source = file["source_path"]
            if source in unlinked_sources and source not in seen:
                unlinked_files.append({"relative_path": file["relative_path"],
                                       "view": file["view"], "source_path": source})
                seen.add(source)
        raw["formal_coverage"][version] = {
            "status": "COMPLETE", "formal_version": latest_version,
            "raw_unique_source_count": raw_inventory["unique_source_count"],
            "formal_unique_source_count": len(selected_sources),
            "unlinked_unique_source_count": len(unlinked_sources),
            "unlinked_files": unlinked_files,
        }
        for view in sorted(original_by_view.keys() | selected_by_view.keys()):
            result["chart_data"]["raw_formal_view_coverage"].append({
                "raw_version": version, "view": view,
                "raw_source_count": len(original_by_view.get(view, set())),
                "formal_source_count": len(selected_by_view.get(view, set())),
            })


def _raw_version_sort_key(name: str) -> tuple[tuple[int, ...], str]:
    """Order source version directory names by embedded numeric version/date tokens."""
    return tuple(int(value) for value in NUMBERS_RE.findall(name)), name.casefold()


def _compare_raw_version_inventories(raw: dict[str, Any], candidates: list[str]) -> dict[str, Any]:
    if len(candidates) < 2:
        return {"status": "NOT_ENOUGH_VERSIONS", "latest": candidates[0] if candidates else None,
                "next_latest": None}
    latest, previous = candidates
    inventories = raw["inventories"]
    if latest not in inventories or previous not in inventories:
        return {"status": "NOT_AVAILABLE", "latest": latest, "next_latest": previous}
    latest_inventory, previous_inventory = inventories[latest], inventories[previous]
    if latest_inventory["status"] != "COMPLETE" or previous_inventory["status"] != "COMPLETE":
        return {"status": "INCOMPLETE", "latest": latest, "next_latest": previous,
                "latest_status": latest_inventory["status"],
                "next_latest_status": previous_inventory["status"]}
    latest_paths = {item["relative_path"]: item for item in latest_inventory["files"]}
    previous_paths = {item["relative_path"]: item for item in previous_inventory["files"]}
    only_latest = sorted(latest_paths.keys() - previous_paths.keys())
    only_previous = sorted(previous_paths.keys() - latest_paths.keys())
    by_view: dict[str, dict[str, int]] = {}
    for view in sorted({item["view"] for item in latest_paths.values()} |
                       {item["view"] for item in previous_paths.values()}):
        latest_count = sum(item["view"] == view for item in latest_paths.values())
        previous_count = sum(item["view"] == view for item in previous_paths.values())
        by_view[view] = {"latest": latest_count, "next_latest": previous_count,
                         "delta": latest_count - previous_count}
    return {
        "status": "COMPLETE", "latest": latest, "next_latest": previous,
        "comparison_basis": "相对路径清单；未读取内容、未计算 Hash，不代表同路径文件内容相同",
        "counts": {"same_path": len(latest_paths.keys() & previous_paths.keys()),
                   "only_latest": len(only_latest), "only_next_latest": len(only_previous)},
        "view_counts": by_view,
        "only_latest_paths": only_latest,
        "only_next_latest_paths": only_previous,
    }


def _md(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _sample_by_view(items: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        groups.setdefault(item["view"], []).append(item)
    sample: list[dict[str, Any]] = []
    while len(sample) < limit and any(groups.values()):
        for view in sorted(groups):
            if groups[view] and len(sample) < limit:
                sample.append(groups[view].pop(0))
    return sample


def _file_pair_markdown(pairing: dict[str, Any]) -> list[str]:
    labels = {
        "MATCHED": "路径唯一匹配", "REVIEW_CANDIDATE": "同名候选，待人工确认",
        "AMBIGUOUS": "多个候选，无法自动选择", "UNMATCHED": "未找到对应正式来源",
    }
    lines = ["## 新 RAW 文件与正式来源配对", ""]
    if pairing.get("status") == "NEEDS_FORMAL_STAGE":
        options = "、".join(f"`{item}`" for item in pairing.get("formal_stage_candidates", [])) or "无"
        lines.append(f"正式根未限定为单一阶段（发现：{options}），本次未自行选择比较对象。请将正式根配置到单一 `lib_NL<阶段>/IP`，或显式指定正式阶段。")
        return lines
    if pairing.get("status") in {"FORMAL_STAGE_NOT_FOUND", "RAW_VERSION_NOT_FOUND"}:
        lines.append(f"无法生成配对：{pairing['status']}；检查正式阶段和 RAW 版本是否已盘点。")
        return lines
    summary = pairing.get("summary") or {}
    lines.extend([
        f"正式阶段：`{_md(pairing.get('formal_stage', '未识别'))}`；新 RAW：`{_md(pairing.get('raw_version', '未识别'))}`。",
        f"新文件 {summary.get('new_raw_file_count', 0)} 个：唯一匹配 {summary.get('matched', 0)}，"
        f"待人工确认 {summary.get('review_candidate', 0)}，歧义 {summary.get('ambiguous', 0)}，"
        f"未匹配 {summary.get('unmatched', 0)}。",
        f"另有 {summary.get('formal_sources_without_raw_origin', 0)} 个正式链接无法归属到配置的 RAW 版本；这些来源不参与自动配对。",
        "只按 View 内相对路径和文件名配对；不读取内容、不计算 Hash、不作放行结论。", "",
        "| 新 RAW 文件 | 配对状态 | 正式 RAW 来源 | 正式目录路径 | 匹配依据 |",
        "| --- | --- | --- | --- | --- |",
    ])
    for item in pairing.get("pairs", [])[:100]:
        raw_file = item.get("raw_file") or {}
        formal = item.get("formal_source")
        candidates = item.get("candidates") or []
        source_text = f"`{_md(formal.get('source_path', ''))}`" if formal else (
            "；".join(f"`{_md(row.get('source_path', ''))}`" for row in candidates[:3]) or "—"
        )
        published = f"`{_md(formal.get('published_path', ''))}`" if formal else "—"
        lines.append(
            f"| `{_md(raw_file.get('relative_path', ''))}` | {labels.get(item.get('status'), item.get('status'))} "
            f"| {source_text} | {published} | {_md(item.get('match_method', ''))} |"
        )
    if len(pairing.get("pairs", [])) > 100:
        lines.append(f"另有 {len(pairing['pairs']) - 100} 个文件配对记录见 JSON。")
    lines.append("")
    return lines


def _render_single_stage_markdown(result: dict[str, Any]) -> str:
    matches = result.get("matches", [])
    match = matches[0] if matches else {}
    stage = match.get("nl_version", "未识别")
    inventory = result.get("inventories", {}).get(stage, {})
    raw = result.get("raw_library", {})
    source = result.get("formal_sources", {}).get(stage, {})
    lines = [
        "# 指定正式阶段 IP 文件核查", "",
        f"- IP：`{_md(result.get('ip_directory_name', ''))}`",
        f"- 正式阶段：`{_md(stage)}`（阶段编号；不表示最新或次新）",
        f"- 正式 IP 路径：`{_md(result.get('formal_nl_root', ''))}`",
        f"- 原始 IP 路径：`{_md(raw.get('root_path') or '未配置')}`",
        f"- 盘点状态：{'完成' if result.get('report_status') == 'COMPLETE' else '未完成；请查看异常'}",
        "- 方式：只读遍历文件和链接；不读取文件内容、不计算 Hash。", "",
        "## 阶段内容统计", "",
    ]
    if result.get("status") != "MATCHED":
        lines.extend([
            "没有在指定阶段路径下找到可归属该 IP 的文件链接。请确认 `formal_nl.root` 指向 `lib_NL<阶段号>/IP`，"
            "并确认 `library.root` 指向该 IP 的原始版本父目录。", "",
        ])
    else:
        lines.extend([
            f"本次只核查指定阶段 `{_md(stage)}`，不进行正式阶段之间的比较。",
            "视图数量表示该阶段下可见文件路径数；数量为 0 只表示没有发现该类文件，不自动判定缺交付。", "",
            "| 文件类型 | 可见路径数 |",
            "| --- | ---: |",
        ])
        for view in ("lef", "liberty", "db", "gds", "cdl", "verilog", "oas", "spice", "ndm", "other"):
            lines.append(f"| {_md(view)} | {inventory.get('view_counts', {}).get(view, 0)} |")
        lines.extend([
            f"| **可见路径合计** | **{inventory.get('file_count', 0)}** |",
            f"| **不同来源路径** | **{inventory.get('unique_source_count', 0)}** |", "",
        ])

    lines.extend(["## 正式链接来自哪些原始版本", ""])
    if source.get("counts_by_raw_version"):
        lines.extend([
            "| 原始版本目录 | 正式可见路径 | 去重来源路径 |",
            "| --- | ---: | ---: |",
        ])
        for version, count in sorted(source["counts_by_raw_version"].items()):
            unique = source.get("unique_sources_by_raw_version", {}).get(version, 0)
            lines.append(f"| `{_md(version)}` | {count} | {unique} |")
    else:
        lines.append("没有可归属到原始版本目录的正式链接来源。")
    if source.get("unmapped_count"):
        lines.append(f"另有 {source['unmapped_count']} 条来源无法归属到配置的原始版本目录；明细见 JSON。")
    formal_files = inventory.get("files", [])
    if formal_files:
        lines.extend(["", "## 正式路径 → 原始来源", "",
                      "展示正式目录中的相对路径及其链接解析后的原始绝对路径；这里只核对路径来源，不比较文件内容。", "",
                      "| 正式相对路径 | 类型 | 原始版本目录 | 原始绝对路径 |",
                      "| --- | --- | --- | --- |"])
        for item in formal_files[:100]:
            lines.append(
                f"| `{_md(item.get('relative_path', ''))}` | {_md(item.get('view', 'other'))} "
                f"| `{_md(item.get('raw_version') or '无法归属')}` "
                f"| `{_md(item.get('source_path', ''))}` |"
            )
        if len(formal_files) > 100:
            lines.append(f"完整清单共 {len(formal_files)} 条；Markdown 显示前 100 条，其余见 JSON 的正式文件清单。")
    if result.get("file_pairs"):
        lines.extend(["", *_file_pair_markdown(result["file_pairs"])])
    if result.get("candidate_filemap"):
        lines.extend(["", *_candidate_filemap_markdown(
            result["candidate_filemap"], result.get("formal_candidate_comparison", {}))])
    lines.extend(["", "## 原始版本目录", ""])
    versions = raw.get("versions", [])
    if versions:
        lines.extend([
            "按原始版本目录名中的数字字段排序（自然降序）；每个版本均已盘点文件路径与类型。排序是路径命名推断，不证明内容完整或已经生效。",
            "| 原始版本 | 路径 | 本次状态 | 可见路径数 |",
            "| --- | --- | --- | ---: |",
        ])
        for item in versions:
            status = "未被本阶段引用，未盘点" if item["inventory_status"] == "NOT_SCANNED" else (
                "已盘点" if item["inventory_status"] == "COMPLETE" else "盘点不完整"
            )
            lines.append(f"| `{_md(item['version_id'])}` | `{_md(item['path'])}` | {status} | {item.get('file_count', '—')} |")
    else:
        lines.append("未发现可读取的原始版本目录；请检查原始 IP 路径和权限。")

    evolution = raw.get("version_evolution", [])
    if evolution:
        lines.extend([
            "", "## RAW 原始版本逐级演进", "",
            f"已对 {len(versions)} 个原始版本的相邻目录逐级比较，共 {len(evolution)} 组。比较对象是各版本的相对文件路径及视图数量，不读取内容或 Hash；路径相同不代表文件内容相同。",
            "正式阶段引用来源仍单独列在上方；本表用于判断新到 RAW 版本相对前序目录的文件构成变化。", "",
            "| 较新 RAW 版本 | 前一 RAW 版本 | 共同相对路径 | 仅新版本路径 | 仅前版路径 | 盘点状态 |",
            "| --- | --- | ---: | ---: | ---: | --- |",
        ])
        for row in evolution:
            lines.append(
                f"| `{_md(row['newer'])}` | `{_md(row['older'])}` | {row['same_path']} | "
                f"{row['only_newer']} | {row['only_older']} | "
                f"{'完整' if row['status'] == 'COMPLETE' else '不完整'} |"
            )
        lines.extend([
            "", "各版本视图数量与逐版本文件清单保存在 JSON 的 `chart_data.raw_view_counts`、`raw_library.inventories`；"
            "此处的路径变化不能单独证明文件内容变化或交付质量。",
        ])

    candidates = raw.get("version_candidates", {})
    comparison = raw.get("comparison", {})
    if candidates.get("latest"):
        lines.extend([
            "", "## 原始版本新旧参考", "",
            f"按原始目录名推断的最新候选：`{_md(candidates['latest'])}`；"
            f"次新候选：`{_md(candidates.get('next_latest') or '无')}`。",
            "这用于快速查看当前正式链接采用的原始版本新旧；不是有效库确认，也不把正式阶段号当作原始版本号。", "",
        ])
        selected_counts = source.get("counts_by_raw_version", {})
        for candidate in (candidates.get("latest"), candidates.get("next_latest")):
            if candidate:
                lines.append(
                    f"- `{_md(candidate)}`：原始清单 {raw.get('inventories', {}).get(candidate, {}).get('file_count', '未盘点')} 条路径；"
                    f"本正式阶段引用 {selected_counts.get(candidate, 0)} 条。"
                )
        if comparison.get("status") == "COMPLETE":
            counts = comparison["counts"]
            lines.extend([
                "", f"最新与次新原始目录的路径清单对照：相同相对路径 {counts['same_path']} 条，"
                f"仅最新目录有 {counts['only_latest']} 条，仅次新目录有 {counts['only_next_latest']} 条。",
                "同路径只代表路径相同；未读取文件内容，不能据此断言内容未变。", "",
                "| 文件类型 | 最新目录 | 次新目录 | 数量差 |",
                "| --- | ---: | ---: | ---: |",
            ])
            for view, counts_by_view in comparison.get("view_counts", {}).items():
                lines.append(
                    f"| {_md(view)} | {counts_by_view['latest']} | {counts_by_view['next_latest']} | "
                    f"{counts_by_view['delta']:+d} |"
                )
            for label, key in (("仅最新目录有的路径", "only_latest_paths"),
                               ("仅次新目录有的路径", "only_next_latest_paths")):
                paths = comparison.get(key, [])
                if paths:
                    lines.extend(["", f"{label}（最多显示 20 条，完整清单见 JSON）："])
                    lines.extend(f"- `{_md(path)}`" for path in paths[:20])
                    if len(paths) > 20:
                        lines.append(f"- 另有 {len(paths) - 20} 条。")
        elif comparison.get("status") == "INCOMPLETE":
            lines.append("最新/次新目录有一侧盘点不完整，未生成清单对照；请查看盘点异常。")
        elif comparison.get("status") == "NOT_ENOUGH_VERSIONS":
            lines.append("原始根目录只有一个版本目录，无法与次新版本对照。")
        else:
            lines.append("未能完成最新/次新原始目录清单对照；请查看 JSON 中的盘点状态。")

    coverage = raw.get("formal_coverage", {})
    if coverage:
        lines.extend([
            "", "## 被引用原始版本中，哪些文件未链接到本阶段", "",
            "以下只对正式链接实际引用的原始版本统计；未链接不代表缺失或错误。", "",
            "| 原始版本 | 文件类型 | 原始不同来源 | 正式引用来源 | 未引用来源 |",
            "| --- | --- | ---: | ---: | ---: |",
        ])
        for row in result.get("chart_data", {}).get("raw_formal_view_coverage", []):
            lines.append(
                f"| `{_md(row['raw_version'])}` | {_md(row['view'])} | {row['raw_source_count']} | "
                f"{row['formal_source_count']} | {row['raw_source_count'] - row['formal_source_count']} |"
            )
        unlinked = [
            {"raw_version": version, **item}
            for version, data in coverage.items()
            if data.get("status") == "COMPLETE"
            for item in data.get("unlinked_files", [])
        ]
        if unlinked:
            lines.extend(["", "未链接文件示例（完整路径见 JSON）："])
            for item in _sample_by_view(unlinked, 8):
                lines.append(f"- `{_md(item['raw_version'])}` / `{_md(item['relative_path'])}`（{_md(item['view'])}）")

    audit = result.get("filename_coverage", {}).get(stage, {})
    corner_counts = audit.get("corner_counts", {})
    if corner_counts:
        lines.extend([
            "", "## LIB / DB 文件名角标", "",
            "角标仅从链接文件名识别，不读取 LIB/DB 内容。", "",
            "| 文件名角标 | LIB 文件数 | DB 文件数 |",
            "| --- | ---: | ---: |",
        ])
        corners = sorted(set(corner_counts.get("liberty", {})) | set(corner_counts.get("db", {})))
        for corner in corners:
            lines.append(
                f"| {_md(corner)} | {corner_counts.get('liberty', {}).get(corner, 0)} | "
                f"{corner_counts.get('db', {}).get(corner, 0)} |"
            )
        rc_counts = audit.get("rc_corner_counts", {})
        rc_labels = sorted(set(rc_counts.get("liberty", {})) | set(rc_counts.get("db", {})))
        if rc_labels:
            lines.extend(["", "RC 文件名标签："])
            for label in rc_labels:
                lines.append(
                    f"- `{_md(label)}`：LIB {rc_counts.get('liberty', {}).get(label, 0)} 个，"
                    f"DB {rc_counts.get('db', {}).get(label, 0)} 个"
                )
        unmatched = [row for row in audit.get("lib_db_pairs", []) if row["status"] != "PAIRED"]
        if unmatched:
            lines.extend(["", "LIB/DB 同名对照异常（只作名称核对提示，不判定缺交付）：", ""])
            for row in unmatched[:30]:
                labels = {"LIB_ONLY": "只有 LIB", "DB_ONLY": "只有 DB", "AMBIGUOUS": "名称不唯一"}
                lines.append(
                    f"- `{_md(row['key'])}`：LIB {len(row['liberty_files'])} 个，"
                    f"DB {len(row['db_files'])} 个，{labels[row['status']]}"
                )
            if len(unmatched) > 30:
                lines.append(f"- 其余 {len(unmatched) - 30} 项见 JSON。")
        else:
            lines.append("LIB/DB 文件名未发现单侧或重名条目。")

    problems: list[str] = []
    for path in result.get("broken_links", []):
        problems.append(f"正式链接失效：`{_md(path)}`")
    for issue in inventory.get("issues", []):
        problems.append(f"正式目录 `{_md(issue['relative_path'])}`：{_md(issue['reason'])}")
    for issue in raw.get("issues", []):
        problems.append(_md(issue))
    if problems:
        lines.extend(["", "## 盘点异常", "", *[f"- {problem}" for problem in problems]])
    lines.extend([
        "", "## 结论边界", "",
        "本报告核查的是指定 `lib_NL<阶段号>/IP` 目录中的文件路径、链接来源、类型数量和文件名角标。",
        "不比较不同正式阶段，不读取内容或 Hash，不判断 Macro 粒度完整性、文件语义正确性、必需交付项或正式放行。",
        "正式与原始目录均可用于核对文件构成；某类文件为 0 或原始文件未被链接，需结合该 IP 的交付要求由使用者判断。", "",
    ])
    return "\n".join(lines)


def render_markdown(result: dict[str, Any]) -> str:
    """Answer operator questions while keeping unsupported conclusions explicit."""
    if result.get("formal_scope") == "SINGLE_STAGE":
        return _render_single_stage_markdown(result)
    lines = [
        "# 正式 IP 核查报告未生成", "",
        f"- 配置的正式根目录：`{_md(result.get('formal_nl_root', ''))}`",
        "- 原因：配置的正式根不是单阶段 IP 目录，无法确定本次要核查的正式 IP 阶段。", "",
        "请将 `formal_nl.root` 直接设置为 `lib_NL<阶段号>/IP` 目录后重新运行。",
        "本工具不对多个正式阶段排序或互相比较；原始库版本的新旧参考仍依据原始目录名推断。", "",
    ]
    if result.get("file_pairs"):
        lines.extend(_file_pair_markdown(result["file_pairs"]))
    if result.get("candidate_filemap"):
        lines.extend(_candidate_filemap_markdown(
            result["candidate_filemap"], result.get("formal_candidate_comparison", {})))
    return "\n".join(lines)
    matches = result.get("matches", [])[:2]
    comparison = result.get("comparison", {})
    raw = result.get("raw_library", {})
    lines = [
        "# 原始库与正式 NL 文件核查", "",
        f"- IP：`{_md(result['ip_directory_name'])}`",
        f"- 原始库：`{_md(raw.get('root_path') or '未配置')}`",
        f"- 正式目录：`{_md(result['formal_nl_root'])}`",
        f"- 目录核查：{'所选目录已遍历' if result.get('report_status') == 'COMPLETE' else '未完成；见下方异常'}；不代表全部原始版本已盘点、交付质量或发布放行。",
        "- 核查方式：只读遍历目录与链接，不读取文件内容。", "",
        "## 核查结论", "",
    ]
    if result["status"] != "MATCHED":
        lines.append("未找到可归属此 IP 的正式版本；请检查库名、链接目标、版本目录和 library.root（文件级链接需要原始 IP 根目录）。" if result["status"] == "NOT_FOUND"
                     else "同一版本存在不同目标，无法可靠确定正式版本；请先核对冲突链接。")
    elif len(matches) == 1:
        lines.append(f"只有一个按目录名识别的正式版本：`{_md(matches[0]['nl_version'])}`；可查看其文件清单，无法进行版本间比较，不代表当前有效指针。")
    else:
        lines.append(f"按目录名数字排序的最高版本为 `{_md(matches[0]['nl_version'])}`，次高为 `{_md(matches[1]['nl_version'])}`；不代表当前有效指针。")
        if comparison["status"] == "COMPLETE":
            counts = comparison["counts"]
            lines.append(
                f"正式目录相对路径：仅在编号最高目录出现的相对路径 {counts['added']} 条、"
                f"仅在次高目录出现 {counts['removed']} 条；两边同名路径中，"
                f"链接目标路径变化 {counts['source_updated']} 条、目标路径相同 {counts['same_source']} 条。"
            )
            lines.append("链接目标路径变化不证明文件内容变化；本次未读取内容或计算 Hash。")
        else:
            lines.append("文件清单不完整，暂不计算版本差异；请先处理下面的遍历异常。")
    if raw:
        if raw["status"] in {"COMPLETE", "INCOMPLETE"}:
            lines.append(f"原始库发现 {raw['version_count']} 个直接子版本目录；只盘点所选正式目录引用的版本。")
        elif raw["status"] == "NOT_CONFIGURED":
            lines.append("原始库未配置，无法核对正式文件的原始版本归属。")
        else:
            lines.append(f"原始库无法完成核查：{'；'.join(raw['issues'])}。")
    latest = matches[0]["nl_version"] if matches else ""
    latest_sources = result.get("formal_sources", {}).get(latest, {})
    if matches and matches[0].get("layout") == "FLAT_FILE_LINKS":
        lines.append("正式目录采用按视图分组的文件级链接；本报告只统计目标落在所配置原始 IP 根目录内的文件，不把同目录其他 IP 的链接算入。")
        ignored = result.get("inventories", {}).get(latest, {}).get("ignored_outside_source_count", 0)
        if ignored:
            lines.append(f"同一正式盘点目录另有 {ignored} 条目标不在该原始 IP 根目录内的路径未计入。")
    if latest_sources:
        origins = "、".join(f"{name} {count} 条" for name, count in latest_sources["counts_by_raw_version"].items())
        lines.append(f"最高编号正式目录的链接来源：{origins or '没有可归属的原始版本'}；"
                     f"库外或无法归属 {latest_sources['unmapped_count']} 条。")
    lines.extend(["", "## 原始库有哪些版本", ""])
    if raw.get("versions"):
        lines.extend(["| 原始版本 | 原始目录 | 文件清单 | 可见路径 |",
                      "| --- | --- | --- | ---: |"])
        versions = sorted(raw["versions"], key=lambda item: (item["inventory_status"] == "NOT_SCANNED", item["version_id"]))
        for item in versions[:20]:
            if item["inventory_status"] == "NOT_SCANNED":
                status = "未盘点（未被所选正式目录引用）"
            else:
                status = "已遍历" if item["inventory_status"] == "COMPLETE" else "遍历不完整"
            lines.append(f"| {_md(item['version_id'])} | `{_md(item['path'])}` | {status} | {item.get('file_count', '—')} |")
        if len(versions) > 20:
            lines.append(f"\n另有 {len(versions) - 20} 个原始版本路径见 JSON 的 `raw_library.versions`。")
    else:
        lines.append("原始版本目录不可用；完整核查需配置可读的 `library.root`。")
    lines.extend(["", "## 正式链接由哪些原始版本提供", ""])
    if result.get("formal_sources"):
        lines.extend(["| 正式 NL 版本 | 原始版本 | 可见路径 | 不同来源 |",
                      "| --- | --- | ---: | ---: |"])
        for match in matches:
            source = result["formal_sources"].get(match["nl_version"])
            if not source:
                continue
            for version, count in source["counts_by_raw_version"].items():
                lines.append(f"| {_md(match['nl_version'])} | {_md(version)} | {count} | "
                             f"{source['unique_sources_by_raw_version'][version]} |")
            if source["unmapped_count"]:
                lines.append(f"| {_md(match['nl_version'])} | 库外或无法归属 | {source['unmapped_count']} | — |")
    else:
        lines.append("没有可核对的来源对应；正式链接必须可读，且需配置原始库版本父目录。")
    lines.extend(["", "可见路径数包含别名链接；去重来源数按解析后的绝对路径计数，不代表内容去重。", ""])
    lines.extend(["## 哪些原始文件未被最高编号正式目录引用", ""])
    coverage = raw.get("formal_coverage", {})
    if coverage:
        lines.extend(["这里只比较最高编号正式目录实际引用的原始版本；未引用来源按去重后的绝对路径计数，不是原始可见路径数减正式可见路径数。未选入不代表缺失。", "",
                      "| 原始版本 | 视图 | 原始不同来源 | 正式引用来源 | 未引用来源 |",
                      "| --- | --- | ---: | ---: | ---: |"])
        for row in result["chart_data"]["raw_formal_view_coverage"]:
            lines.append(f"| {_md(row['raw_version'])} | {_md(row['view'])} | {row['raw_source_count']} | "
                         f"{row['formal_source_count']} | {row['raw_source_count'] - row['formal_source_count']} |")
        examples = [{"raw_version": version, **item} for version, data in coverage.items()
                    if data["status"] == "COMPLETE" for item in data["unlinked_files"]]
        if examples:
            lines.append("\n未引用文件示例（完整路径见 JSON 的 `raw_library.formal_coverage`）：")
            sampled = _sample_by_view(examples, 5)
            for item in sampled:
                lines.append(f"- `{_md(item['raw_version'])}` / `{_md(item['relative_path'])}` ({_md(item['view'])})")
            if len(examples) > len(sampled):
                lines.append(f"- 其余 {len(examples) - len(sampled)} 条见 JSON。")
        if any(data["status"] != "COMPLETE" for data in coverage.values()):
            lines.append("部分原始目录清单不完整，未引用数量不可确认。")
    else:
        lines.append("没有可可靠核对的原始文件与最高编号正式目录的链接范围。")
    lines.append("")
    lines.extend(["", "## 正式目录各包含哪些可见文件", "",
                  "| 视图 | 最高编号目录 | 次高编号目录 |", "| --- | ---: | ---: |"])
    inventory = result.get("inventories", {})
    first = inventory.get(matches[0]["nl_version"], {}) if matches else {}
    second = inventory.get(matches[1]["nl_version"], {}) if len(matches) > 1 else {}
    listed_views = set(first.get("view_counts", {})) | set(second.get("view_counts", {}))
    if matches:
        listed_views.update(("lef", "liberty", "db", "gds", "cdl", "verilog"))
    for view in sorted(listed_views):
        current_count = first.get("view_counts", {}).get(view, 0) if first.get("status") == "COMPLETE" else "未确认"
        old_count = (second.get("view_counts", {}).get(view, 0) if second.get("status") == "COMPLETE"
                     else "未确认" if len(matches) > 1 else "—")
        lines.append(f"| {_md(view)} | {current_count} | {old_count} |")
    if not first.get("view_counts"):
        lines.append("| 暂无可统计文件 | — | — |")
    lines.append(f"| **可见路径合计** | {first.get('file_count', '—')} | {second.get('file_count', '—')} |")
    lines.append(f"| **不同来源文件** | {first.get('unique_source_count', '—')} | {second.get('unique_source_count', '—')} |")
    lines.append("\n统计口径：本表的视图数量是正式目录的可见路径数；0 表示已遍历目录未见该类型，"
                 "不自动判定交付缺失。原始文件未引用表统计的是去重来源路径，两者不能直接相减。")
    lines.extend(["", "| 版本 | 入口形式 | 正式入口 | 盘点目录 | 文件清单 |", "| --- | --- | --- | --- | --- |"])
    for match in matches:
        layout = "文件级链接" if match.get("layout") == "FLAT_FILE_LINKS" else "IP 目录软链接"
        lines.append(f"| {_md(match['nl_version'])} | {layout} | `{_md(match['link_path'])}` | "
                     f"`{_md(match['target_path'])}` | {_md({'COMPLETE': '已遍历', 'INCOMPLETE': '遍历不完整'}.get(match.get('inventory_status'), '未读取'))} |")
    lines.extend(["", "## LIB / DB 文件名与角标", "",
                  "按链接名统计正式目录的工艺角；未识别与标签冲突单独列出。"
                  "LIB/DB 只按去掉扩展名后的完整文件名配对，不读取内容。", "",
                  "| 正式版本 | 文件名角标 | LIB | DB | 文件示例 |",
                  "| --- | --- | ---: | ---: | --- |"])
    for match in matches:
        version = match["nl_version"]
        audit = result.get("filename_coverage", {}).get(version, {})
        corners = audit.get("corner_counts", {})
        for corner in sorted(set(corners.get("liberty", {})) | set(corners.get("db", {}))):
            examples = [f"{row['view']}: `{_md(Path(row['relative_path']).name)}`"
                        for row in audit.get("files", []) if row["corner_label"] == corner]
            shown = "、".join(examples[:3])
            if len(examples) > 3:
                shown += f"；另有 {len(examples) - 3} 个见 JSON"
            lines.append(f"| {_md(version)} | {_md(corner)} | "
                         f"{corners.get('liberty', {}).get(corner, 0)} | {corners.get('db', {}).get(corner, 0)} | {shown} |")
        if not corners.get("liberty") and not corners.get("db"):
            lines.append(f"| {_md(version)} | 无可识别的 LIB/DB 文件 | 0 | 0 | — |")
    lines.extend(["", "### RC 文件名标签", "",
                  "RC 角只统计链接名中的 SIGRCMIN/SIGRCMAX；未标注不等于文件没有 RC 条件。", "",
                  "| 正式版本 | RC 标签 | LIB | DB |",
                  "| --- | --- | ---: | ---: |"])
    for match in matches:
        version = match["nl_version"]
        counts = result.get("filename_coverage", {}).get(version, {}).get("rc_corner_counts", {})
        for label in sorted(set(counts.get("liberty", {})) | set(counts.get("db", {}))):
            lines.append(f"| {_md(version)} | {_md(label)} | "
                         f"{counts.get('liberty', {}).get(label, 0)} | {counts.get('db', {}).get(label, 0)} |")
    lines.extend(["", "### LIB / DB 同名文件对照", "",
                  "仅列出没有同名对应文件或同名不唯一的链接；这提示核对命名和交付范围，**不自动判定缺失**。", "",
                  "| 正式版本 | 文件名键 | LIB 链接 | DB 链接 | 对照情况 |",
                  "| --- | --- | --- | --- | --- |"])
    unmatched = [(match["nl_version"], row)
                 for match in matches
                 for row in result.get("filename_coverage", {}).get(match["nl_version"], {}).get("lib_db_pairs", [])
                 if row["status"] != "PAIRED"]
    for version, row in unmatched[:30]:
        labels = {"LIB_ONLY": "只有 LIB", "DB_ONLY": "只有 DB", "AMBIGUOUS": "同名不唯一"}
        libs = "、".join(f"`{_md(Path(path).name)}`" for path in row["liberty_files"]) or "—"
        dbs = "、".join(f"`{_md(Path(path).name)}`" for path in row["db_files"]) or "—"
        lines.append(f"| {_md(version)} | `{_md(row['key'])}` | {libs} | {dbs} | {labels[row['status']]} |")
    if not unmatched:
        lines.append("| — | — | — | — | 没有按同名规则发现单侧文件 |")
    elif len(unmatched) > 30:
        lines.append(f"\n其余 {len(unmatched) - 30} 项见 JSON 的 `filename_coverage`。")
    lines.extend(["", "文件名角标和同名配对不证明文件内的 Corner 或对象覆盖；其他视图的文件路径见 JSON 的 `inventories`。"])
    lines.extend(["", "## 按视图看，哪些文件来源发生了变化", ""])
    if comparison.get("status") == "COMPLETE":
        view_counts: dict[str, dict[str, int]] = {}
        for row in result["chart_data"]["view_transition_counts"]:
            view_counts.setdefault(row["view"], {})[row["change"]] = row["file_count"]
        lines.extend(["以下按正式目录内的相对路径核对；链接目标路径变化不代表文件字节变化。", "",
                      "| 视图 | 仅最高编号目录有 | 仅次高编号目录有 | 链接目标路径变化 | 目标路径相同 |",
                      "| --- | ---: | ---: | ---: | ---: |"])
        for view, count_by_kind in sorted(view_counts.items()):
            lines.append(f"| {_md(view)} | {count_by_kind.get('added', 0)} | "
                         f"{count_by_kind.get('removed', 0)} | {count_by_kind.get('source_updated', 0)} | "
                         f"{count_by_kind.get('same_source', 0)} |")
    else:
        lines.append("当前没有可确认的版本间视图对照。")
    lines.extend(["", "## 文件范围与来源有什么变化", ""])
    if comparison.get("status") == "COMPLETE":
        changes = comparison["changes"]
        if not changes:
            lines.append("两版相对路径及来源路径相同；仍不能据此判断文件字节是否相同。")
        else:
            lines.extend(["下表按视图取少量代表路径；全部变化与旧新来源绝对路径见 JSON 的 `comparison.changes`。", "",
                          "| 类型 | 视图 | 相对路径 |", "| --- | --- | --- |"])
            labels = {"added": "仅最高编号目录有", "removed": "仅次高编号目录有", "source_updated": "链接目标路径变化"}
            sampled = _sample_by_view(changes, 8)
            for change in sampled:
                lines.append(f"| {labels[change['change']]} | {_md(change['view'])} | "
                             f"`{_md(change['relative_path'])}` |")
            if len(changes) > len(sampled):
                lines.append(f"\n其余 {len(changes) - len(sampled)} 条见 JSON 的 `comparison.changes`。")
            source_updates = [item for item in changes if item["change"] == "source_updated"]
            if source_updates:
                lines.extend(["", "### 链接目标路径变化示例（未比较内容）", ""])
                for change in source_updates[:2]:
                    lines.extend([
                        f"- `{_md(change['relative_path'])}`",
                        f"  - 旧来源：`{_md(change['old_source_path'])}`",
                        f"  - 新来源：`{_md(change['new_source_path'])}`",
                    ])
                if len(source_updates) > 2:
                    lines.append(f"- 其余 {len(source_updates) - 2} 条旧新来源见 JSON。")
    elif comparison.get("status") == "NO_SECOND_VERSION":
        lines.append("只有一个正式版本，没有次新版本可比较。")
    else:
        lines.append("当前无法可靠对比：正式链接冲突、未找到版本或文件清单不完整。")
    lines.extend(["", "## 需处理的核查异常", ""])
    problems: list[str] = []
    for item in result.get("ambiguous_versions", []):
        problems.append(f"版本 `{_md(item['nl_version'])}` 指向多个目录：{', '.join(item['target_paths'])}")
    for path in result.get("broken_links", []):
        problems.append(f"正式链接失效：`{_md(path)}`")
    for version, data in inventory.items():
        for issue in data["issues"]:
            problems.append(f"`{_md(version)}` / `{_md(issue['relative_path'])}`：{_md(issue['reason'])}")
    for issue in raw.get("issues", []):
        problems.append(issue)
    for version, source in result.get("formal_sources", {}).items():
        if source["unmapped_count"]:
            examples = ", ".join(item["relative_path"] for item in source["unmapped_files"][:3])
            problems.append(f"正式版本 `{_md(version)}` 有 {source['unmapped_count']} 条库外或无法归属的来源；示例：{_md(examples)}")
    for version, data in raw.get("inventories", {}).items():
        for issue in data["issues"]:
            problems.append(f"原始版本 `{_md(version)}` / `{_md(issue['relative_path'])}`：{_md(issue['reason'])}")
    lines.extend(f"- {item}" for item in problems) if problems else lines.append("未发现链接冲突或遍历异常。")
    lines.extend(["", "## 需确认的发布范围", ""])
    non_view = [file["relative_path"] for file in first.get("files", []) if file["view"] == "other"]
    if non_view:
        examples = ", ".join(f"`{_md(path)}`" for path in non_view[:3])
        lines.append(f"最高编号正式目录包含 {len(non_view)} 条非视图路径（如 {examples}）；是否保留取决于该 IP 的发布要求，这不是已证实的错误。")
    else:
        lines.append("未发现需要单独确认的非视图路径。")
    if coverage:
        unlinked = sum(data.get("unlinked_unique_source_count", 0) for data in coverage.values())
        if unlinked:
            lines.append(f"有 {unlinked} 个去重原始来源未被最高编号正式目录引用；仅表示链接选取范围，不自动判定交付缺失。")
    lines.extend(["", "## 核查边界与图表数据", "",
                  "原始版本按目录列出；只盘点所选正式目录引用的版本。正式 NL 最高/次高版本按目录名数字排序，"
                  "不代表当前有效指针。未被正式链接引用的原始文件不自动算交付缺失。",
                  "本报告只说明目录、文件名与解析后的链接来源；**不判断内容是否变化**，"
                  "也不判断 View/Corner 是否满足交付要求或能否正式放行。",
                  "JSON 提供逐文件 `inventories`、逐项 `comparison.changes` 与图表行 `chart_data`；"
                  "各图表的单位和范围见 `chart_data_meta`。绘图须先按 `nl_version` 筛选，不能把两个正式目录的来源数直接相加作为当前目录构成；"
                  "`null` 表示未盘点，不是零。同一来源路径不代表不同时间文件内容未变。", ""])
    return "\n".join(lines)


def _load_config(path: Path) -> dict[str, Any]:
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("读取 YAML 需要 PyYAML；请使用项目运行环境安装的依赖。") from exc
    value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(value, dict):
        raise ValueError("配置文件顶层必须是 YAML mapping")
    return value


def _output_path(name: str, config_file: Path, input_roots: tuple[Path, ...]) -> Path:
    path = Path(name).expanduser()
    if not path.is_absolute():
        path = config_file.parent / path
    path = path.resolve()
    for root in input_roots:
        try:
            path.relative_to(root)
        except ValueError:
            continue
        raise ValueError("报告输出路径必须位于只读输入目录之外（正式 NL 根目录之外、原始库目录之外）")
    return path


def _report_status(result: dict[str, Any]) -> str:
    if result.get("formal_scope") != "SINGLE_STAGE":
        return "INCOMPLETE"
    if result["status"] != "MATCHED" or result["raw_library"]["status"] != "COMPLETE":
        return "INCOMPLETE"
    if any(item["status"] != "COMPLETE" for item in result["inventories"].values()):
        return "INCOMPLETE"
    if any(item["unmapped_count"] for item in result["formal_sources"].values()):
        return "INCOMPLETE"
    if any(item["status"] != "COMPLETE" for item in result["raw_library"]["formal_coverage"].values()):
        return "INCOMPLETE"
    return "COMPLETE"


def run(config_path: str | Path) -> dict[str, Any]:
    config_file = Path(config_path).expanduser().resolve()
    config = _load_config(config_file)
    library = config.get("library") or {}
    formal = config.get("formal_nl") or {}
    output = config.get("output") or {}
    ip_name = str(library.get("ip_directory_name") or "").strip()
    if not ip_name:
        library_root = str(library.get("root") or "").strip()
        if not library_root:
            raise ValueError("配置必须填写 library.ip_directory_name 或 library.root")
        ip_name = Path(library_root).expanduser().name
    formal_root = str(formal.get("root") or "").strip()
    if not formal_root:
        raise ValueError("配置缺少 formal_nl.root")
    formal_root_path = Path(formal_root).expanduser()
    if not formal_root_path.is_absolute():
        formal_root = str((config_file.parent / formal_root_path).resolve())
    formal_root_resolved = Path(formal_root).expanduser().resolve()
    library_root = str(library.get("root") or "").strip()
    raw_root = None
    if library_root:
        raw_root_path = Path(library_root).expanduser()
        raw_root = (raw_root_path if raw_root_path.is_absolute() else config_file.parent / raw_root_path).resolve()
    filemap_config = config.get("filemap") or {}
    catalog_value = str(library.get("catalog") or "").strip()
    catalog_path = None
    if catalog_value:
        catalog_candidate = Path(catalog_value).expanduser()
        catalog_path = (catalog_candidate if catalog_candidate.is_absolute()
                        else config_file.parent / catalog_candidate).resolve()
    result = discover_formal_ip_links(formal_root, ip_name, raw_root=raw_root)
    target_roots = [Path(item["target_path"]) for item in result["matches"]]
    target_roots.extend(Path(path) for item in result["ambiguous_versions"] for path in item["target_paths"])
    input_roots = ((formal_root_resolved,) + ((raw_root,) if raw_root is not None else ())
                   + tuple(target_roots) + ((catalog_path,) if catalog_path is not None else ()))
    json_path = _output_path(str(output.get("report_json") or "formal_nl_ip_links.json"),
                             config_file, input_roots)
    md_path = _output_path(str(output.get("report_md") or "formal_nl_ip_links.md"),
                           config_file, input_roots)
    if json_path == md_path:
        raise ValueError("report_json 和 report_md 必须是不同文件")
    result["library_id"] = str(library.get("id") or "")
    result["library_root"] = str(raw_root) if raw_root is not None else ""
    add_delivery_evidence(result)
    add_filename_coverage(result)
    add_raw_library_evidence(result, raw_root)
    result["file_pairs"] = resolve_file_pairs(result)
    result["candidate_filemap"] = {"schema_version": "candidate_filemap.v1", "status": "NOT_CONFIGURED",
                                   "files": [], "changes": [], "operations": {},
                                   "message": "请在 library.catalog 指定当前 Catalog JSON"}
    result["formal_candidate_comparison"] = {"status": "NOT_AVAILABLE", "counts": {}, "changes": []}
    if catalog_path is not None and raw_root is not None:
        try:
            package_metadata = _catalog_package_metadata(
                catalog_path, {**library, "root": str(raw_root)},
                result["raw_library"].get("versions", []))
            candidate_version = str(filemap_config.get("candidate_version") or
                                    result["raw_library"].get("version_candidates", {}).get("latest") or "")
            filemap = build_candidate_filemap(
                result["raw_library"], package_metadata, candidate_version,
                explicit_deletions=filemap_config.get("explicit_deletions"),
                explicit_resets=filemap_config.get("explicit_resets"),
            )
            filemap["formal_stage"] = result["file_pairs"].get("formal_stage")
            result["candidate_filemap"] = filemap
            formal_stage = filemap.get("formal_stage")
            if formal_stage in result.get("inventories", {}):
                result["formal_candidate_comparison"] = compare_formal_to_filemap(
                    result["inventories"][formal_stage], filemap)
            result["chart_data"]["candidate_operation_counts"] = [
                {"operation": key.upper(), "file_count": count}
                for key, count in sorted(filemap.get("operations", {}).items())
            ]
            result["chart_data"]["formal_candidate_operation_counts"] = [
                {"operation": key, "file_count": count}
                for key, count in sorted(result["formal_candidate_comparison"].get("counts", {}).items())
            ]
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            result["candidate_filemap"] = {
                "schema_version": "candidate_filemap.v1", "status": "CATALOG_UNAVAILABLE",
                "candidate_version": "", "chain": [], "files": [], "changes": [],
                "operations": {}, "message": str(exc),
                "basis": "Catalog 无法可靠加载时不生成候选集合",
            }
    result["report_status"] = _report_status(result)
    json_content = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    md_content = render_markdown(result)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json_content, encoding="utf-8")
    md_path.write_text(md_content, encoding="utf-8")
    result["report_json"] = str(json_path)
    result["report_md"] = str(md_path)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="只读核查正式 IP 来源、Catalog 增量链与候选文件集合")
    parser.add_argument("--config", required=True, help="YAML 配置路径")
    args = parser.parse_args(argv)
    try:
        result = run(args.config)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["report_status"] == "COMPLETE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
