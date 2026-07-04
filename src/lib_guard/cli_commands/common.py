"""Shared helpers for lib_guard CLI command modules."""

from __future__ import annotations

from argparse import Namespace
from datetime import datetime
from pathlib import Path
from typing import Any
import json


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
