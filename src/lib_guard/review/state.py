from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .commands import derive_next_action
from .evidence_state import build_version_evidence_state
from .io import read_json, utc_now
from .overrides import apply_overrides_to_gate, read_review_overrides


def _versions(lib: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return list(lib.get("versions", []) or [])


def _status_scan(version: Mapping[str, Any]) -> str:
    scan = version.get("scan", {}) or {}
    raw = str(scan.get("status") or "").upper()
    if not scan.get("scan_dir") and not scan.get("scan_html"):
        return "NOT_SCANNED"
    if raw in {"PASS", "SCANNED", "DONE"}:
        return "SCAN_PASS"
    if raw in {"PASS_WITH_WARNING", "WARNING", "WARN"}:
        return "SCAN_WARN"
    if raw in {"BLOCK", "BLOCKED"}:
        return "SCAN_BLOCK"
    if raw in {"FAILED", "ERROR"}:
        return "SCAN_FAILED"
    return "SCAN_PASS" if scan.get("scan_dir") or scan.get("scan_html") else "NOT_SCANNED"


def _diff_dir(version: Mapping[str, Any]) -> str:
    diff = version.get("diff", {}) or {}
    return str(diff.get("base_diff_dir") or diff.get("adjacent_diff_dir") or diff.get("cumulative_diff_dir") or diff.get("diff_dir") or "")


def _diff_html(version: Mapping[str, Any]) -> str:
    diff = version.get("diff", {}) or {}
    return str(diff.get("base_diff_html") or diff.get("adjacent_diff_html") or diff.get("cumulative_diff_html") or diff.get("diff_html") or "")


def _status_diff(version: Mapping[str, Any], scan_status: str) -> str:
    diff = version.get("diff", {}) or {}
    raw_values = [
        str(diff.get("base_status") or "").upper(),
        str(diff.get("adjacent_status") or "").upper(),
        str(diff.get("cumulative_status") or "").upper(),
        str(diff.get("status") or "").upper(),
    ]
    ignored = {"PENDING", "DIFF_PENDING", "NOT_APPLICABLE", "N/A", "NA"}
    raw = next((value for value in raw_values if value and value not in ignored), "")
    if raw in {"SAME", "DIFF_SAME"}:
        return "DIFF_SAME"
    if raw in {"DIFF", "DIFF_DONE", "PASS_WITH_WARNING"}:
        return "DIFF_REVIEW"
    if raw in {"BLOCK", "BLOCKED"}:
        return "DIFF_BLOCK"
    if raw in {"FAILED", "ERROR"}:
        return "DIFF_FAILED"
    if scan_status == "NOT_SCANNED":
        return "DIFF_NOT_READY"
    return "DIFF_PENDING"


def _pairwise_results_for_task(task: Mapping[str, Any]) -> Mapping[str, Any] | None:
    expected = task.get("expected_output")
    if not expected:
        return None
    out = Path(str(expected))
    result = read_json(out / "pairwise_result.json", None)
    if result:
        return result
    if (out / "file_diff_summary.json").exists():
        summary = read_json(out / "file_diff_summary.json", {}) or {}
        return {"status": "DONE", "result": summary.get("status"), "change_count": 1 if summary.get("changed") else 0, "html": str(out / "index.html")}
    return None


def _pairwise(version: Mapping[str, Any]) -> tuple[str, list[dict[str, Any]], dict[str, int]]:
    diff_dir = _diff_dir(version)
    if not diff_dir:
        return "PAIRWISE_EMPTY", [], {"total": 0, "done": 0, "pending": 0, "failed": 0}
    payload = read_json(Path(diff_dir) / "manual_pairwise_tasks.json", None) or read_json(Path(diff_dir) / "pairwise_diff_tasks.json", {"tasks": []}) or {"tasks": []}
    tasks = []
    done = failed = pending = 0
    for task in payload.get("tasks", []) or []:
        item = dict(task)
        result = _pairwise_results_for_task(item)
        if result:
            item["status"] = str(result.get("status") or "DONE")
            item["result"] = result
            if item["status"] == "FAILED":
                failed += 1
            else:
                done += 1
        else:
            item["status"] = item.get("status") or "PENDING"
            pending += 1
        tasks.append(item)
    total = len(tasks)
    if not total:
        return "PAIRWISE_EMPTY", tasks, {"total": 0, "done": 0, "pending": 0, "failed": 0}
    if failed:
        status = "PAIRWISE_FAILED"
    elif done == total:
        status = "PAIRWISE_DONE"
    elif done:
        status = "PAIRWISE_PARTIAL"
    else:
        status = "PAIRWISE_PENDING"
    return status, tasks, {"total": total, "done": done, "pending": pending, "failed": failed}


def _release_result(version: Mapping[str, Any]) -> Mapping[str, Any]:
    release = version.get("release", {}) or {}
    for key in ["release_result", "postcheck_json", "link_json", "manifest_json", "check_json"]:
        value = release.get(key)
        if not value:
            continue
        path = Path(str(value))
        candidate = path if path.name == "release_result.json" else path.parent / "release_result.json"
        result = read_json(candidate, None)
        if result:
            return result
    return {}


def _has_release_evidence(version: Mapping[str, Any]) -> bool:
    release = version.get("release", {}) or {}
    release_status = str(version.get("release_status") or "").upper()
    if version.get("release_candidate") or version.get("selected_for_release"):
        return True
    if release_status and release_status not in {"UNKNOWN", "RELEASE_NOT_CHECKED", "RELEASE_NOT_APPLICABLE", "NOT_APPLICABLE", "NONE"}:
        return True
    for key in [
        "status",
        "check_status",
        "link_status",
        "release_html",
        "release_dir",
        "manifest_json",
        "postcheck_json",
        "release_result",
        "link_json",
        "check_json",
    ]:
        value = release.get(key)
        if value not in (None, "", "UNKNOWN", "RELEASE_NOT_CHECKED", "RELEASE_NOT_APPLICABLE", "NOT_APPLICABLE", "NONE"):
            return True
    return bool(_release_result(version))


def _status_release(version: Mapping[str, Any]) -> str:
    if not _has_release_evidence(version):
        return "RELEASE_NOT_APPLICABLE"
    result = _release_result(version)
    raw = str(result.get("status") or (version.get("release", {}) or {}).get("status") or (version.get("release", {}) or {}).get("check_status") or "").upper()
    if raw in {"APPLIED", "DONE", "FORCED_DONE"}:
        return "RELEASE_APPLIED"
    if raw in {"PASS", "PASS_WITH_WARNING", "READY", "DRY_RUN"}:
        return "RELEASE_READY"
    if raw in {"BLOCK", "BLOCKED"}:
        return "RELEASE_BLOCKED"
    if raw in {"FAILED", "ERROR"}:
        return "RELEASE_VERIFY_FAILED"
    return "RELEASE_NOT_CHECKED"


def _catalog_status(version: Mapping[str, Any]) -> str:
    stage = str(version.get("stage") or "").lower()
    lineage = version.get("lineage", {}) or {}
    parent = lineage.get("parent_candidate") or lineage.get("parent")
    base = version.get("base_version") or lineage.get("base_candidate") or lineage.get("base")
    if stage in {"", "unknown", "unknown_stage"}:
        return "UNKNOWN_STAGE"
    if version.get("manual_review") or (version.get("base_required") and not (parent or base)):
        return "NEED_CONFIRM"
    return "OK"


def _overall(scan: str, diff: str, pairwise: str, release: str, catalog: str) -> str:
    if catalog in {"NEED_CONFIRM", "UNKNOWN_STAGE"}:
        return "REVIEW"
    release_blocks = release not in {"RELEASE_NOT_APPLICABLE", "RELEASE_NOT_CHECKED"} and release in {"RELEASE_BLOCKED", "RELEASE_VERIFY_FAILED"}
    if scan in {"SCAN_BLOCK", "SCAN_FAILED"} or diff in {"DIFF_BLOCK", "DIFF_FAILED"} or pairwise == "PAIRWISE_FAILED" or release_blocks:
        return "BLOCK"
    if diff == "DIFF_REVIEW" and pairwise in {"PAIRWISE_PENDING", "PAIRWISE_PARTIAL"}:
        return "REVIEW"
    if scan == "NOT_SCANNED" or diff in {"DIFF_NOT_READY", "DIFF_PENDING"}:
        return "UNKNOWN"
    if release == "RELEASE_APPLIED" or (scan == "SCAN_PASS" and diff in {"DIFF_SAME", "DIFF_REVIEW"} and pairwise in {"PAIRWISE_EMPTY", "PAIRWISE_DONE"}):
        return "OK"
    return "REVIEW"


def _version_links(out_dir: str | Path | None, lib_name: str, version_id: str, version: Mapping[str, Any]) -> dict[str, str]:
    safe_lib = _safe_name(lib_name)
    safe_ver = _safe_name(version_id)
    return {
        "version_review_html": f"versions/{safe_lib}/{safe_ver}/index.html",
        "scan_html": str((version.get("scan", {}) or {}).get("scan_html") or ""),
        "diff_html": _diff_html(version),
        "pairwise_html": (_diff_html(version) + "#pairwise") if _diff_html(version) else "",
        "release_html": str((version.get("release", {}) or {}).get("release_html") or (version.get("release", {}) or {}).get("postcheck_json") or ""),
    }


def _safe_name(value: Any) -> str:
    import re

    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "item")).strip("._")
    return text or "item"


