"""Compatibility wrapper for the old lib_guard control console.

The project no longer maintains a parallel six-page console. The authoritative
human page for a single scan is render_scan_html() in html_report.py.
This module keeps render_console() for existing CLI callers and still exports
machine-readable data/*.json for audit evidence.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
import html

from .control_data import (
    build_approval_snapshot,
    build_config_view,
    build_control_data,
    build_parser_quality,
    build_recommended_actions,
    build_review_items,
    read_json,
    write_json,
)
from .html_report import render_scan_html


def _redirect_page(title: str, target: str = "index.html") -> str:
    safe_title = html.escape(title)
    safe_target = html.escape(target)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta http-equiv="refresh" content="0; url={safe_target}" />
<title>{safe_title}</title>
</head>
<body style="font-family:Arial,'Microsoft YaHei',sans-serif;padding:24px">
  <h2>{safe_title}</h2>
  <p>该控制台页面已合并到单版本交付结构审阅台。</p>
  <p><a href="{safe_target}">打开统一审阅页</a></p>
</body>
</html>"""


def render_console(
    scan_dir: str | Path,
    out_dir: str | Path,
    workdir: str | Path = "work",
    config_dir: str | Path = "configs",
) -> dict[str, Any]:
    scan = Path(scan_dir)
    out = Path(out_dir)
    data_dir = out / "data"
    out.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)

    control_data = build_control_data(scan, workdir=workdir, config_dir=config_dir)
    config_view = build_config_view(config_dir=config_dir)
    parser_quality = build_parser_quality(scan)
    review_items = build_review_items(scan, config_dir=config_dir)
    recommended_actions = build_recommended_actions(review_items, scan)
    approval_snapshot = build_approval_snapshot(control_data)
    release_readiness = read_json(scan / "summary" / "release_readiness.json", default={})

    write_json(data_dir / "control_data.json", control_data)
    write_json(data_dir / "config_view.json", config_view)
    write_json(data_dir / "parser_quality.json", parser_quality)
    write_json(data_dir / "review_items.json", review_items)
    write_json(data_dir / "recommended_actions.json", recommended_actions)
    write_json(data_dir / "approval_snapshot.json", approval_snapshot)
    write_json(data_dir / "release_readiness.json", release_readiness)

    result = render_scan_html(scan, out)
    for name in ["config.html", "quality.html", "release.html", "history.html", "review.html"]:
        (out / name).write_text(_redirect_page(name), encoding="utf-8")

    return {
        "status": "PASS",
        "console_dir": str(out),
        "index_html": result.get("index_html", str(out / "index.html")),
        "data_dir": str(data_dir),
        "note": "control_console is a compatibility wrapper; Version Review is the normal single-version detail page.",
    }
