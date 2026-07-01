"""Shared catalog render helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping
import os
import re

from lib_guard.review.io import as_file_href, read_json
from lib_guard.render import product_theme as ui


def safe(value: Any) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "item")).strip("._")
    return text or "item"


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def version_links(version: Mapping[str, Any]) -> Mapping[str, Any]:
    links = version.get("links") or {}
    return links if isinstance(links, Mapping) else {}


def href(path: Any) -> str:
    return as_file_href(path) if path else ""


def rel_href(base: Path, path: Any) -> str:
    if not path:
        return ""
    try:
        target = Path(str(path))
        if target.is_absolute():
            return Path(os.path.relpath(target, base)).as_posix()
    except Exception:
        pass
    return str(path).replace("\\", "/")


def status_key(value: Any) -> str:
    return str(value or "UNKNOWN").strip().upper()


def truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "ok"}


def short_path(path: Any, limit: int = 72) -> str:
    text = str(path or "-")
    if len(text) <= limit:
        return text
    return "\u2026" + text[-limit:]


def short_name(value: Any, head: int = 26, tail: int = 18) -> str:
    text = str(value or "-")
    if len(text) <= head + tail + 3:
        return text
    return f"{text[:head]}...{text[-tail:]}"


def package_type(version: Mapping[str, Any]) -> str:
    return str(version.get("package_type") or version.get("version_type") or version.get("stage") or "UNKNOWN").upper()


def base_full_version(version: Mapping[str, Any]) -> str | None:
    diff = version.get("diff") or {}
    lineage = version.get("lineage") or {}
    for key in ["base_full_version", "base_version"]:
        value = version.get(key)
        if value:
            return str(value)
    for value in [diff.get("cumulative_base_version"), diff.get("base_version"), lineage.get("base_candidate")]:
        if value:
            return str(value)
    return None


def previous_effective_version(version: Mapping[str, Any]) -> str | None:
    diff = version.get("diff") or {}
    lineage = version.get("lineage") or {}
    for key in ["previous_effective_version", "parent_version"]:
        value = version.get(key)
        if value:
            return str(value)
    for value in [diff.get("adjacent_old_version"), lineage.get("parent_candidate")]:
        if value:
            return str(value)
    return None


def is_full_baseline(version: Mapping[str, Any]) -> bool:
    pkg = package_type(version)
    return bool(truthy(version.get("standalone")) or pkg in {"FULL_PACKAGE", "FULL"})


def relation_status(version: Mapping[str, Any]) -> str:
    pkg = package_type(version)
    if is_full_baseline(version):
        return "FULL_BASELINE"
    base_full = base_full_version(version)
    prev_eff = previous_effective_version(version)
    base_required = truthy(version.get("base_required")) or pkg in {"PARTIAL_UPDATE", "HOTFIX", "DOC_UPDATE", "DOC_ONLY"}
    if base_required and (not base_full or not prev_eff):
        return "NEED_BINDING"
    if prev_eff:
        return "RELATION_OK"
    if bool(version.get("manual_review")):
        return "NEED_BINDING"
    return "RELATION_UNKNOWN"


def relation_label(status: str) -> str:
    return {
        "FULL_BASELINE": "完整基线",
        "RELATION_OK": "关系OK",
        "NEED_BINDING": "需绑定",
        "RELATION_UNKNOWN": "关系未知",
    }.get(status, status)


def _file_review_recommendation(version: Mapping[str, Any]) -> dict[str, Any]:
    rec = version.get("file_diff_recommendation") or version.get("file_review") or {}
    if isinstance(rec, Mapping) and rec:
        return dict(rec)
    pair = version.get("pairwise_summary") or {}
    total = int(pair.get("total", 0) or 0)
    done = int(pair.get("done", 0) or 0)
    return {
        "comparison_quality": version.get("comparison_quality") or "NORMAL",
        "recommended_total": total,
        "result_generated": done,
        "needs_run": max(total - done, 0),
        "candidate_total": int(pair.get("candidate_total", 0) or version.get("changed_file_total", 0) or 0),
        "suppressed_total": int(pair.get("suppressed_total", 0) or 0),
    }


def file_review_text(version: Mapping[str, Any]) -> str:
    rec = _file_review_recommendation(version)
    quality = str(rec.get("comparison_quality") or "NORMAL")
    recommended = int(rec.get("recommended_total", 0) or 0)
    generated = int(rec.get("result_generated", 0) or 0)
    candidates = int(rec.get("candidate_total", 0) or 0)
    if quality.upper() not in {"NORMAL", "PASS", "OK", ""}:
        return f"{ui.status_label(quality)} · 重点 {recommended} · 候选 {candidates}"
    if recommended:
        return f"重点 {recommended} · 已生成 {generated}"
    if candidates:
        return f"候选 {candidates}"
    return "无重点"


def file_review_status(version: Mapping[str, Any]) -> str:
    rec = _file_review_recommendation(version)
    quality = str(rec.get("comparison_quality") or "NORMAL").upper()
    if quality not in {"NORMAL", "PASS", "OK", ""}:
        return quality
    if int(rec.get("needs_run", 0) or 0):
        return "FILE_DIFF_RECOMMENDED"
    if int(rec.get("result_generated", 0) or 0):
        return "FILE_DIFF_DONE"
    if int(rec.get("recommended_total", 0) or 0):
        return "FILE_DIFF_RECOMMENDED"
    return "PAIRWISE_EMPTY"


def node_package_type(version: Mapping[str, Any]) -> str:
    pkg = package_type(version)
    version_id = str(version.get("version_id") or version.get("version") or "").lower()
    stage = str(version.get("stage") or "").lower()
    if pkg in {"FULL_PACKAGE", "FULL"} or version_id.startswith(("stable_", "final_", "initial_")) or stage in {"stable", "final", "initial"}:
        return "full"
    if pkg == "HOTFIX" or stage == "ad-hoc":
        return "hotfix"
    if pkg in {"DOC_UPDATE", "DOC_ONLY"}:
        return "doc"
    if pkg in {"PARTIAL_UPDATE", "PARTIAL"} or version_id.startswith(("patch_", "update_")) or version.get("update_scope"):
        return "partial"
    return "unknown"


def version_diff_summary(diff_dir: Path | None) -> Mapping[str, Any]:
    return read_json(diff_dir / "diff_summary.json", default={}) if diff_dir else {}


def version_file_diff(diff_dir: Path | None) -> Mapping[str, Any]:
    return read_json(diff_dir / "file_diff.json", default={}) if diff_dir else {}


def version_diff_json(diff_dir: Path | None, name: str) -> Mapping[str, Any]:
    return read_json(diff_dir / name, default={}) if diff_dir else {}


def _clip_text(text: str, limit: int = 900) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text[: limit - 1] + "..." if len(text) > limit else text


def relative_display_path(path: Any, *, base: Any = None, tail_parts: int = 4) -> str:
    text = str(path or "-")
    if text == "-":
        return text
    p = Path(text)
    if base:
        try:
            return p.relative_to(Path(str(base))).as_posix()
        except Exception:
            pass
    if p.is_absolute():
        parts = p.parts[-tail_parts:]
        return Path(*parts).as_posix() if parts else p.name
    return text.replace("\\", "/")


def version_release_notes(raw_path: Any, *, limit: int = 3) -> list[dict[str, str]]:
    """Deprecated render helper.

    Catalog/Version Detail rendering must not recursively scan raw libraries.
    Release-note evidence should come from scan artifacts such as
    file_inventory.json or release_readiness.json.
    """
    return []