def _review_root_for_out(out_dir: str | Path | None) -> Path | None:
    if not out_dir:
        return None
    out = Path(out_dir)
    if out.name == "html" and out.parent.name == "catalog":
        return out.parent.parent / "review"
    if out.name == "catalog":
        return out.parent / "review"
    return out / "review"


def review_paths_for_version(out_dir: str | Path | None, lib_name: str, version_id: str) -> dict[str, str]:
    safe_lib = _safe_name(lib_name)
    safe_ver = _safe_name(version_id)
    relative = Path("review") / safe_lib / safe_ver
    root = _review_root_for_out(out_dir)
    if root is None:
        base = relative
    else:
        base = root / safe_lib / safe_ver
    return {
        "override_file": str(base / "review_overrides.json"),
        "gate_file": str(base / "review_gate.json"),
    }


def _gate_item(
    item_id: str,
    *,
    category: str,
    title: str,
    message: str,
    severity: str = "blocker",
    source: str = "",
    fatal: bool = False,
    file: str | None = None,
    rule_id: str = "",
    rule_source: str = "review_gate.v1",
    why: str = "",
    next_action: str = "",
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "id": item_id,
        "severity": severity,
        "category": category,
        "title": title,
        "message": message,
        "blocking": severity.lower() in {"blocker", "error"},
        "fatal": fatal,
        "rule_id": rule_id or item_id.split(":", 1)[0],
        "rule_source": rule_source or "review_gate.v1",
        "why": why or message,
        "next_action": next_action or "Review the evidence and record an accept or waive decision when needed.",
    }
    if source:
        result["source"] = source
    if file:
        result["file"] = file
    return result


