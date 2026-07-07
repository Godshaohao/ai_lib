"""Review context model for Version Detail pages."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import re
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "version_detail_review_context.v1"
ACTIVE_WINDOW_STATES = {"PENDING", "REBUILT", "COMPARED", "ACCEPTED"}


@dataclass(frozen=True)
class VersionDetailReviewContext:
    schema_version: str
    status: str

    library: str
    library_id: str
    target_version: str

    role_in_window: str
    window_state: str
    window_file: str
    window_items: list[dict[str, Any]]

    old_target: str
    old_label: str

    candidate_effective_id: str
    candidate_effective_base_full: str
    candidate_effective_overlays: list[str]
    candidate_effective_manifest: str
    candidate_effective_html: str

    compare_id: str
    compare_old: str
    compare_new: str
    compare_dir: str
    compare_html: str
    compare_manifest: str

    freshness: dict[str, Any]
    warnings: list[str]


def to_dict(ctx: VersionDetailReviewContext) -> dict[str, Any]:
    return asdict(ctx)


def build_version_detail_review_context(
    *,
    catalog_html_out: str | Path,
    library_row: Mapping[str, Any],
    version_row: Mapping[str, Any],
) -> dict[str, Any]:
    target_version = _version_id(version_row)
    window_file = find_pending_window_file(catalog_html_out, library_row)
    if not window_file:
        return to_dict(_standalone_context(library_row, version_row, window=None, window_file=None))

    window = _read_mapping(window_file)
    state = str(window.get("state") or "").upper()
    if state not in ACTIVE_WINDOW_STATES:
        return to_dict(_standalone_context(library_row, version_row, window=window, window_file=window_file))

    items = _window_items(window)
    role = _role_for_target(target_version, items, _mapping(window.get("candidate_effective")))
    in_active_window = role != "standalone"
    ctx = VersionDetailReviewContext(
        schema_version=SCHEMA_VERSION,
        status="IN_ACTIVE_WINDOW" if in_active_window else "STANDALONE",
        library=_library_name(library_row, window),
        library_id=_library_id(library_row, window),
        target_version=target_version,
        role_in_window=role,
        window_state=state,
        window_file=str(window_file),
        window_items=items,
        old_target=_old_target(window),
        old_label=_old_target(window),
        candidate_effective_id=_candidate_effective_id(window),
        candidate_effective_base_full=_candidate_base_full(window),
        candidate_effective_overlays=_candidate_overlays(window),
        candidate_effective_manifest=_candidate_manifest(catalog_html_out, library_row, window),
        candidate_effective_html=_candidate_html(catalog_html_out, library_row, window),
        compare_id=_compare_id(window),
        compare_old=_compare_old(window),
        compare_new=_compare_new(window),
        compare_dir=_compare_dir(catalog_html_out, library_row, window),
        compare_html=_compare_html(catalog_html_out, library_row, window),
        compare_manifest=_compare_manifest(catalog_html_out, library_row, window),
        freshness={},
        warnings=_warnings(window),
    )
    return to_dict(_with_freshness(ctx, version_row, in_active_window=in_active_window))


def find_pending_window_file(catalog_html_out: str | Path, library_row: Mapping[str, Any]) -> Path | None:
    path = Path(catalog_html_out) / "libraries" / _library_report_key(library_row) / "window" / "pending_window.json"
    return path if path.exists() and path.is_file() else None


def _standalone_context(
    library_row: Mapping[str, Any],
    version_row: Mapping[str, Any],
    *,
    window: Mapping[str, Any] | None,
    window_file: Path | None,
) -> VersionDetailReviewContext:
    active_summary = window if window else {}
    ctx = VersionDetailReviewContext(
        schema_version=SCHEMA_VERSION,
        status="STANDALONE",
        library=_library_name(library_row, active_summary),
        library_id=_library_id(library_row, active_summary),
        target_version=_version_id(version_row),
        role_in_window="standalone",
        window_state=str(active_summary.get("state") or "").upper(),
        window_file=str(window_file) if window_file else "",
        window_items=_window_items(active_summary),
        old_target=_old_target(active_summary),
        old_label=_old_target(active_summary),
        candidate_effective_id=_candidate_effective_id(active_summary),
        candidate_effective_base_full=_candidate_base_full(active_summary),
        candidate_effective_overlays=_candidate_overlays(active_summary),
        candidate_effective_manifest=_candidate_manifest("", library_row, active_summary),
        candidate_effective_html=_candidate_html("", library_row, active_summary),
        compare_id=_compare_id(active_summary),
        compare_old=_compare_old(active_summary),
        compare_new=_compare_new(active_summary),
        compare_dir=_compare_dir("", library_row, active_summary),
        compare_html=_compare_html("", library_row, active_summary),
        compare_manifest=_compare_manifest("", library_row, active_summary),
        freshness={},
        warnings=_warnings(active_summary),
    )
    return _with_freshness(ctx, version_row, in_active_window=False)


def _with_freshness(
    ctx: VersionDetailReviewContext,
    version_row: Mapping[str, Any],
    *,
    in_active_window: bool,
) -> VersionDetailReviewContext:
    freshness = {
        "window_exists": bool(ctx.window_file and Path(ctx.window_file).exists()),
        "candidate_manifest_exists": bool(ctx.candidate_effective_manifest and Path(ctx.candidate_effective_manifest).exists()),
        "compare_manifest_exists": bool(ctx.compare_manifest and Path(ctx.compare_manifest).exists()),
        "compare_html_exists": bool(ctx.compare_html and Path(ctx.compare_html).exists()),
        "scan_evidence_exists": _scan_evidence_exists(version_row),
        "status": "STALE_OR_MISSING",
    }
    if in_active_window and all(
        freshness[key]
        for key in [
            "window_exists",
            "candidate_manifest_exists",
            "compare_manifest_exists",
            "compare_html_exists",
            "scan_evidence_exists",
        ]
    ):
        freshness["status"] = "FRESH"
    elif any(value for key, value in freshness.items() if key != "status"):
        freshness["status"] = "PARTIAL"

    return VersionDetailReviewContext(**{**asdict(ctx), "freshness": freshness})


def _read_mapping(path: Path) -> Mapping[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, Mapping) else {}


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _safe(value: Any) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "item")).strip("._")
    return text or "item"


def _library_report_key(library_row: Mapping[str, Any]) -> str:
    return str(
        library_row.get("report_slug")
        or _safe(library_row.get("typed_library_id") or library_row.get("library_id") or library_row.get("library_name") or "library")
    )


def _library_id(library_row: Mapping[str, Any], window: Mapping[str, Any]) -> str:
    return str(
        window.get("library_id")
        or library_row.get("formal_library_id")
        or library_row.get("library_id")
        or library_row.get("library_name")
        or "library"
    )


def _library_name(library_row: Mapping[str, Any], window: Mapping[str, Any]) -> str:
    value = window.get("library") or library_row.get("library_name") or library_row.get("display_name")
    if value:
        return str(value)
    lib_id = _library_id(library_row, window)
    return lib_id.rsplit("/", 1)[-1] or lib_id


def _version_id(version_row: Mapping[str, Any]) -> str:
    return str(version_row.get("version_id") or version_row.get("version") or "version")


def _window_items(window: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw_items = window.get("items")
    if not isinstance(raw_items, list):
        return []
    return [dict(item) for item in raw_items if isinstance(item, Mapping)]


def _item_version(item: Mapping[str, Any]) -> str:
    return str(item.get("version") or item.get("version_id") or item.get("id") or "")


def _role_for_target(target_version: str, items: list[dict[str, Any]], candidate: Mapping[str, Any]) -> str:
    matched = next((item for item in items if _item_version(item) == target_version), None)
    if matched is None:
        return "standalone"
    role = str(matched.get("role") or "")
    if role in {"candidate_base", "candidate_overlay", "intermediate"}:
        return role
    if target_version == str(candidate.get("base_full") or ""):
        return "candidate_base"
    if target_version in {str(item) for item in candidate.get("overlays", []) or []}:
        return "candidate_overlay"
    return "intermediate"


def _old_target(window: Mapping[str, Any]) -> str:
    compare = _mapping(window.get("compare"))
    base = _mapping(window.get("base_effective"))
    return str(compare.get("old") or base.get("target") or "")


def _candidate_effective(window: Mapping[str, Any]) -> Mapping[str, Any]:
    return _mapping(window.get("candidate_effective"))


def _candidate_effective_id(window: Mapping[str, Any]) -> str:
    candidate = _candidate_effective(window)
    return str(candidate.get("effective_id") or candidate.get("id") or "")


def _candidate_base_full(window: Mapping[str, Any]) -> str:
    return str(_candidate_effective(window).get("base_full") or "")


def _candidate_overlays(window: Mapping[str, Any]) -> list[str]:
    overlays = _candidate_effective(window).get("overlays")
    return [str(item) for item in overlays] if isinstance(overlays, list) else []


def _candidate_manifest(catalog_html_out: str | Path, library_row: Mapping[str, Any], window: Mapping[str, Any]) -> str:
    candidate = _candidate_effective(window)
    manifest = str(candidate.get("manifest") or "")
    if manifest or not catalog_html_out:
        return manifest
    effective_id = _candidate_effective_id(window)
    if not effective_id:
        return ""
    return str(Path(catalog_html_out) / "libraries" / _library_report_key(library_row) / "effective" / _safe(effective_id) / "effective_manifest.json")


def _candidate_html(catalog_html_out: str | Path, library_row: Mapping[str, Any], window: Mapping[str, Any]) -> str:
    candidate = _candidate_effective(window)
    html = str(candidate.get("html") or "")
    if html or not catalog_html_out:
        return html
    effective_id = _candidate_effective_id(window)
    if not effective_id:
        return ""
    return str(Path(catalog_html_out) / "libraries" / _library_report_key(library_row) / "effective" / _safe(effective_id) / "index.html")


def _compare(window: Mapping[str, Any]) -> Mapping[str, Any]:
    return _mapping(window.get("compare"))


def _compare_id(window: Mapping[str, Any]) -> str:
    compare = _compare(window)
    return str(compare.get("compare_id") or compare.get("id") or "")


def _compare_old(window: Mapping[str, Any]) -> str:
    return str(_compare(window).get("old") or _old_target(window))


def _compare_new(window: Mapping[str, Any]) -> str:
    return str(_compare(window).get("new") or "")


def _compare_dir(catalog_html_out: str | Path, library_row: Mapping[str, Any], window: Mapping[str, Any]) -> str:
    compare = _compare(window)
    out_dir = str(compare.get("out_dir") or "")
    if out_dir and Path(out_dir).exists():
        return out_dir
    if not catalog_html_out:
        return out_dir
    compare_id = _compare_id(window)
    if compare_id:
        candidate = Path(catalog_html_out) / "libraries" / _library_report_key(library_row) / "compare" / _safe(compare_id)
        if candidate.exists():
            return str(candidate)
    manifest = _find_compare_manifest(catalog_html_out, library_row, window)
    if manifest:
        return str(manifest.parent)
    return out_dir


def _compare_html(catalog_html_out: str | Path, library_row: Mapping[str, Any], window: Mapping[str, Any]) -> str:
    compare = _compare(window)
    html = str(compare.get("html") or "")
    if html and Path(html).exists():
        return html
    compare_dir = _compare_dir(catalog_html_out, library_row, window)
    candidate = Path(compare_dir) / "index.html" if compare_dir else None
    if candidate and candidate.exists():
        return str(candidate)
    return html or (str(candidate) if candidate else "")


def _compare_manifest(catalog_html_out: str | Path, library_row: Mapping[str, Any], window: Mapping[str, Any]) -> str:
    compare = _compare(window)
    explicit = str(compare.get("manifest") or compare.get("compare_manifest") or "")
    if explicit and Path(explicit).exists():
        return explicit
    compare_dir = _compare_dir(catalog_html_out, library_row, window)
    candidate = Path(compare_dir) / "compare_manifest.json" if compare_dir else None
    if candidate and candidate.exists():
        return str(candidate)
    manifest = _find_compare_manifest(catalog_html_out, library_row, window)
    return str(manifest) if manifest else ""


def _manifest_target_label(manifest: Mapping[str, Any], key: str) -> str:
    target = _mapping(manifest.get(key))
    return str(target.get("label") or (f"{target.get('type')}:{target.get('id')}" if target.get("type") and target.get("id") else ""))


def _compare_manifest_matches(manifest: Mapping[str, Any], expected_old: str, expected_new: str) -> bool:
    old_label = _manifest_target_label(manifest, "old_target")
    new_label = _manifest_target_label(manifest, "new_target")
    return bool(old_label and new_label and old_label == str(expected_old or "") and new_label == str(expected_new or ""))


def _find_compare_manifest(catalog_html_out: str | Path, library_row: Mapping[str, Any], window: Mapping[str, Any]) -> Path | None:
    if not catalog_html_out:
        return None
    compare_root = Path(catalog_html_out) / "libraries" / _library_report_key(library_row) / "compare"
    if not compare_root.exists() or not compare_root.is_dir():
        return None
    expected_old = _compare_old(window)
    expected_new = _compare_new(window)
    for child in sorted(compare_root.iterdir()):
        if not child.is_dir():
            continue
        manifest_path = child / "compare_manifest.json"
        if not manifest_path.exists():
            continue
        manifest = _read_mapping(manifest_path)
        if _compare_manifest_matches(manifest, expected_old, expected_new):
            return manifest_path
    return None


def _scan_evidence_exists(version_row: Mapping[str, Any]) -> bool:
    scan = _mapping(version_row.get("scan"))
    status = str(scan.get("status") or version_row.get("scan_status") or "").upper()
    if status in {"", "NOT_SCANNED", "STALE_SCAN", "FAILED"}:
        return False
    scan_dir = scan.get("scan_dir") or version_row.get("scan_dir")
    if scan_dir and Path(str(scan_dir)).exists():
        return True
    for key in ["file_inventory", "file_inventory_json", "inventory_json"]:
        value = scan.get(key) or version_row.get(key)
        if value and Path(str(value)).exists():
            return True
    return False


def _warnings(window: Mapping[str, Any]) -> list[str]:
    warnings = window.get("warnings")
    return [str(item) for item in warnings] if isinstance(warnings, list) else []
