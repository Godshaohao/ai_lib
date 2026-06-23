"""Post-release verification for manifest-driven release bundles."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping
from collections import Counter
import os

from .bundle import iter_release_files, load_release_manifest, manifest_run_dir, release_dir_for, read_json, write_json


def _norm(path: Any) -> str:
    if not path:
        return ""
    try:
        return os.path.normcase(str(Path(str(path)).resolve(strict=False)))
    except Exception:
        return os.path.normcase(str(path))


def _issue(severity: str, category: str, library_name: str | None, message: str) -> dict[str, Any]:
    return {"severity": severity, "category": category, "library_name": library_name, "message": message}


def _file_type_counts(path: Path, limit: int = 200000) -> dict[str, int]:
    from lib_guard.scan.file_classifier import FileClassifier

    classifier = FileClassifier()
    counts: Counter[str] = Counter()
    if not path.exists():
        return {}
    total = 0
    for item in path.rglob("*"):
        if not item.is_file():
            continue
        rel = item.relative_to(path).as_posix()
        record = classifier.classify({"path": rel, "name": item.name})
        counts[str(record.get("file_type") or "unknown")] += 1
        total += 1
        if total >= limit:
            counts["__truncated__"] += 1
            break
    return dict(sorted(counts.items()))


def _link_result_by_library(link_result: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    out: dict[str, Mapping[str, Any]] = {}
    for item in link_result.get("created_links", []) or []:
        if isinstance(item, Mapping) and item.get("library_name"):
            out[str(item.get("library_name"))] = item
    return out


def _link_result_by_relative_path(link_result: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    out: dict[str, Mapping[str, Any]] = {}
    for item in link_result.get("created_links", []) or []:
        if isinstance(item, Mapping) and item.get("relative_path"):
            out[str(item.get("relative_path"))] = item
    return out


def verify_release_manifest(
    manifest_path: str | Path,
    *,
    link_result_path: str | Path | None = None,
    out_dir: str | Path | None = None,
    render: bool = False,
    html_out: str | Path | None = None,
) -> dict[str, Any]:
    manifest = load_release_manifest(manifest_path)
    run_dir = manifest_run_dir(manifest_path, out_dir)
    release_dir = release_dir_for(manifest)
    link_json = Path(link_result_path) if link_result_path else run_dir / "release_link_result.json"
    link_result = read_json(link_json, {}) or {}
    link_by_rel = _link_result_by_relative_path(link_result)

    planned = [item for item in iter_release_files(manifest) if item.get("relative_path")]
    expected = {str(item.get("relative_path")): item for item in planned}
    actual_files = {
        item.relative_to(release_dir).as_posix(): item
        for item in release_dir.rglob("*")
        if release_dir.exists() and (item.is_file() or item.is_symlink())
    } if release_dir.exists() else {}
    issues: list[dict[str, Any]] = []
    library_stats: dict[str, dict[str, Any]] = {}

    for rel_path, plan in expected.items():
        library_name = str(plan.get("library_name") or "unknown")
        stats = library_stats.setdefault(
            library_name,
            {
                "library_type": plan.get("library_type"),
                "library_name": library_name,
                "version_id": plan.get("version_id"),
                "version_key": plan.get("version_key"),
                "source_path": plan.get("source_root"),
                "link_status": "OK",
                "target_match": True,
                "file_type_counts": Counter(),
                "source_package_counts": Counter(),
                "source_kind_counts": Counter(),
                "expected_files": 0,
                "linked_files": 0,
                "scan_html": plan.get("scan_html"),
                "diff_html": plan.get("diff_html"),
                "manual_accept": True,
            },
        )
        stats["expected_files"] += 1
        target = Path(str(plan.get("target_path") or release_dir / rel_path))
        link_info = link_by_rel.get(rel_path, {})
        exists = target.exists() or target.is_symlink()
        is_broken = target.is_symlink() and not target.exists()
        if not exists:
            stats["link_status"] = "MISSING"
            issues.append(_issue("warning", "missing_file", library_name, f"release file missing: {rel_path}"))
        if is_broken:
            stats["link_status"] = "BROKEN"
            issues.append(_issue("warning", "broken_link", library_name, f"broken symlink: {rel_path}"))

        source_path = str(plan.get("source_path") or "")
        recorded_target = str(link_info.get("target_path") or link_info.get("source_path") or "")
        target_match = True
        if recorded_target and _norm(recorded_target) != _norm(source_path):
            target_match = False
        elif target.is_symlink():
            try:
                target_match = _norm(target.resolve(strict=False)) == _norm(source_path)
            except Exception:
                target_match = False
        if not target_match:
            stats["target_match"] = False
            issues.append(_issue("warning", "target_mismatch", library_name, f"release target does not match manifest source file: {rel_path}"))

        if exists and not is_broken:
            stats["linked_files"] += 1
            stats["file_type_counts"][str(plan.get("file_type") or "unknown")] += 1
            if plan.get("source_package"):
                stats["source_package_counts"][str(plan.get("source_package"))] += 1
            if plan.get("source_kind"):
                stats["source_kind_counts"][str(plan.get("source_kind"))] += 1

    for rel_path in sorted(set(actual_files) - set(expected)):
        issues.append(_issue("warning", "extra_file", None, f"release directory contains extra file: {rel_path}"))

    counts = Counter(issue["category"] for issue in issues)
    libraries = []
    for stats in library_stats.values():
        clean = dict(stats)
        clean["file_type_counts"] = dict(sorted(clean["file_type_counts"].items()))
        clean["source_package_counts"] = dict(sorted(clean["source_package_counts"].items()))
        clean["source_kind_counts"] = dict(sorted(clean["source_kind_counts"].items()))
        libraries.append(clean)
    linked_files = sum(int(item.get("linked_files") or 0) for item in libraries)
    result = {
        "schema_version": "1.0",
        "release_id": manifest.get("release_id"),
        "alias": manifest.get("alias"),
        "release_root": manifest.get("release_root"),
        "release_dir": str(release_dir),
        "manifest_path": str(Path(manifest_path)),
        "link_result_path": str(link_json) if link_json.exists() else None,
        "postcheck_path": str(run_dir / "release_postcheck.json"),
        "status": "PASS_WITH_WARNING" if issues else "PASS",
        "summary": {
            "expected_libraries": len(library_stats),
            "linked_libraries": sum(1 for item in libraries if item.get("linked_files") == item.get("expected_files")),
            "expected_files": len(expected),
            "linked_files": linked_files,
            "missing_files": counts.get("missing_file", 0),
            "extra_files": counts.get("extra_file", 0),
            "broken_links": counts.get("broken_link", 0),
            "target_mismatch": counts.get("target_mismatch", 0),
            "unknown_file_types": sum((item.get("file_type_counts", {}) or {}).get("unknown", 0) for item in libraries),
        },
        "libraries": libraries,
        "issues": issues,
    }
    write_json(run_dir / "release_postcheck.json", result)
    if render:
        from lib_guard.render.release_report import render_release_html

        html_result = render_release_html(result, html_out or run_dir)
        result["html"] = html_result
        write_json(run_dir / "release_postcheck.json", result)
    return result
