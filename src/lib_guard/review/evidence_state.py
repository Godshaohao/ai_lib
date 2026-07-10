from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "version_evidence_state.v1"


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _exists(value: Any) -> bool:
    if not value:
        return False
    try:
        return Path(str(value)).exists()
    except OSError:
        return False


def _status_from_exists(path: Any, *, expected: bool = True) -> str:
    if not expected:
        return "NOT_APPLICABLE"
    return "PRESENT" if _exists(path) else "MISSING"


def _status_rank(status: str) -> int:
    return {
        "PRESENT": 0,
        "GENERATED": 0,
        "PROJECTION": 0,
        "PARTIAL": 1,
        "NOT_APPLICABLE": 1,
        "MISSING": 2,
        "STALE_OR_MISSING": 2,
        "UNKNOWN": 2,
    }.get(str(status or "UNKNOWN").upper(), 2)


def _scan_paths(version: Mapping[str, Any]) -> dict[str, str]:
    scan = _as_mapping(version.get("scan"))
    scan_dir = str(scan.get("scan_dir") or "")
    review_dir = str(Path(scan_dir) / "review") if scan_dir else ""
    return {
        "scan_dir": scan_dir,
        "scan_html": str(scan.get("scan_html") or ""),
        "scan_review": str(Path(review_dir) / "scan_review.json") if review_dir else "",
        "view_coverage": str(Path(review_dir) / "view_coverage.tsv") if review_dir else "",
        "files_by_view": str(Path(review_dir) / "files_by_view.tsv") if review_dir else "",
        "unknown_files": str(Path(review_dir) / "unknown_files.tsv") if review_dir else "",
        "large_metadata_files": str(Path(review_dir) / "large_metadata_files.tsv") if review_dir else "",
        "parser_evidence": str(Path(review_dir) / "parser_evidence.tsv") if review_dir else "",
    }


def _diff_paths(version: Mapping[str, Any]) -> dict[str, str]:
    diff = _as_mapping(version.get("diff"))
    diff_dir = str(
        diff.get("base_diff_dir")
        or diff.get("diff_dir")
        or diff.get("adjacent_diff_dir")
        or diff.get("cumulative_diff_dir")
        or ""
    )
    return {
        "diff_dir": diff_dir,
        "diff_html": str(diff.get("base_diff_html") or diff.get("diff_html") or diff.get("adjacent_diff_html") or diff.get("cumulative_diff_html") or ""),
        "diff_summary": str(Path(diff_dir) / "diff_summary.json") if diff_dir else "",
        "view_diff": str(Path(diff_dir) / "view_diff.json") if diff_dir else "",
        "file_diff": str(Path(diff_dir) / "file_diff.json") if diff_dir else "",
        "diff_issues": str(Path(diff_dir) / "diff_issues.json") if diff_dir else "",
    }


def _review_context_paths(review_context: Mapping[str, Any]) -> dict[str, str]:
    return {
        "window_file": str(review_context.get("window_file") or ""),
        "candidate_effective_manifest": str(review_context.get("candidate_effective_manifest") or ""),
        "candidate_effective_html": str(review_context.get("candidate_effective_html") or ""),
        "compare_manifest": str(review_context.get("compare_manifest") or ""),
        "compare_html": str(review_context.get("compare_html") or ""),
    }


def _source(
    *,
    name: str,
    role: str,
    status: str,
    owner: str,
    primary_artifact: str = "",
    artifacts: Mapping[str, str] | None = None,
    message: str = "",
) -> dict[str, Any]:
    return {
        "name": name,
        "role": role,
        "status": status,
        "owner": owner,
        "primary_artifact": primary_artifact,
        "artifacts": dict(artifacts or {}),
        "message": message,
    }


