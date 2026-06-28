from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Mapping
import json

from lib_guard.project_config import CONTROL_CONFIG_SPECS as CONFIG_SPECS, PROJECT_CONFIG_DIR


def utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")


def read_json(path: str | Path, default: Any = None) -> Any:
    p = Path(path)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: str | Path, data: Any) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")


def _count_by(items: list[Mapping[str, Any]], key: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for item in items:
        value = str(item.get(key, "unknown"))
        out[value] = out.get(value, 0) + 1
    return dict(sorted(out.items()))


def _flatten_config(prefix: str, value: Any) -> list[tuple[str, Any]]:
    if isinstance(value, Mapping):
        out: list[tuple[str, Any]] = []
        for key, sub in value.items():
            out.extend(_flatten_config(f"{prefix}.{key}" if prefix else str(key), sub))
        return out
    return [(prefix, value)]


def build_config_view(config_dir: str | Path = PROJECT_CONFIG_DIR) -> dict[str, Any]:
    config_root = Path(config_dir)
    configs: list[dict[str, Any]] = []
    for group, rel_source, editable, impact, actions in CONFIG_SPECS:
        path = config_root / Path(rel_source).name
        data = read_json(path, default=None)
        if data is None:
            configs.append(
                {
                    "name": group,
                    "value": None,
                    "source": str(path),
                    "present": False,
                    "user_editable": editable,
                    "impact": impact,
                    "requires_action_after_change": actions,
                    "suggestion": "Create this config only if the project needs custom policy.",
                }
            )
            continue
        for name, value in _flatten_config(group, data):
            configs.append(
                {
                    "name": name,
                    "value": value,
                    "source": str(path),
                    "present": True,
                    "user_editable": editable,
                    "impact": impact,
                    "requires_action_after_change": actions,
                    "suggestion": _config_suggestion(name),
                }
            )
    return {"schema_version": "1.0", "generated_at": utc_now(), "configs": configs}


def _config_suggestion(name: str) -> str:
    if name.startswith("catalog_policy."):
        return "After changing this item, rerun catalog scan/render; scan evidence is only required when discovered versions or file evidence change."
    if name.startswith("release_policy."):
        return "After changing this item, rerun release check; scan is usually not required."
    if name.startswith("scan_policy.") or name.startswith("file_patterns.") or name.startswith("ignore_rules."):
        return "After changing this item, rerun scan for affected libraries."
    return "Review impact before changing this item."


def build_parser_quality(scan_dir: str | Path) -> dict[str, Any]:
    scan = Path(scan_dir)
    existing = read_json(scan / "summary" / "parser_quality.json", default=None)
    if isinstance(existing, Mapping) and existing.get("parsers") is not None:
        return dict(existing)
    manifest = read_json(scan / "parser_manifest.json", default={}) or {}
    parser_results = read_json(scan / "parser_results.json", default={}) or {}
    by_parser: dict[str, dict[str, Any]] = {}
    for file_entry in manifest.get("files", []) or []:
        file_path = file_entry.get("file")
        file_type = file_entry.get("file_type")
        for task in file_entry.get("parser_tasks", []) or []:
            parser_name = task.get("parser_name") or "UNSUPPORTED"
            item = by_parser.setdefault(
                parser_name,
                {
                    "parser_name": parser_name,
                    "parser_version": task.get("parser_version"),
                    "file_types": set(),
                    "parsed_files": 0,
                    "cache_hits": 0,
                    "failed_files": 0,
                    "skipped_files": 0,
                    "pass_empty_files": 0,
                    "object_count": 0,
                    "empty_examples": [],
                    "failed_examples": [],
                },
            )
            item["file_types"].add(str(file_type))
            status = str(task.get("result_status", task.get("status", ""))).upper()
            if status in {"PASS", "PASS_EMPTY", "METADATA_ONLY"}:
                item["parsed_files"] += 1
                if task.get("cache_used"):
                    item["cache_hits"] += 1
                result = parser_results.get(task.get("result_path")) or parser_results.get(f"{file_path}::{parser_name}") or {}
                object_count = _parser_object_count(result)
                item["object_count"] += object_count
                if status == "PASS_EMPTY" or object_count == 0:
                    item["pass_empty_files"] += 1
                    if len(item["empty_examples"]) < 5:
                        item["empty_examples"].append(file_path)
            elif status == "FAILED":
                item["failed_files"] += 1
                if len(item["failed_examples"]) < 5:
                    item["failed_examples"].append(file_path)
            else:
                item["skipped_files"] += 1

    parsers = []
    for item in by_parser.values():
        parsed = int(item["parsed_files"])
        failed = int(item["failed_files"])
        empty = int(item["pass_empty_files"])
        if failed:
            status = "FAILED"
        elif parsed and empty == parsed:
            status = "PASS_EMPTY"
        elif parsed:
            status = "PASS"
        else:
            status = "SKIPPED" if item["parser_name"] != "UNSUPPORTED" else "UNSUPPORTED"
        total = max(parsed + failed + int(item["skipped_files"]), 1)
        quality_score = max(0, int(100 * (parsed - empty - failed) / total))
        parsers.append({**item, "file_types": sorted(item["file_types"]), "status": status, "quality_score": quality_score})
    counts = _count_by(parsers, "status")
    overall = "FAILED" if counts.get("FAILED") else "PASS_WITH_WARNING" if counts.get("PASS_EMPTY") or counts.get("UNSUPPORTED") else "PASS"
    return {"schema_version": "1.0", "generated_at": utc_now(), "status": overall, "parsers": sorted(parsers, key=lambda x: x["parser_name"])}


def _parser_object_count(result: Mapping[str, Any]) -> int:
    data = result.get("data", result) if isinstance(result, Mapping) else {}
    if not isinstance(data, Mapping):
        return 0
    stats = data.get("stats")
    if isinstance(stats, Mapping):
        counts = [int(v) for k, v in stats.items() if str(k).endswith("_count") and isinstance(v, int)]
        if counts:
            return sum(counts)
    for key in ["modules", "macros", "cells", "subckts", "constraints", "nets", "waivers"]:
        value = data.get(key)
        if isinstance(value, Mapping):
            return len(value)
        if isinstance(value, list):
            return len(value)
    return 0


def build_review_items(scan_dir: str | Path, config_dir: str | Path = PROJECT_CONFIG_DIR) -> dict[str, Any]:
    scan = Path(scan_dir)
    meta = read_json(scan / "scan_meta.json", default={}) or {}
    inventory = read_json(scan / "file_inventory.json", default={}) or {}
    parser_manifest = read_json(scan / "parser_manifest.json", default={}) or {}
    release_input = read_json(scan / "summary" / "release_input_summary.json", default=None)
    release_readiness = read_json(scan / "summary" / "release_readiness.json", default={}) or {}
    release_policy = read_json(Path(config_dir) / "release_policy.json", default={}) or {}
    parser_quality = build_parser_quality(scan)
    items: list[dict[str, Any]] = []

    def add(severity: str, category: str, title: str, suggested_action: str, file: str | None = None, command: str | None = None) -> None:
        items.append(
            {
                "review_id": f"RVW-{len(items) + 1:06d}",
                "severity": severity,
                "category": category,
                "title": title,
                "file": file,
                "auto_detected": True,
                "needs_human_decision": severity in {"warning", "error", "blocker"},
                "suggested_action": suggested_action,
                "recommended_command": command,
            }
        )

    library_id = meta.get("library_id")
    mode = meta.get("scan_mode", "signature")
    for f in inventory.get("files", []) or []:
        if f.get("file_type") == "unknown":
            add("warning", "file_inventory", "Unknown file type", "Confirm whether this file should be ignored or mapped in file_patterns.", f.get("path"))

    for file_entry in parser_manifest.get("files", []) or []:
        for task in file_entry.get("parser_tasks", []) or []:
            if str(task.get("result_status", task.get("status", ""))).upper() == "FAILED":
                add("error", "parser_quality", "Parser failed on key file", "Inspect parser error and rerun scan with --rescan after fixing parser support.", file_entry.get("file"))

    required_docs = release_policy.get("required_docs", []) or []
    docs = release_input.get("docs", {}) if isinstance(release_input, Mapping) else {}
    for item in release_readiness.get("blocking_items", []) or []:
        add(
            "blocker",
            "release_readiness",
            item.get("title", "Release readiness blocker"),
            item.get("message", "Review release readiness."),
            command=f"lib_guard release check --latest --library-id {library_id} --mode {mode}",
        )
    for item in release_readiness.get("manual_review_items", []) or []:
        add("warning", "manual_review", item.get("reason", "Manual release review required"), "Record an approval or waiver before promoting this component.")
    for doc in required_docs:
        flag_name = f"{doc}_found"
        if release_input is not None and docs.get(flag_name) is False:
            add("warning", "doc", f"Missing required document: {doc}", "Add the document or confirm a waiver before release.")

    required_types = (release_policy.get("required_views", {}) or {}).get(meta.get("library_type"), [])
    required_set = set(required_types)
    for parser in parser_quality.get("parsers", []):
        if parser.get("status") == "PASS_EMPTY" and required_set.intersection(parser.get("file_types", [])):
            file_type = next(iter(required_set.intersection(parser.get("file_types", []))), "unknown")
            add(
                "blocker",
                "parser_quality",
                f"{parser['parser_name']} returned PASS_EMPTY",
                f"Check whether {file_type} files are valid or parser missed core objects.",
                parser.get("empty_examples", [None])[0],
                "lg.csh scan <library> <version> --rescan",
            )
    return {"schema_version": "1.0", "generated_at": utc_now(), "library_id": library_id, "scan_id": meta.get("scan_id"), "review_items": items}


def build_recommended_actions(review_items: Mapping[str, Any], scan_dir: str | Path) -> dict[str, Any]:
    scan = Path(scan_dir)
    meta = read_json(scan / "scan_meta.json", default={}) or {}
    actions: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in review_items.get("review_items", []) or []:
        command = item.get("recommended_command")
        if command and command not in seen:
            actions.append({"action_id": f"ACT-{len(actions) + 1:06d}", "source_review_id": item.get("review_id"), "title": item.get("title"), "command": command})
            seen.add(command)
    return {"schema_version": "1.0", "generated_at": utc_now(), "recommended_actions": actions}


def build_control_data(scan_dir: str | Path, workdir: str | Path = "work", config_dir: str | Path = PROJECT_CONFIG_DIR) -> dict[str, Any]:
    scan = Path(scan_dir)
    meta = read_json(scan / "scan_meta.json", default={}) or {}
    manifest = read_json(scan / "manifest.json", default={}) or {}
    issues = read_json(scan / "scan_issues.json", default={}) or {}
    release_input = read_json(scan / "summary" / "release_input_summary.json", default=None)
    release_readiness = read_json(scan / "summary" / "release_readiness.json", default={}) or {}
    parser_quality = build_parser_quality(scan)
    review_items = build_review_items(scan, config_dir=config_dir)
    issue_counts = issues.get("summary", {}) if isinstance(issues, Mapping) else {}
    readiness_status = release_readiness.get("bundle_status")
    release_readiness_status = "READY" if release_input and not review_items["review_items"] else "NEEDS_REVIEW"
    if readiness_status == "PASS":
        release_readiness_status = "READY" if not review_items["review_items"] else "NEEDS_REVIEW"
    elif readiness_status == "PASS_WITH_WARNING":
        release_readiness_status = "NEEDS_REVIEW"
    elif readiness_status in {"BLOCK", "FAILED"}:
        release_readiness_status = "BLOCKED"
    if any(item["severity"] == "blocker" for item in review_items["review_items"]):
        release_readiness_status = "BLOCKED"
    release_level = {
        "release_level_candidate": release_readiness.get("release_level_candidate"),
        "validation_depth": release_readiness.get("validation_depth"),
        "doc_parse_status": release_readiness.get("doc_parse_status"),
        "required_view_status": release_readiness.get("required_view_status"),
        "diff_level": release_readiness.get("diff_level"),
        "deep_diff_completed": release_readiness.get("deep_diff_completed"),
        "allowed_aliases": release_readiness.get("allowed_aliases", []),
        "blocked_aliases": release_readiness.get("blocked_aliases", []),
        "limitations": release_readiness.get("limitations", []),
        "doc_summary": release_readiness.get("doc_summary", {}),
    }
    return {
        "schema_version": "1.0",
        "generated_at": utc_now(),
        "meta": {
            "library_id": meta.get("library_id"),
            "library_type": meta.get("library_type"),
            "release_version": meta.get("release_version"),
            "scan_mode": meta.get("scan_mode"),
        },
        "library_id": meta.get("library_id"),
        "library_type": meta.get("library_type"),
        "library_name": meta.get("library_name"),
        "version": meta.get("release_version"),
        "scan_id": meta.get("scan_id"),
        "scan_dir": str(scan),
        "latest_mode": meta.get("scan_mode"),
        "status": {
            "scan": meta.get("status", "UNKNOWN"),
            "summary": "PASS" if release_input else "OPTIONAL",
            "parser_quality": parser_quality.get("status", "UNKNOWN"),
            "release_readiness": release_readiness_status,
        },
        "release_level": release_level,
        "counts": {
            "files": (manifest.get("summary") or {}).get("total_files", 0),
            "parser_tasks": (manifest.get("summary") or {}).get("parser_tasks", 0),
            "warnings": issue_counts.get("warning", 0),
            "errors": issue_counts.get("error", 0),
            "blockers": issue_counts.get("blocker", 0),
            "review_items": len(review_items.get("review_items", [])),
        },
        "pages": {"config": "config.html", "quality": "quality.html", "release": "release.html", "history": "history.html", "review": "review.html"},
    }


def build_approval_snapshot(control_data: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "library_id": control_data.get("library_id"),
        "scan_id": control_data.get("scan_id"),
        "reviewer": "manual",
        "review_time": utc_now(),
        "decisions": [],
    }
