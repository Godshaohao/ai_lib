from __future__ import annotations

from pathlib import Path
from typing import Any
import json


def read_json(path: str | Path | None, default: Any = None) -> Any:
    if not path:
        return default
    p = Path(path)
    try:
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default
    return default


def write_json(path: str | Path, data: Any) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")


def utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")


def as_file_href(path: str | Path | None) -> str:
    if not path:
        return ""
    text = str(path)
    anchor = ""
    if "#" in text:
        text, fragment = text.split("#", 1)
        anchor = "#" + fragment
    if text.startswith(("http://", "https://", "file://")):
        return text + anchor
    try:
        return Path(text).resolve().as_uri() + anchor
    except Exception:
        return text.replace("\\", "/") + anchor
