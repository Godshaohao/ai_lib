"""Compatibility wrapper for legacy imports.

All Diff HTML rendering is handled by ``lib_guard.render.html_report.render_diff_html``.
This avoids maintaining two incompatible Diff UI paths.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def render_diff_html(diff_dir: str | Path, out_dir: str | Path) -> dict[str, Any]:
    from lib_guard.render.html_report import render_diff_html as _render_diff_html

    return _render_diff_html(diff_dir, out_dir)


__all__ = ["render_diff_html"]
