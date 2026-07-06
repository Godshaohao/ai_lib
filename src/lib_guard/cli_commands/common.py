"""Shared helpers for lib_guard CLI command modules."""

from __future__ import annotations

from argparse import Namespace
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
import json

from lib_guard.render.impact import RenderImpact, dedup_impacts, serialize_impacts


def print_json(data: Any) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


def auto_scan_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def default_state_dir(workdir: str | Path, library_type: str, library_name: str, version: str) -> str:
    return str(Path(workdir) / "index" / "scan_state" / (library_type or "unknown") / (library_name or "unknown") / (version or "unknown"))


def default_cache_dir(workdir: str | Path) -> str:
    return str(Path(workdir) / "index" / "parser_cache")


def default_catalog_html_out(catalog_path: str | Path, workdir: str | Path | None = None) -> str:
    catalog = Path(catalog_path).resolve()
    if catalog.parent.name == "catalog" and catalog.parent.parent.name == "work":
        project_root = catalog.parent.parent.parent
        if (project_root / "pages").exists():
            return str(project_root / "pages" / "catalog_html")
    if workdir:
        work = Path(workdir).resolve()
        if work.name == "work" and (work.parent / "pages").exists():
            return str(work.parent / "pages" / "catalog_html")
    return str(catalog.parent / "html")


def refresh_catalog_html(args: Namespace) -> dict[str, Any] | None:
    if getattr(args, "no_catalog_render", False):
        return None
    from lib_guard.catalog.index import render_catalog_html

    out = getattr(args, "catalog_html_out", None) or default_catalog_html_out(args.catalog, getattr(args, "workdir", None))
    library_filter = getattr(args, "library", None)
    version_filter = getattr(args, "version", None) or getattr(args, "new", None)
    return render_catalog_html(args.catalog, out, library_filter=library_filter, version_filter=version_filter)


def _combined_render_result(render_calls: list[dict[str, Any]]) -> dict[str, Any]:
    if len(render_calls) == 1:
        return render_calls[0]
    failed = [item for item in render_calls if item.get("status") not in {None, "PASS"}]
    return {
        "status": "PASS" if not failed else "FAILED",
        "render_calls": render_calls,
    }

def render_impacted_catalog_html(args: Namespace, impacts: Iterable[RenderImpact] | None = None) -> dict[str, Any]:
    """Render catalog HTML affected by state changes.

    Hot path rule:
      version_detail impacts render Version Detail directly through a single-
      version review-state builder. They do not rebuild the full catalog/index
      projection unless LIB_GUARD_FULL_RENDER_ON_IMPACT=1 is set.

    Library/index impacts are recorded as deferred when paired with version
    detail impacts; normal catalog render can refresh them later.
    """

    out = getattr(args, "catalog_html_out", None) or default_catalog_html_out(args.catalog, getattr(args, "workdir", None))
    affected = dedup_impacts(impacts or [])
    affected_pages = serialize_impacts(affected)
    if getattr(args, "no_catalog_render", False):
        return {
            "catalog_html_out": out,
            "affected_pages": affected_pages,
            "render_result": {"status": "SKIPPED", "reason": "no_catalog_render"},
        }

    from lib_guard.catalog.index import render_catalog_html

    if impacts is None:
        library_filter = getattr(args, "library", None)
        version_filter = getattr(args, "version", None) or getattr(args, "new", None)
        render_result = render_catalog_html(args.catalog, out, library_filter=library_filter, version_filter=version_filter)
        return {
            "catalog_html_out": out,
            "affected_pages": [],
            "render_result": render_result,
        }

    if not affected:
        return {
            "catalog_html_out": out,
            "affected_pages": [],
            "render_result": {"status": "SKIPPED", "reason": "no_impacts"},
        }

    # Explicit escape hatch for debugging or conservative rollout.
    import os
    if os.environ.get("LIB_GUARD_FULL_RENDER_ON_IMPACT") == "1":
        return _render_impacts_via_catalog(args, out, affected, affected_pages)

    version_impacts = [item for item in affected if item.kind == "version_detail" and item.library and item.version]
    if version_impacts:
        from lib_guard.render.version_detail_fast import render_impacted_version_details

        render_result = render_impacted_version_details(
            catalog_path=args.catalog,
            out_dir=out,
            impacts=version_impacts,
            all_impacts=affected,
        )
        return {
            "catalog_html_out": out,
            "affected_pages": affected_pages,
            "render_result": render_result,
        }

    return _render_impacts_via_catalog(args, out, affected, affected_pages)


def _render_impacts_via_catalog(
    args: Namespace,
    out: str | Path,
    affected: Iterable[RenderImpact],
    affected_pages: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compatibility renderer for non-version impacts or full-render fallback."""

    from lib_guard.catalog.index import render_catalog_html

    versions_by_library: dict[str, list[str]] = {}
    library_order: list[str] = []
    catalog_index_only = True
    for item in affected:
        if item.kind not in {"version_detail", "library_page"} or not item.library:
            continue
        catalog_index_only = False
        if item.library not in versions_by_library:
            versions_by_library[item.library] = []
            library_order.append(item.library)
        if item.kind == "version_detail" and item.version and item.version not in versions_by_library[item.library]:
            versions_by_library[item.library].append(item.version)

    render_calls: list[dict[str, Any]] = []
    for library in library_order:
        versions = versions_by_library[library]
        version_filter: Any = versions if versions else "__lib_guard_render_impact_no_versions__"
        render_calls.append(
            render_catalog_html(
                args.catalog,
                out,
                library_filter=library,
                version_filter=version_filter,
            )
        )
    if catalog_index_only:
        render_calls.append(render_catalog_html(args.catalog, out, render_library_pages=False))

    return {
        "catalog_html_out": str(out),
        "affected_pages": affected_pages,
        "render_result": _combined_render_result(render_calls),
    }
