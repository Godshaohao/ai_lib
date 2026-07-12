"""Fast, local Version Detail rendering for RenderImpact.

This module intentionally does not own Version Detail business logic. It only
selects one catalog library/version, enriches that single version with the same
review-state fields used by the full catalog renderer, then delegates to
``render_version_detail_page``.

Purpose:
- scan/cmp/intake changed one or a few versions;
- RenderImpact should refresh those Version Detail pages;
- refreshing them must not rebuild the whole catalog/index state.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from lib_guard.catalog.runtime import load_catalog_view
from lib_guard.render.impact import RenderImpact, dedup_impacts, serialize_impacts


DEFERRED_FILE = "render_deferred.json"


def _write_json(path: str | Path, data: Mapping[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def render_version_detail_only(
    *,
    catalog_path: str | Path,
    out_dir: str | Path,
    library: str,
    version: str,
    export_markdown: bool = False,
) -> dict[str, Any]:
    """Render exactly one Version Detail page using single-version enrichment.

    This is the fast path for RenderImpact. It avoids ``render_catalog_html`` and
    therefore avoids global ``build_review_state`` / ``build_review_tasks`` /
    effective-report discovery.
    """

    from lib_guard.review.state import build_review_version_state
    from lib_guard.render.version_detail_report import render_version_detail_page

    catalog = load_catalog_view(catalog_path)
    lib_state, version_state = build_review_version_state(
        catalog,
        out_dir=out_dir,
        library=library,
        version=version,
    )
    page = render_version_detail_page(out_dir, lib_state, version_state, export_markdown=export_markdown)
    return {
        "status": "PASS",
        "library": lib_state.get("library_name") or lib_state.get("formal_library_id") or library,
        "version": version_state.get("version_id") or version,
        "version_detail_html": page,
        "mode": "single_version_review_state",
        "enriched_review_state": True,
    }


def _version_impacts(impacts: Iterable[RenderImpact]) -> list[RenderImpact]:
    return [
        item
        for item in dedup_impacts(impacts)
        if item.kind == "version_detail" and item.library and item.version
    ]


def _deferred_entries(all_impacts: Iterable[RenderImpact]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for item in dedup_impacts(all_impacts):
        if item.kind in {"library_page", "catalog_index"}:
            entries.append(
                {
                    "kind": item.kind,
                    "library": item.library,
                    "version": item.version,
                    "reason": item.reason,
                }
            )
    return entries


def write_deferred_render_notice(
    *,
    out_dir: str | Path,
    entries: list[dict[str, Any]],
    rendered_versions: list[dict[str, Any]],
) -> str:
    """Record that library/index pages were intentionally not rebuilt.

    Version Detail is the authoritative review projection. Library/index pages
    are navigation surfaces and can be refreshed by normal catalog render.
    """

    out = Path(out_dir)
    path = out / DEFERRED_FILE
    payload = {
        "schema_version": "render_deferred.v1",
        "status": "DEFERRED",
        "reason": "RenderImpact refreshed Version Detail directly; navigation pages were deferred to avoid global catalog projection.",
        "deferred_pages": entries,
        "fresh_version_detail_pages": rendered_versions,
        "recommended_refresh": "Run the normal catalog render/cat command when library/index navigation summaries must be refreshed.",
    }
    _write_json(path, payload)
    return str(path)


def render_impacted_version_details(
    *,
    catalog_path: str | Path,
    out_dir: str | Path,
    impacts: Iterable[RenderImpact],
    all_impacts: Iterable[RenderImpact] | None = None,
) -> dict[str, Any]:
    """Render affected Version Detail pages without full catalog render."""

    selected = _version_impacts(impacts)
    rendered: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for item in selected:
        try:
            rendered.append(
                render_version_detail_only(
                    catalog_path=catalog_path,
                    out_dir=out_dir,
                    library=str(item.library),
                    version=str(item.version),
                )
            )
        except Exception as exc:  # pragma: no cover - exercised by integration failures
            failures.append(
                {
                    "library": item.library,
                    "version": item.version,
                    "reason": item.reason,
                    "error": str(exc),
                }
            )

    deferred_entries = _deferred_entries(all_impacts if all_impacts is not None else impacts)
    deferred_file = ""
    if deferred_entries:
        deferred_file = write_deferred_render_notice(
            out_dir=out_dir,
            entries=deferred_entries,
            rendered_versions=rendered,
        )

    return {
        "status": "PASS" if not failures else "FAILED",
        "mode": "version_detail_direct",
        "rendered_versions": len(rendered),
        "version_detail_pages": rendered,
        "failed_versions": failures,
        "deferred_pages": deferred_entries,
        "deferred_file": deferred_file,
        "affected_version_details": serialize_impacts(selected),
    }