def _metadata_gate_items(diff_dir: str, *, limit: int = 20) -> list[dict[str, Any]]:
    if not diff_dir:
        return []
    diff = Path(diff_dir)
    payload = read_json(diff / "metadata_review_tasks.json", {}) or {}
    tasks = payload.get("tasks") if isinstance(payload, Mapping) else []
    items: list[dict[str, Any]] = []
    for task in list(tasks or [])[:limit]:
        if not isinstance(task, Mapping):
            continue
        file_type = str(task.get("file_type") or "metadata")
        path = str(task.get("path") or "")
        change_type = str(task.get("change_type") or "changed")
        item_id = f"metadata.{file_type}.{change_type}:{path or task.get('task_id')}"
        items.append(
            _gate_item(
                item_id,
                category="metadata_only",
                title="Metadata-only view changed",
                message="Binary/metadata-only view changed; human acceptance is required for current.",
                source=str(diff / "metadata_review_tasks.json"),
                file=path,
                rule_id="metadata_only.changed.blocks_current",
                why="DB/GDS/OAS are metadata-only in default scan; semantic safety cannot be proven automatically.",
                next_action="Owner accept/waive or release with --force and audit reason.",
            )
        )
    if items:
        return items

    issues = read_json(diff / "diff_issues.json", {}) or {}
    for idx, issue in enumerate(list((issues.get("issues") if isinstance(issues, Mapping) else []) or [])[:limit], start=1):
        if not isinstance(issue, Mapping):
            continue
        title = str(issue.get("title") or "")
        category = str(issue.get("category") or "")
        if "metadata" not in title.lower() and "metadata" not in category.lower():
            continue
        path = str(issue.get("file") or issue.get("path") or f"issue_{idx}")
        items.append(
            _gate_item(
                f"metadata.review:{path}",
                category="metadata_only",
                title=title or "Metadata-only change needs review",
                message=str(issue.get("message") or "Human acceptance is required for current."),
                source=str(diff / "diff_issues.json"),
                file=path,
                rule_id="metadata_only.changed.blocks_current",
                why="Metadata-only changes cannot be proven semantically safe from the default evidence.",
                next_action="Owner accept/waive or release with --force and audit reason.",
            )
        )
    return items


