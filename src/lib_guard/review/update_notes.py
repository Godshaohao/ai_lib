"""Human-authored version update notes.

These notes are review narrative, not scan/diff facts.  They are stored beside
review state so a Version Detail page can show the owner's intent without
polluting catalog, scan, or compare evidence.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
import json
import re

from lib_guard.atomic import atomic_write_json, file_lock


SCHEMA_VERSION = "version_update_note.v1"
VALID_STATUSES = {"draft", "published"}
VALID_SUGGESTIONS = {"推荐使用", "条件使用", "暂缓使用", "待确认"}


def _safe_segment(value: Any) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "item")).strip("._")
    return text or "item"


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def review_notes_root(*, workdir: str | Path | None = None, catalog_html_out: str | Path | None = None) -> Path:
    if workdir:
        return Path(workdir).expanduser().resolve() / "review_notes"
    if catalog_html_out:
        html = Path(catalog_html_out).expanduser().resolve()
        # Normal layout: <workspace>/catalog/html.  Keep the note under the
        # workspace so deleting/rebuilding HTML does not delete human notes.
        if html.name == "html" and html.parent.name == "catalog":
            return html.parent.parent / "review_notes"
        return html.parent / "review_notes"
    return Path.cwd().resolve() / "work" / "review_notes"


def update_note_path(root: str | Path, library: str, version: str) -> Path:
    return Path(root).expanduser().resolve() / _safe_segment(library) / _safe_segment(version) / "update_note.json"


def empty_update_note(library: str, version: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "library": library,
        "version": version,
        "status": "missing",
        "use_suggestion": "待确认",
        "summary": "",
        "impact_areas": [],
        "key_changes": [],
        "risks": [],
        "must_check": [],
        "evidence_refs": [],
        "updated_by": "",
        "updated_at": "",
        "history": [],
    }


def _text(value: Any, *, limit: int = 2000) -> str:
    text = str(value or "").strip()
    return text[:limit]


def _list(value: Any, *, limit: int = 24) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        raw = [line.strip() for line in value.replace("；", "\n").replace(";", "\n").splitlines()]
    elif isinstance(value, list):
        raw = []
        for item in value:
            if isinstance(item, Mapping):
                raw.append(str(item.get("text") or item.get("label") or item.get("value") or "").strip())
            else:
                raw.append(str(item or "").strip())
    else:
        raw = [str(value).strip()]
    result: list[str] = []
    for item in raw:
        if item and item not in result:
            result.append(item[:500])
        if len(result) >= limit:
            break
    return result


def load_update_note(root: str | Path, library: str, version: str) -> dict[str, Any]:
    path = update_note_path(root, library, version)
    if not path.is_file():
        return empty_update_note(library, version) | {"path": str(path)}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return empty_update_note(library, version) | {"status": "invalid", "path": str(path)}
    if not isinstance(loaded, Mapping):
        return empty_update_note(library, version) | {"status": "invalid", "path": str(path)}
    note = empty_update_note(library, version)
    note.update({key: loaded.get(key) for key in note if key in loaded})
    note["library"] = library
    note["version"] = version
    note["path"] = str(path)
    note["status"] = str(note.get("status") or "draft").lower()
    if note["status"] not in VALID_STATUSES:
        note["status"] = "draft"
    suggestion = str(note.get("use_suggestion") or "待确认").strip()
    note["use_suggestion"] = suggestion if suggestion in VALID_SUGGESTIONS else "待确认"
    for key in ("impact_areas", "key_changes", "risks", "must_check", "evidence_refs"):
        note[key] = _list(note.get(key))
    history = note.get("history")
    note["history"] = history if isinstance(history, list) else []
    return note


def _history_item(note: Mapping[str, Any]) -> dict[str, Any] | None:
    summary = _text(note.get("summary"), limit=400)
    if not summary and not note.get("updated_at"):
        return None
    return {
        "status": str(note.get("status") or "draft"),
        "use_suggestion": str(note.get("use_suggestion") or "待确认"),
        "summary": summary,
        "updated_by": str(note.get("updated_by") or ""),
        "updated_at": str(note.get("updated_at") or ""),
    }


def save_update_note(
    root: str | Path,
    library: str,
    version: str,
    payload: Mapping[str, Any],
    *,
    updated_by: str = "web",
    publish: bool = False,
) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise ValueError("版本备注必须是 JSON 对象")
    path = update_note_path(root, library, version)
    lock_path = path.with_name(f".{path.name}.lock")
    with file_lock(lock_path):
        previous = load_update_note(root, library, version)
        status = "published" if publish or str(payload.get("status") or "").lower() == "published" else "draft"
        suggestion = _text(payload.get("use_suggestion") or "待确认", limit=40)
        if suggestion not in VALID_SUGGESTIONS:
            suggestion = "待确认"
        author = _text(payload.get("updated_by") or updated_by or "web", limit=80)
        history = list(previous.get("history") or [])
        previous_item = _history_item(previous)
        if previous_item and previous.get("status") not in {"missing", "invalid"}:
            history.insert(0, previous_item)
        note = {
            "schema_version": SCHEMA_VERSION,
            "library": library,
            "version": version,
            "status": status,
            "use_suggestion": suggestion,
            "summary": _text(payload.get("summary"), limit=2000),
            "impact_areas": _list(payload.get("impact_areas")),
            "key_changes": _list(payload.get("key_changes")),
            "risks": _list(payload.get("risks")),
            "must_check": _list(payload.get("must_check")),
            "evidence_refs": _list(payload.get("evidence_refs")),
            "updated_by": author,
            "updated_at": _now(),
            "history": history[:20],
        }
        note["path"] = str(path)
        atomic_write_json(path, note)
        return note


def note_is_available(note: Mapping[str, Any]) -> bool:
    return str(note.get("status") or "").lower() in VALID_STATUSES and bool(str(note.get("summary") or "").strip())
