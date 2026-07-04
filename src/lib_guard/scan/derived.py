from __future__ import annotations

from pathlib import Path
from typing import Any
import json


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")


def build_scan_derived_outputs(scan_dir: str | Path) -> dict[str, str]:
    """Build non-core scan outputs from completed scan evidence."""

    out = Path(scan_dir)
    try:
        from lib_guard.summary.readiness import build_release_readiness

        readiness = build_release_readiness(out)
    except Exception as exc:
        readiness = {
            "schema_version": "1.0",
            "bundle_status": "FAILED",
            "release_level_candidate": "L0",
            "validation_depth": "inventory",
            "blocking_items": [
                {
                    "severity": "blocker",
                    "category": "release_readiness",
                    "title": "Readiness build failed",
                    "message": str(exc),
                }
            ],
            "manual_review_items": [],
            "warning_items": [],
            "allowed_aliases": ["stage"],
            "blocked_aliases": ["current", "approved"],
            "limitations": ["Release readiness generation failed"],
        }
    readiness_path = out / "summary" / "release_readiness.json"
    _write_json(readiness_path, readiness)
    return {"release_readiness": str(readiness_path)}