def build_version_evidence_state(
    *,
    library: Mapping[str, Any],
    version: Mapping[str, Any],
    review_context: Mapping[str, Any] | None = None,
    render_output: str | Path | None = None,
) -> dict[str, Any]:
    """Build a source-of-truth map for one Version Detail projection.

    This model does not create a new fact source. It explains how existing
    catalog, scan, diff, effective/window, and render projection artifacts are
    used by the page. Render output is deliberately marked as projection, not
    source.
    """

    ctx = _as_mapping(review_context)
    scan = _scan_paths(version)
    diff = _diff_paths(version)
    window = _review_context_paths(ctx)
    catalog_status = "PRESENT" if version else "MISSING"
    scan_status = "PRESENT" if _exists(scan["scan_dir"]) else "MISSING"
    scan_review_status = "PRESENT" if _exists(scan["view_coverage"]) and _exists(scan["files_by_view"]) else ("PARTIAL" if _exists(scan["scan_dir"]) else "MISSING")
    diff_status = "PRESENT" if _exists(diff["diff_summary"]) or _exists(diff["view_diff"]) else ("MISSING" if diff["diff_dir"] else "NOT_APPLICABLE")
    window_status = "PRESENT" if _exists(window["window_file"]) else "NOT_APPLICABLE"
    effective_status = "PRESENT" if _exists(window["candidate_effective_manifest"]) else ("NOT_APPLICABLE" if not window["candidate_effective_manifest"] else "MISSING")
    render_status = "PROJECTION" if render_output else "NOT_APPLICABLE"

    sources = [
        _source(
            name="catalog",
            role="库和版本资产地图",
            status=catalog_status,
            owner="catalog/library registry",
            primary_artifact=str(version.get("version_uid") or version.get("version_key") or version.get("version_id") or ""),
            artifacts={
                "library": str(library.get("formal_library_id") or library.get("library_name") or library.get("library_id") or ""),
                "version": str(version.get("version_id") or version.get("version_key") or ""),
                "raw_path": str(version.get("raw_path") or ""),
            },
            message="Catalog 只说明有哪些库/版本和原始路径，不证明版本可用。",
        ),
        _source(
            name="scan",
            role="单版本扫描事实",
            status=scan_status,
            owner="scan runner",
            primary_artifact=scan["scan_dir"],
            artifacts=scan,
            message="Scan 说明当前版本目录有什么；人工表在 review/*.tsv，raw JSON 只作机器事实。",
        ),
        _source(
            name="scan_review_tables",
            role="人工可读扫描证据",
            status=scan_review_status,
            owner="scan evidence exporter",
            primary_artifact=scan["view_coverage"],
            artifacts={key: value for key, value in scan.items() if key not in {"scan_dir", "scan_html"}},
            message="View 覆盖、文件清单、unknown 和大文件策略应优先从这些表进入页面。",
        ),
        _source(
            name="diff",
            role="相对基准的变化事实",
            status=diff_status,
            owner="diff/compare",
            primary_artifact=diff["diff_summary"] or diff["diff_dir"],
            artifacts=diff,
            message="Diff 只在基准可信时用于变化判断；缺失时不能伪装成无变化。",
        ),
        _source(
            name="effective_window",
            role="当前有效版和接入窗口",
            status="PARTIAL" if window_status == "PRESENT" and effective_status != "PRESENT" else window_status,
            owner="window/effective",
            primary_artifact=window["window_file"] or window["candidate_effective_manifest"],
            artifacts=window,
            message="Window/effective 负责说明候选组合和当前审查对象，不替代 scan/diff。",
        ),
        _source(
            name="html_render",
            role="用户看到的投影",
            status=render_status,
            owner="render",
            primary_artifact=str(render_output or ""),
            artifacts={"html": str(render_output or "")},
            message="HTML 是投影，不是事实源；页面 stale 时应回到上面的证据源重建。",
        ),
    ]
    worst = max(sources, key=lambda item: _status_rank(str(item.get("status") or "UNKNOWN")))
    return {
        "schema_version": SCHEMA_VERSION,
        "library": str(library.get("formal_library_id") or library.get("library_name") or library.get("library_id") or ""),
        "version": str(version.get("version_id") or version.get("version_key") or ""),
        "overall_status": str(worst.get("status") or "UNKNOWN"),
        "sources": sources,
        "principle": "catalog/scan/diff/effective-window 是事实输入；HTML render 只是投影。",
    }