def build_review_gate_for_version(
    version: Mapping[str, Any],
    *,
    gate: str = "current",
    overrides: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    version_id = str(version.get("version_id") or version.get("version_key") or "unknown")
    lib_name = str(version.get("display_name") or version.get("library_name") or version.get("library_id") or "unknown")
    blocking_items: list[dict[str, Any]] = []
    attention_items: list[dict[str, Any]] = []

    catalog_status = str(version.get("catalog_status") or "")
    if catalog_status in {"NEED_CONFIRM", "UNKNOWN_STAGE"}:
        blocking_items.append(
            _gate_item(
                f"catalog.relation:{version_id}",
                category="catalog_trust",
                title="Catalog relation needs confirmation",
                message="Version stage, parent, base, or package relation is not trusted yet.",
            )
        )

    scan_status = str(version.get("scan_status") or "")
    if scan_status in {"SCAN_BLOCK", "SCAN_FAILED"}:
        blocking_items.append(
            _gate_item(
                f"scan.fatal:{version_id}",
                category="scan",
                title="扫描阻塞或失败",
                message=f"scan_status={scan_status}",
                fatal=True,
            )
        )

    diff_status = str(version.get("diff_status") or "")
    if diff_status in {"DIFF_BLOCK", "DIFF_FAILED"}:
        blocking_items.append(
            _gate_item(
                f"diff.fatal:{version_id}",
                category="diff",
                title="对比阻塞或失败",
                message=f"diff_status={diff_status}",
                fatal=True,
            )
        )

    release_status = str(version.get("release_status") or "")
    if release_status in {"RELEASE_BLOCKED", "RELEASE_VERIFY_FAILED"}:
        blocking_items.append(
            _gate_item(
                f"release.fatal:{version_id}",
                category="release",
                title="发布证据阻塞或失败",
                message=f"release_status={release_status}",
                fatal=True,
            )
        )

    blocking_items.extend(_metadata_gate_items(_diff_dir(version)))

    pairwise_status = str(version.get("pairwise_status") or "")
    pairwise_summary = version.get("pairwise_summary") or {}
    if pairwise_status in {"PAIRWISE_PENDING", "PAIRWISE_PARTIAL"}:
        item = _gate_item(
            f"pairwise.recommended:{version_id}",
            severity="attention",
            category="file_diff",
            title="建议做重点文件深度确认",
            message="当前对比建议对重点文件做深度确认；默认不阻塞当前版本使用。",
            rule_id="pairwise.recommended.attention",
            why="重点文件深度确认是有用证据，但默认不是当前版本使用的强制项。",
            next_action="需要时对推荐的 P0/P1 文件运行 lg fd。",
        )
        item["pending"] = int((pairwise_summary or {}).get("pending", 0) or 0)
        item["total"] = int((pairwise_summary or {}).get("total", 0) or 0)
        attention_items.append(item)
    elif pairwise_status == "PAIRWISE_FAILED":
        attention_items.append(
            _gate_item(
                f"pairwise.failed:{version_id}",
                severity="warning",
                category="file_diff",
                title="重点文件深度确认失败",
                message="推荐的文件深度确认运行失败；只有需要该证据时才重跑。",
                rule_id="pairwise.failed.attention",
                why="重点文件深度确认证据未能生成。",
                next_action="如果审查需要该证据，请重跑 lg fd。",
            )
        )

    status = "REVIEW_REQUIRED" if blocking_items else "ATTENTION" if attention_items else "READY"
    result = {
        "schema_version": "review_gate.v1",
        "library": lib_name,
        "version": version_id,
        "gate": gate,
        "status": status,
        "blocking_open": len(blocking_items),
        "attention_count": len(attention_items),
        "blocking_items": blocking_items,
        "attention_items": attention_items,
        "accepted_items": [],
        "waived_items": [],
    }
    return apply_overrides_to_gate(result, overrides)


def build_review_state(catalog: Mapping[str, Any], *, out_dir: str | Path | None = None) -> dict[str, Any]:
    libraries = []
    for lib in catalog.get("libraries", []) or []:
        formal_library_id = str(lib.get("formal_library_id") or lib.get("library_name") or lib.get("library_id") or "unknown")
        typed_library_id = str(lib.get("typed_library_id") or lib.get("library_id") or formal_library_id)
        report_slug = str(lib.get("report_slug") or _safe_name(typed_library_id))
        display_name = str(lib.get("display_name") or formal_library_id)
        lib_name = formal_library_id
        versions = []
        for version in _versions(lib):
            version_id = str(version.get("version_id") or version.get("version_key") or "unknown")
            catalog_status = _catalog_status(version)
            scan_status = _status_scan(version)
            diff_status = _status_diff(version, scan_status)
            pairwise_status, pairwise_tasks, pairwise_summary = _pairwise(version)
            release_status = _status_release(version)
            overall_status = _overall(scan_status, diff_status, pairwise_status, release_status, catalog_status)
            lineage = version.get("lineage", {}) or {}
            item: dict[str, Any] = {
                "version_id": version_id,
                "version_key": version.get("version_key"),
                "version_uid": version.get("version_uid") or version.get("version_key"),
                "formal_library_id": formal_library_id,
                "typed_library_id": typed_library_id,
                "report_slug": report_slug,
                "stage": version.get("stage") or "unknown",
                "raw_path": version.get("raw_path"),
                "base_version": version.get("base_version") or lineage.get("base_candidate") or lineage.get("base"),
                "parent_version": lineage.get("parent_candidate") or lineage.get("parent"),
                "package_type": version.get("package_type"),
                "update_scope": version.get("update_scope") or [],
                "catalog_status": catalog_status,
                "scan_status": scan_status,
                "scan": {
                    "scan_dir": (version.get("scan", {}) or {}).get("scan_dir"),
                    "scan_html": (version.get("scan", {}) or {}).get("scan_html"),
                    "scan_id": (version.get("scan", {}) or {}).get("scan_id"),
                },
                "diff": dict(version.get("diff", {}) or {}),
                "diff_status": diff_status,
                "pairwise_status": pairwise_status,
                "pairwise_summary": pairwise_summary,
                "release_status": release_status,
                "risk_level": overall_status,
                "overall_status": overall_status,
                "library_name": lib_name,
                "display_name": display_name,
                "library_id": typed_library_id,
                "links": _version_links(out_dir, lib_name, version_id, version),
                "pairwise_tasks": pairwise_tasks,
                "release_result": _release_result(version),
            }
            # Keep catalog/runtime annotations such as current_effective,
            # compare-default hints, and package metadata available to
            # renderers. Normalized fields above remain authoritative.
            for key, value in dict(version).items():
                item.setdefault(key, value)
            review_paths = review_paths_for_version(out_dir, lib_name, version_id)
            overrides = read_review_overrides(review_paths["override_file"])
            review_gate = build_review_gate_for_version(item, gate="current", overrides=overrides)
            review_gate["override_file"] = review_paths["override_file"]
            review_gate["gate_file"] = review_paths["gate_file"]
            item["review_gate"] = review_gate
            item.update(derive_next_action(item))
            versions.append(item)
        latest = versions[-1]["version_id"] if versions else None
        approved = next((v["version_id"] for v in reversed(versions) if v.get("release_status") == "RELEASE_APPLIED"), None)
        overall = "OK" if versions and all(v.get("overall_status") == "OK" for v in versions) else "REVIEW" if versions else "UNKNOWN"
        if any(v.get("overall_status") == "BLOCK" for v in versions):
            overall = "BLOCK"
        libraries.append(
            {
                "library_id": lib.get("library_id"),
                "typed_library_id": typed_library_id,
                "formal_library_id": formal_library_id,
                "library_name": formal_library_id,
                "display_name": display_name,
                "report_slug": report_slug,
                "vendor": lib.get("vendor") or "",
                "category": lib.get("category") or lib.get("library_type") or "",
                "middle_path": lib.get("middle_path") or "",
                "library_root": lib.get("library_root") or "",
                "latest_version": latest,
                "approved_version": approved,
                "version_count": len(versions),
                "overall_status": overall,
                "versions": versions,
            }
        )
    return {"generated_at": utc_now(), "schema_version": "review_state.v1", "libraries": libraries}

# ---------------------------------------------------------------------------
# Single-version review-state builder
# ---------------------------------------------------------------------------
# Version Detail is the authoritative review projection. Full catalog rendering
# still calls build_review_state(), but RenderImpact uses the helpers below to
# enrich exactly one version without rebuilding every library/version.


def _selector_aliases_for_value(value: Any) -> set[str]:
    text = str(value or "").strip()
    if not text:
        return set()
    aliases = {text, _safe_name(text)}
    aliases.add(text.replace("/", "."))
    aliases.add(text.replace("/", "_"))
    aliases.add(text.replace(".", "_"))
    if "/" in text:
        tail = text.rsplit("/", 1)[-1]
        aliases.update({tail, _safe_name(tail), tail.replace("/", "."), tail.replace("/", "_")})
    return {item for item in aliases if item}


def _library_selector_aliases(lib: Mapping[str, Any]) -> set[str]:
    aliases: set[str] = set()
    for key in ["formal_library_id", "typed_library_id", "library_id", "library_name", "display_name", "report_slug"]:
        aliases.update(_selector_aliases_for_value(lib.get(key)))
    for alias in lib.get("aliases", []) or []:
        aliases.update(_selector_aliases_for_value(alias))
    return aliases


def _version_selector_aliases(version: Mapping[str, Any]) -> set[str]:
    aliases: set[str] = set()
    for key in ["version_id", "version", "version_key", "version_uid", "name"]:
        aliases.update(_selector_aliases_for_value(version.get(key)))
    return aliases


def _selector_matches(aliases: set[str], selector: Any) -> bool:
    if not selector:
        return True
    values = selector if isinstance(selector, (list, tuple, set)) else [selector]
    wanted = {str(value).strip() for value in values if str(value).strip()}
    expanded: set[str] = set()
    for value in wanted:
        expanded.update(_selector_aliases_for_value(value))
    return bool(aliases & expanded)


def build_review_version_item(
    lib: Mapping[str, Any],
    version: Mapping[str, Any],
    *,
    out_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Build review-state fields for one catalog version.

    This mirrors the per-version enrichment inside build_review_state() but is
    intentionally scoped to one version. It is used by Version Detail fast
    rendering so scan/cmp/intake do not need full catalog projection.
    """

    formal_library_id = str(lib.get("formal_library_id") or lib.get("library_name") or lib.get("library_id") or "unknown")
    typed_library_id = str(lib.get("typed_library_id") or lib.get("library_id") or formal_library_id)
    report_slug = str(lib.get("report_slug") or _safe_name(typed_library_id))
    display_name = str(lib.get("display_name") or formal_library_id)
    lib_name = formal_library_id

    version_id = str(version.get("version_id") or version.get("version_key") or "unknown")
    catalog_status = _catalog_status(version)
    scan_status = _status_scan(version)
    diff_status = _status_diff(version, scan_status)
    pairwise_status, pairwise_tasks, pairwise_summary = _pairwise(version)
    release_status = _status_release(version)
    overall_status = _overall(scan_status, diff_status, pairwise_status, release_status, catalog_status)
    lineage = version.get("lineage", {}) or {}
    item: dict[str, Any] = {
        "version_id": version_id,
        "version_key": version.get("version_key"),
        "version_uid": version.get("version_uid") or version.get("version_key"),
        "formal_library_id": formal_library_id,
        "typed_library_id": typed_library_id,
        "report_slug": report_slug,
        "stage": version.get("stage") or "unknown",
        "raw_path": version.get("raw_path"),
        "base_version": version.get("base_version") or lineage.get("base_candidate") or lineage.get("base"),
        "parent_version": lineage.get("parent_candidate") or lineage.get("parent"),
        "package_type": version.get("package_type"),
        "update_scope": version.get("update_scope") or [],
        "catalog_status": catalog_status,
        "scan_status": scan_status,
        "scan": {
            "scan_dir": (version.get("scan", {}) or {}).get("scan_dir"),
            "scan_html": (version.get("scan", {}) or {}).get("scan_html"),
            "scan_id": (version.get("scan", {}) or {}).get("scan_id"),
        },
        "diff": dict(version.get("diff", {}) or {}),
        "diff_status": diff_status,
        "pairwise_status": pairwise_status,
        "pairwise_summary": pairwise_summary,
        "release_status": release_status,
        "risk_level": overall_status,
        "overall_status": overall_status,
        "library_name": lib_name,
        "display_name": display_name,
        "library_id": typed_library_id,
        "links": _version_links(out_dir, lib_name, version_id, version),
        "pairwise_tasks": pairwise_tasks,
        "release_result": _release_result(version),
    }

    # Preserve catalog/runtime fields that are not explicitly normalized above.
    # Explicit normalized fields win.
    for key, value in dict(version).items():
        item.setdefault(key, value)

    review_paths = review_paths_for_version(out_dir, lib_name, version_id)
    overrides = read_review_overrides(review_paths["override_file"])
    review_gate = build_review_gate_for_version(item, gate="current", overrides=overrides)
    review_gate["override_file"] = review_paths["override_file"]
    review_gate["gate_file"] = review_paths["gate_file"]
    item["review_gate"] = review_gate
    item["evidence_state"] = build_version_evidence_state(library=lib, version=item)
    item.update(derive_next_action(item))
    return item


def build_review_version_state(
    catalog: Mapping[str, Any],
    *,
    out_dir: str | Path | None = None,
    library: str,
    version: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return an enriched ``(library, version)`` pair for one Version Detail.

    Unlike build_review_state(), this is O(1) with respect to the number of
    catalog versions after the target library/version have been selected. It is
    the correct dependency for hot-path Version Detail renders.
    """

    selected_lib: Mapping[str, Any] | None = None
    for lib in catalog.get("libraries", []) or []:
        if isinstance(lib, Mapping) and _selector_matches(_library_selector_aliases(lib), library):
            selected_lib = lib
            break
    if selected_lib is None:
        raise ValueError(f"library not found for version detail render: {library!r}")

    selected_version: Mapping[str, Any] | None = None
    for item in selected_lib.get("versions", []) or []:
        if isinstance(item, Mapping) and _selector_matches(_version_selector_aliases(item), version):
            selected_version = item
            break
    if selected_version is None:
        raise ValueError(f"version not found for version detail render: library={library!r} version={version!r}")

    enriched = build_review_version_item(selected_lib, selected_version, out_dir=out_dir)
    formal_library_id = str(selected_lib.get("formal_library_id") or selected_lib.get("library_name") or selected_lib.get("library_id") or "unknown")
    typed_library_id = str(selected_lib.get("typed_library_id") or selected_lib.get("library_id") or formal_library_id)
    report_slug = str(selected_lib.get("report_slug") or _safe_name(typed_library_id))
    display_name = str(selected_lib.get("display_name") or formal_library_id)
    lib_state: dict[str, Any] = dict(selected_lib)
    lib_state.update(
        {
            "library_id": selected_lib.get("library_id"),
            "typed_library_id": typed_library_id,
            "formal_library_id": formal_library_id,
            "library_name": formal_library_id,
            "display_name": display_name,
            "report_slug": report_slug,
            "vendor": selected_lib.get("vendor") or "",
            "category": selected_lib.get("category") or selected_lib.get("library_type") or "",
            "middle_path": selected_lib.get("middle_path") or "",
            "library_root": selected_lib.get("library_root") or "",
            "version_count": len(selected_lib.get("versions", []) or []),
            "versions": [enriched],
        }
    )
    return lib_state, enriched
