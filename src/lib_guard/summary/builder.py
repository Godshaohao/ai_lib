"""
lib_guard.summary.builder

Rebuild dashboard/release-input summaries from an existing scan output.

This module is intentionally scan-output based. It does not walk raw library and
it does not re-run parsers. It is used when summary scripts change but parser
results / file inventory are already valid.
"""

from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Mapping
import json
import os
import shutil
import tempfile


DEFAULT_AFFECTED_SUMMARY_MAP = {
    "lef": ["lef_summary", "macro_summary", "port_summary"],
    "liberty": ["liberty_summary", "macro_summary", "port_summary"],
    "verilog": ["verilog_summary", "port_summary"],
    "systemverilog": ["verilog_summary", "port_summary"],
    "cdl": ["cdl_summary", "port_summary"],
    "sdc": ["sdc_summary"],
    "upf": ["upf_summary"],
    "cpf": ["cpf_summary"],
    "spef": ["spef_summary"],
    "package": ["package_summary"],
    "ibis": ["package_summary"],
    "touchstone": ["package_summary"],
    "waiver": ["waiver_summary"],
    "doc": ["doc_summary"],
}


def utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")


def read_json(path: str | Path, default: Any = None) -> Any:
    p = Path(path)
    if not p.exists():
        return default
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


def atomic_write_json(path: str | Path, data: Any) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=p.name, suffix=".tmp", dir=str(p.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp_name, p)
    finally:
        try:
            if os.path.exists(tmp_name):
                os.remove(tmp_name)
        except OSError:
            pass


