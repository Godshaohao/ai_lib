from __future__ import annotations

from pathlib import Path
from typing import Any
import json


def write_release_markdown(release_check_or_link: dict[str, Any], path: str | Path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    status = release_check_or_link.get("release_check_status") or release_check_or_link.get("status")
    lines = [
        "# Release Report",
        "",
        f"- status: `{status}`",
        f"- scan_dir: `{release_check_or_link.get('scan_dir')}`",
        f"- library_id: `{release_check_or_link.get('library_id')}`",
        "",
        "## Issues",
        "",
    ]
    issues = release_check_or_link.get("issues") or release_check_or_link.get("release_check", {}).get("issues") or []
    if not issues:
        lines.append("No release issues.")
    else:
        for i in issues:
            lines.append(f"- **{i.get('severity')}** {i.get('category')}: {i.get('title')} - {i.get('message')}")
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
