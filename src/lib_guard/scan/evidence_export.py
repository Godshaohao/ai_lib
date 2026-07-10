from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Mapping
import csv
import json

from lib_guard.project_config import BINARY_METADATA_ONLY_TYPES, SUMMARY_ONLY_TYPES
from lib_guard.view_types import canonical_file_type, canonical_view_type, usage_area_for_view, view_label, view_sort_key


REQUIRED_REVIEW_VIEWS = {"physical_abstract", "timing_lib", "rtl_model"}


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")


def _write_tsv(path: Path, fieldnames: list[str], rows: list[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, delimiter="\t", extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({name: "" if row.get(name) is None else row.get(name) for name in fieldnames})


def evidence_level_for_file_type(file_type: Any) -> str:
    key = canonical_file_type(file_type)
    if key == "unknown":
        return "unknown"
    if key in BINARY_METADATA_ONLY_TYPES:
        return "metadata_only"
    if key in SUMMARY_ONLY_TYPES:
        return "summary_only"
    return "parsed"


def _status_for_view(view_type: str, count: int, required: bool, evidence_levels: set[str]) -> str:
    if count <= 0 and required:
        return "WARNING"
    if "unknown" in evidence_levels:
        return "WARNING"
    if evidence_levels & {"metadata_only", "summary_only"}:
        return "INFO"
    return "PASS" if count else "INFO"


def _meaning(view_type: str, evidence_levels: set[str], required: bool) -> str:
    if not evidence_levels and required:
        return "必需视图未发现，需要确认交付是否完整。"
    if "unknown" in evidence_levels:
        return "存在未识别文件，需要分类或确认可忽略。"
    if "metadata_only" in evidence_levels:
        return "按 metadata/hash/路径证据审查，不默认读取二进制内容。"
    if "summary_only" in evidence_levels:
        return "按 summary/count/corner 证据审查，不默认做全文深读。"
    if evidence_levels:
        return "已有可读结构证据，可进入版本对比或使用场景审查。"
    return "当前版本未发现该视图。"


def _parser_status_by_file(parser_manifest: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for entry in parser_manifest.get("files", []) or []:
        path = str(entry.get("file") or "")
        tasks = entry.get("parser_tasks") or []
        statuses = [str(task.get("result_status") or task.get("status") or "UNKNOWN").upper() for task in tasks if task.get("parser_name")]
        parsers = [str(task.get("parser_name")) for task in tasks if task.get("parser_name")]
        if not statuses:
            status = "SKIPPED"
        elif any(s == "FAILED" for s in statuses):
            status = "FAILED"
        elif any(s == "PASS_EMPTY" for s in statuses):
            status = "PASS_EMPTY"
        else:
            status = "PASS"
        out[path] = {"status": status, "parsers": ",".join(parsers), "task_count": len(statuses)}
    return out


def _parser_evidence_rows(parser_manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    by_key: dict[tuple[str, str], Counter[str]] = {}
    for entry in parser_manifest.get("files", []) or []:
        file_type = canonical_file_type(entry.get("file_type"))
        for task in entry.get("parser_tasks") or []:
            parser = task.get("parser_name")
            if not parser:
                continue
            key = (file_type, str(parser))
            status = str(task.get("result_status") or task.get("status") or "UNKNOWN").upper()
            counter = by_key.setdefault(key, Counter())
            counter["tasks"] += 1
            if status == "FAILED":
                counter["failed"] += 1
            elif status == "PASS_EMPTY":
                counter["empty"] += 1
                counter["parsed"] += 1
            else:
                counter["parsed"] += 1
    rows: list[dict[str, Any]] = []
    for (file_type, parser), counter in sorted(by_key.items()):
        status = "FAILED" if counter["failed"] else "PASS_EMPTY" if counter["empty"] else "PASS"
        rows.append(
            {
                "file_type": file_type,
                "parser": parser,
                "tasks": counter["tasks"],
                "parsed": counter["parsed"],
                "empty": counter["empty"],
                "failed": counter["failed"],
                "status": status,
            }
        )
    return rows


def build_scan_review_evidence(bundle: Any, context: Any) -> dict[str, Any]:
    files = list((bundle.file_inventory or {}).get("files", []) or [])
    parser_manifest = bundle.parser_manifest or {}
    parser_by_file = _parser_status_by_file(parser_manifest)

    files_by_view: list[dict[str, Any]] = []
    unknown_files: list[dict[str, Any]] = []
    large_metadata_files: list[dict[str, Any]] = []
    view_counts: Counter[str] = Counter()
    file_type_counts: Counter[str] = Counter()
    evidence_by_view: dict[str, set[str]] = {}

    for record in files:
        file_type = canonical_file_type(record.get("file_type"))
        view_type = canonical_view_type(file_type)
        evidence_level = evidence_level_for_file_type(file_type)
        path = str(record.get("path") or "")
        size = int(record.get("size_bytes") or 0)
        parser_state = parser_by_file.get(path, {"status": "SKIPPED", "parsers": "", "task_count": 0})
        view_counts[view_type] += 1
        file_type_counts[file_type] += 1
        evidence_by_view.setdefault(view_type, set()).add(evidence_level)
        row = {
            "view_type": view_type,
            "view_label": view_label(view_type),
            "usage_area": usage_area_for_view(view_type),
            "file_type": file_type,
            "role": record.get("role") or "",
            "size_bytes": size,
            "evidence_level": evidence_level,
            "parser_status": parser_state.get("status"),
            "path": path,
        }
        files_by_view.append(row)
        if file_type == "unknown":
            unknown_files.append(
                {
                    "path": path,
                    "extension": record.get("extension") or "",
                    "size_bytes": size,
                    "suggested_action": "classify",
                    "reason": "未命中文件类型规则，需要补规则或人工确认可忽略。",
                }
            )
        if evidence_level in {"summary_only", "metadata_only"}:
            policy = (
                "摘要级证据：按数量、路径、corner 和轻量摘要审查，不默认全文深读。"
                if evidence_level == "summary_only"
                else "元数据级证据：按大小、hash/路径和文件存在性审查，不默认读取二进制内容。"
            )
            large_metadata_files.append(
                {
                    "view_type": view_type,
                    "view_label": view_label(view_type),
                    "path": path,
                    "size_bytes": size,
                    "evidence_level": evidence_level,
                    "review_policy": policy,
                }
            )

    view_types = set(view_counts) | REQUIRED_REVIEW_VIEWS
    view_coverage: list[dict[str, Any]] = []
    for view_type in sorted(view_types, key=view_sort_key):
        count = int(view_counts.get(view_type, 0))
        required = view_type in REQUIRED_REVIEW_VIEWS
        levels = evidence_by_view.get(view_type, set())
        raw_types = sorted({row["file_type"] for row in files_by_view if row["view_type"] == view_type})
        view_coverage.append(
            {
                "view_type": view_type,
                "view_label": view_label(view_type),
                "file_type": ",".join(raw_types),
                "count": count,
                "required": "yes" if required else "no",
                "evidence_level": ",".join(sorted(levels)) if levels else "missing",
                "status": _status_for_view(view_type, count, required, levels),
                "meaning": _meaning(view_type, levels, required),
            }
        )

    parser_evidence = _parser_evidence_rows(parser_manifest)
    required_missing = [row["view_type"] for row in view_coverage if row["required"] == "yes" and int(row["count"] or 0) == 0]
    scan_review = {
        "schema_version": "scan_review_evidence.v1",
        "scan_id": _get(context, "scan_id", (bundle.scan_meta or {}).get("scan_id")),
        "library": _get(context, "library_name", (bundle.scan_meta or {}).get("library_name")),
        "version": _get(context, "version", (bundle.scan_meta or {}).get("release_version")),
        "status": (bundle.scan_meta or {}).get("status") or (bundle.manifest or {}).get("status"),
        "total_files": len(files),
        "view_count": len([row for row in view_coverage if int(row["count"] or 0)]),
        "unknown_files": len(unknown_files),
        "large_metadata_files": len(large_metadata_files),
        "parser_failed": sum(int(row["failed"] or 0) for row in parser_evidence),
        "required_missing": required_missing,
        "human_tables": {
            "view_coverage": "review/view_coverage.tsv",
            "files_by_view": "review/files_by_view.tsv",
            "unknown_files": "review/unknown_files.tsv",
            "large_metadata_files": "review/large_metadata_files.tsv",
            "parser_evidence": "review/parser_evidence.tsv",
            "required_view_check": "review/required_view_check.tsv",
        },
    }
    required_view_check = [
        {
            "view_type": row["view_type"],
            "view_label": row["view_label"],
            "required": row["required"],
            "count": row["count"],
            "status": "MISSING" if row["required"] == "yes" and int(row["count"] or 0) == 0 else "PASS",
            "meaning": row["meaning"],
        }
        for row in view_coverage
        if row["required"] == "yes"
    ]
    return {
        "scan_review": scan_review,
        "view_coverage": view_coverage,
        "files_by_view": sorted(files_by_view, key=lambda row: (view_sort_key(row["view_type"]), row["file_type"], row["path"])),
        "unknown_files": unknown_files,
        "large_metadata_files": large_metadata_files,
        "parser_evidence": parser_evidence,
        "required_view_check": required_view_check,
    }


def write_scan_review_evidence(out_dir: str | Path, bundle: Any, context: Any) -> dict[str, str]:
    out = Path(out_dir)
    review = out / "review"
    data = build_scan_review_evidence(bundle, context)
    _write_json(review / "scan_review.json", data["scan_review"])
    _write_tsv(
        review / "view_coverage.tsv",
        ["view_type", "view_label", "file_type", "count", "required", "evidence_level", "status", "meaning"],
        data["view_coverage"],
    )
    _write_tsv(
        review / "files_by_view.tsv",
        ["view_type", "view_label", "usage_area", "file_type", "role", "size_bytes", "evidence_level", "parser_status", "path"],
        data["files_by_view"],
    )
    _write_tsv(review / "unknown_files.tsv", ["path", "extension", "size_bytes", "suggested_action", "reason"], data["unknown_files"])
    _write_tsv(
        review / "large_metadata_files.tsv",
        ["view_type", "view_label", "path", "size_bytes", "evidence_level", "review_policy"],
        data["large_metadata_files"],
    )
    _write_tsv(
        review / "parser_evidence.tsv",
        ["file_type", "parser", "tasks", "parsed", "empty", "failed", "status"],
        data["parser_evidence"],
    )
    _write_tsv(
        review / "required_view_check.tsv",
        ["view_type", "view_label", "required", "count", "status", "meaning"],
        data["required_view_check"],
    )
    return {
        "scan_review": str(review / "scan_review.json"),
        "view_coverage": str(review / "view_coverage.tsv"),
        "files_by_view": str(review / "files_by_view.tsv"),
        "unknown_files": str(review / "unknown_files.tsv"),
        "large_metadata_files": str(review / "large_metadata_files.tsv"),
        "parser_evidence": str(review / "parser_evidence.tsv"),
        "required_view_check": str(review / "required_view_check.tsv"),
    }