def atomic_write_text(path: str | Path, text: str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=p.name, suffix=".tmp", dir=str(p.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            if not text.endswith("\n"):
                f.write("\n")
        os.replace(tmp_name, p)
    finally:
        try:
            if os.path.exists(tmp_name):
                os.remove(tmp_name)
        except OSError:
            pass


def load_policy(policy_path: str | Path | None) -> dict[str, Any]:
    if not policy_path:
        return {"affected_summary_map": DEFAULT_AFFECTED_SUMMARY_MAP}
    data = read_json(policy_path, default={}) or {}
    data.setdefault("affected_summary_map", DEFAULT_AFFECTED_SUMMARY_MAP)
    return data


def affected_summary_types(file_type: str, policy_path: str | Path | None = None) -> list[str]:
    policy = load_policy(policy_path)
    amap = policy.get("affected_summary_map", {}) or {}
    return list(amap.get(file_type, []))


def _count_by(files: list[dict[str, Any]], key: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for item in files:
        value = str(item.get(key, "unknown"))
        out[value] = out.get(value, 0) + 1
    return dict(sorted(out.items(), key=lambda x: (-x[1], x[0])))


def _load_summaries(scan_dir: Path) -> dict[str, Any]:
    out: dict[str, Any] = {}
    summaries_dir = scan_dir / "summaries"
    if not summaries_dir.exists():
        return out
    for path in sorted(summaries_dir.glob("*.json")):
        out[path.stem] = read_json(path, default={}) or {}
    return out


def _backup_summaries(scan_dir: Path) -> str | None:
    summaries_dir = scan_dir / "summaries"
    if not summaries_dir.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = scan_dir / "summaries_backup" / stamp
    backup_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(summaries_dir, backup_dir, dirs_exist_ok=True)
    return str(backup_dir)


def _doc_flags(files: list[dict[str, Any]], summaries: dict[str, Any]) -> dict[str, Any]:
    docs = []
    doc_summary = summaries.get("doc_summary") or {}
    if isinstance(doc_summary, Mapping):
        docs = list(doc_summary.get("docs") or [])
    if not docs:
        docs = [f for f in files if f.get("file_type") in {"doc", "waiver"} or f.get("is_key_doc")]

    def has_doc(*terms: str) -> bool:
        for d in docs:
            text = " ".join(str(d.get(k, "")) for k in ["path", "abs_path", "role", "doc_type", "name"]).lower()
            if any(t in text for t in terms):
                return True
        return False

    return {
        "doc_count": len(docs),
        "readme_found": has_doc("readme"),
        "release_note_found": has_doc("release_note", "release note", "release-notes", "releasenote"),
        "update_note_found": has_doc("update_note", "update note", "changelog", "change_log", "change log"),
        "integration_guide_found": has_doc("integration", "user_guide", "user guide"),
        "known_issue_found": has_doc("known_issue", "known issue", "errata"),
        "docs": docs[:200],
    }


def _summary_coverage(summaries: dict[str, Any]) -> dict[str, bool]:
    expected = [
        "lef_summary", "liberty_summary", "verilog_summary", "cdl_summary",
        "sdc_summary", "upf_summary", "cpf_summary", "spef_summary",
        "package_summary", "waiver_summary", "macro_summary", "port_summary", "doc_summary",
    ]
    return {name: bool(summaries.get(name)) for name in expected}


def _normalize_summary_requests(types: list[str] | None, all_summaries: bool, exclude: list[str] | None, policy_path: str | Path | None) -> set[str] | None:
    excluded = {x if x.endswith("_summary") else f"{x}_summary" for x in (exclude or [])}
    if all_summaries:
        return None
    requested: set[str] = set()
    for item in types or []:
        if item.endswith("_summary"):
            requested.add(item)
        else:
            mapped = affected_summary_types(item, policy_path=policy_path)
            if mapped:
                requested.update(mapped)
            else:
                requested.add(f"{item}_summary")
    return requested - excluded


def _rebuild_parser_summaries(
    scan_dir: Path,
    *,
    types: list[str] | None,
    all_summaries: bool,
    exclude: list[str] | None,
    policy_path: str | Path | None,
) -> list[str]:
    parser_results = read_json(scan_dir / "parser_results.json", default={}) or {}
    inventory = read_json(scan_dir / "file_inventory.json", default={}) or {}
    records = list(inventory.get("files") or [])
    selected = _normalize_summary_requests(types, all_summaries, exclude, policy_path)
    if selected == set():
        return []

    from lib_guard.summary.builders import build_default_summary_builders

    summaries_dir = scan_dir / "summaries"
    summaries_dir.mkdir(parents=True, exist_ok=True)
    context = read_json(scan_dir / "scan_meta.json", default={}) or {}
    rebuilt: list[str] = []
    for builder in build_default_summary_builders(None):
        name = str(getattr(builder, "name", builder.__class__.__name__))
        if selected is not None and name not in selected:
            continue
        if name in {x if x.endswith("_summary") else f"{x}_summary" for x in (exclude or [])}:
            continue
        summary = builder.build(records=records, parser_results=parser_results, context=context)
        atomic_write_json(summaries_dir / f"{name}.json", summary)
        rebuilt.append(name)
    return rebuilt


def build_dashboard_summary(scan_dir: str | Path) -> dict[str, Any]:
    scan_dir = Path(scan_dir)
    scan_meta = read_json(scan_dir / "scan_meta.json", default={}) or {}
    manifest = read_json(scan_dir / "manifest.json", default={}) or {}
    inventory = read_json(scan_dir / "file_inventory.json", default={}) or {}
    parser_manifest = read_json(scan_dir / "parser_manifest.json", default={}) or {}
    issues = read_json(scan_dir / "scan_issues.json", default={}) or {}
    integrity = read_json(scan_dir / "integrity.json", default={}) or {}
    summaries = _load_summaries(scan_dir)
    files = list(inventory.get("files") or [])

    parser_tasks = []
    for f in parser_manifest.get("files", []) or []:
        for t in f.get("parser_tasks", []) or []:
            parser_tasks.append(t)

    parsed = [t for t in parser_tasks if str(t.get("result_status", t.get("status", ""))).upper() in {"PASS", "PASS_EMPTY", "METADATA_ONLY"}]
    failed = [t for t in parser_tasks if str(t.get("result_status", t.get("status", ""))).upper() == "FAILED"]
    cache_hits = [t for t in parser_tasks if t.get("cache_used") is True]

    dashboard = {
        "schema_version": "1.0",
        "generated_at": utc_now(),
        "source_scan": str(scan_dir),
        "library": {
            "library_id": scan_meta.get("library_id"),
            "library_type": scan_meta.get("library_type"),
            "library_name": scan_meta.get("library_name"),
            "version": scan_meta.get("release_version"),
            "root_path": scan_meta.get("root_path"),
            "out_dir": scan_meta.get("out_dir"),
        },
        "scan": {
            "scan_id": scan_meta.get("scan_id"),
            "mode": scan_meta.get("scan_mode"),
            "status": scan_meta.get("status"),
            "created_at": scan_meta.get("created_at"),
            "completed_at": scan_meta.get("completed_at"),
        },
        "counts": {
            "total_files": len(files),
            "key_files": len([f for f in files if f.get("is_key_file")]),
            "file_type_counts": _count_by(files, "file_type"),
            "domain_counts": _count_by(files, "domain"),
            "role_counts": _count_by(files, "role"),
            "parser_tasks": len([t for t in parser_tasks if t.get("parser_name")]),
            "parsed_tasks": len(parsed),
            "parser_cache_hits": len(cache_hits),
            "parser_failed_tasks": len(failed),
        },
        "state_delta": read_json(scan_dir / "state_delta.json", default={}) or {},
        "issues": issues,
        "integrity": integrity,
        "docs": _doc_flags(files, summaries),
        "summary_coverage": _summary_coverage(summaries),
        "manifest_summary": manifest.get("summary", {}),
    }
    return dashboard


def build_release_input_summary(scan_dir: str | Path, policy_path: str | Path | None = None) -> dict[str, Any]:
    scan_dir = Path(scan_dir)
    dashboard = build_dashboard_summary(scan_dir)
    files = read_json(scan_dir / "file_inventory.json", default={}) or {}
    file_list = list(files.get("files") or [])
    scan_meta = read_json(scan_dir / "scan_meta.json", default={}) or {}
    issues = read_json(scan_dir / "scan_issues.json", default={}) or {}
    parser_quality = read_json(scan_dir / "summary" / "parser_quality.json", default={}) or {}
    release_readiness = read_json(scan_dir / "summary" / "release_readiness.json", default={}) or {}

    present_types = {str(f.get("file_type")) for f in file_list}
    release_input = {
        "schema_version": "1.0",
        "generated_at": utc_now(),
        "source_scan": str(scan_dir),
        "library_id": dashboard["library"].get("library_id"),
        "scan_id": dashboard["scan"].get("scan_id"),
        "scan_status": dashboard["scan"].get("status"),
        "library": dashboard["library"],
        "required_views": {ft: (ft in present_types) for ft in sorted(present_types | {"verilog", "lef", "liberty", "db", "cdl", "sdc", "upf", "cpf"})},
        "docs": {k: v for k, v in dashboard["docs"].items() if k != "docs"},
        "issues": issues.get("summary", {}),
        "parser": {
            "parser_tasks": dashboard["counts"].get("parser_tasks", 0),
            "parsed_tasks": dashboard["counts"].get("parsed_tasks", 0),
            "parser_cache_hits": dashboard["counts"].get("parser_cache_hits", 0),
            "parser_failed_tasks": dashboard["counts"].get("parser_failed_tasks", 0),
            "quality_status": parser_quality.get("status"),
            "quality": parser_quality,
        },
        "summary_coverage": dashboard.get("summary_coverage", {}),
        "release_readiness": {
            "bundle_status": release_readiness.get("bundle_status"),
            "release_channel": release_readiness.get("release_channel"),
            "summary": release_readiness.get("summary", {}),
            "blocking_items": release_readiness.get("blocking_items", []),
            "manual_review_items": release_readiness.get("manual_review_items", []),
        },
        "scan_meta": {
            "root_path": scan_meta.get("root_path"),
            "out_dir": scan_meta.get("out_dir"),
            "mode": scan_meta.get("scan_mode"),
        },
    }
    return release_input


def write_summary_report(scan_dir: str | Path, dashboard: dict[str, Any], release_input: dict[str, Any]) -> None:
    scan_dir = Path(scan_dir)
    lines = [
        "# lib_guard Summary Report",
        "",
        f"- Library ID: `{dashboard['library'].get('library_id')}`",
        f"- Scan ID: `{dashboard['scan'].get('scan_id')}`",
        f"- Mode: `{dashboard['scan'].get('mode')}`",
        f"- Status: `{dashboard['scan'].get('status')}`",
        f"- Root: `{dashboard['library'].get('root_path')}`",
        "",
        "## Counts",
        "",
        f"- Total files: `{dashboard['counts'].get('total_files')}`",
        f"- Key files: `{dashboard['counts'].get('key_files')}`",
        f"- Parser tasks: `{dashboard['counts'].get('parser_tasks')}`",
        f"- Parsed tasks: `{dashboard['counts'].get('parsed_tasks')}`",
        f"- Cache hits: `{dashboard['counts'].get('parser_cache_hits')}`",
        f"- Parser failed tasks: `{dashboard['counts'].get('parser_failed_tasks')}`",
        "",
        "## Documents / 文档",
        "",
        f"- README found: `{release_input['docs'].get('readme_found')}`",
        f"- Release note found: `{release_input['docs'].get('release_note_found')}`",
        f"- Update note found: `{release_input['docs'].get('update_note_found')}`",
        f"- Integration guide found: `{release_input['docs'].get('integration_guide_found')}`",
        "",
        "## Summary Coverage",
        "",
    ]
    for name, present in sorted(dashboard.get("summary_coverage", {}).items()):
        lines.append(f"- {name}: `{present}`")
    atomic_write_text(scan_dir / "summary" / "summary_report.md", "\n".join(lines))


def rebuild_summary_from_scan(
    scan_dir: str | Path,
    *,
    types: list[str] | None = None,
    all_summaries: bool = False,
    exclude: list[str] | None = None,
    policy_path: str | Path | None = None,
    backup: bool = True,
) -> dict[str, Any]:
    scan_dir = Path(scan_dir)
    if not scan_dir.exists():
        raise FileNotFoundError(f"scan_dir not found: {scan_dir}")

    backup_dir = _backup_summaries(scan_dir) if backup else None
    summary_dir = scan_dir / "summary"
    summary_dir.mkdir(parents=True, exist_ok=True)

    rebuilt_summaries = _rebuild_parser_summaries(
        scan_dir,
        types=types,
        all_summaries=all_summaries,
        exclude=exclude or [],
        policy_path=policy_path,
    )
    dashboard = build_dashboard_summary(scan_dir)
    from lib_guard.summary.readiness import build_release_readiness

    release_readiness = build_release_readiness(scan_dir, policy_path=policy_path)
    atomic_write_json(summary_dir / "release_readiness.json", release_readiness)
    release_input = build_release_input_summary(scan_dir, policy_path=policy_path)
    atomic_write_json(summary_dir / "dashboard_summary.json", dashboard)
    atomic_write_json(summary_dir / "release_input_summary.json", release_input)
    write_summary_report(scan_dir, dashboard, release_input)

    result = {
        "schema_version": "1.0",
        "status": "PASS",
        "generated_at": utc_now(),
        "source_scan": str(scan_dir),
        "backup_dir": backup_dir,
        "types_requested": types or [],
        "all_summaries": all_summaries,
        "exclude": exclude or [],
        "rebuilt_summaries": rebuilt_summaries,
        "outputs": {
            "dashboard_summary": str(summary_dir / "dashboard_summary.json"),
            "release_input_summary": str(summary_dir / "release_input_summary.json"),
            "release_readiness": str(summary_dir / "release_readiness.json"),
            "summary_report": str(summary_dir / "summary_report.md"),
        },
        "note": "This command rebuilds v5 parser summaries plus dashboard/release input summaries from existing scan output.",
    }
    atomic_write_json(summary_dir / "summary_rebuild.json", result)
    return result


def build_summary_from_scan(scan_dir: str | Path, **kwargs: Any) -> dict[str, Any]:
    return rebuild_summary_from_scan(scan_dir, all_summaries=True, **kwargs)
