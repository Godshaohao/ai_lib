"""Library registry discovery and apply helpers for lib_guard.

This layer is intentionally separate from scan/diff/release:
- discover: RAW messy directories -> editable library.list
- apply: confirmed library.list -> formal library_catalog.yml
- catalog/scan/diff/release consume library_catalog.yml afterwards
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from html import escape as html_escape
from pathlib import Path
from typing import Any, Iterable, Mapping
import json
import os
import re
import tempfile

LIST_COLUMNS = ["status", "library_id", "root_abs", "display_name", "vendor", "middle_path"]
VALID_OK_STATUS = {"OK", "ENABLE", "ENABLED"}
VALID_SKIP_STATUS = {"IGNORE", "SKIP", "DISABLE", "DISABLED", "REVIEW", "CANDIDATE", ""}
DEFAULT_IGNORE_DIRS = {
    ".git",
    "__pycache__",
    "catalog",
    "diff",
    "reports",
    "release_area",
    "scan_out",
    "work",
    "tmp",
    "temp",
    "backup",
    "bak",
    "old",
}
DEFAULT_VERSION_PATTERNS = ["20*", "v*", "initial_*", "stable_*", "release_*", "final_*"]
NEGATIVE_CANDIDATE_DIR_NAMES = DEFAULT_IGNORE_DIRS | {
    ".svn",
    "lef",
    "lib",
    "db",
    "gds",
    "oas",
    "timing",
    "spef",
    "sdc",
    "upf",
    "cpf",
    "doc",
    "docs",
    "script",
    "scripts",
    "source_package",
    "src_package",
}
NEGATIVE_CANDIDATE_PREFIXES = ("upstream_",)
KEY_VIEW_SUFFIXES = {".v", ".sv", ".lef", ".lib", ".db", ".gds", ".oas", ".cdl", ".sp", ".spef", ".sdc", ".upf", ".cpf"}
CORE_VIEW_SUFFIXES = {".v", ".sv", ".lef", ".lib", ".db", ".gds", ".oas", ".cdl", ".sp"}
HINT_SKIP_DIR_NAMES = {".git", ".svn", "__pycache__", "tmp", "temp", "backup", "bak", "old", "work"}
WEAK_NAME_PATTERNS = [
    r"\d{2,8}([._-]\d+)*.*",
    r"v\d+.*",
    r"r\d+.*",
    r"rev.*",
    r"release.*",
    r"final.*",
    r"stable.*",
    r"candidate.*",
    r"drop.*",
    r"update.*",
    r"build.*",
    r"snapshot.*",
    r"golden.*",
    r"tapeout.*",
]


@dataclass
class LibraryCandidate:
    status: str
    library_id: str
    root_abs: str
    display_name: str
    vendor: str
    middle_path: str
    version_count: int
    example_versions: list[str]
    confidence: float
    reason: str


def _atomic_write_text(path: str | Path, text: str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=p.name, suffix=".tmp", dir=str(p.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp_name, p)
    finally:
        try:
            if os.path.exists(tmp_name):
                os.remove(tmp_name)
        except OSError:
            pass


def _atomic_write_json(path: str | Path, data: Any) -> None:
    _atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def _sanitize_id_part(value: str) -> str:
    text = str(value or "").strip()
    text = text.replace("/", "_").replace("\\", "_")
    text = re.sub(r"\s+", "_", text)
    text = re.sub(r"[^0-9A-Za-z_\-.\u0080-\uffff]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("._-")
    return text or "unknown"


def library_id_from_root(raw_root: str | Path, library_root: str | Path) -> str:
    raw = Path(raw_root).resolve()
    root = Path(library_root).resolve()
    rel = root.relative_to(raw)
    return "_".join(_sanitize_id_part(part) for part in rel.parts)


def _is_negative_candidate_dir_name(name: str) -> bool:
    lower = str(name or "").strip().lower()
    if not lower:
        return True
    if lower in NEGATIVE_CANDIDATE_DIR_NAMES:
        return True
    if any(lower.startswith(prefix) for prefix in NEGATIVE_CANDIDATE_PREFIXES):
        return True
    return lower.endswith(("_source_package", "-source-package"))


def _weak_name_signal(name: str) -> str | None:
    lower = str(name or "").strip().lower()
    if not lower or _is_negative_candidate_dir_name(lower):
        return None
    for pattern in WEAK_NAME_PATTERNS:
        if re.fullmatch(pattern, lower):
            return pattern
    return None


def _direct_dirs(path: Path) -> list[Path]:
    try:
        return sorted([p for p in path.iterdir() if p.is_dir() and not _is_negative_candidate_dir_name(p.name)], key=lambda p: p.name.lower())
    except OSError:
        return []


def _bounded_hint_scan(path: Path, *, max_depth: int = 4, max_entries: int = 400) -> set[str]:
    """Return key view suffix hints without reading file contents.

    Candidate roles reject view/source-package directory names, but the hint
    scan may traverse through those package wrappers because real deliveries
    commonly store files under ``*_source_package/lef`` or ``gds``.
    """

    hints: set[str] = set()
    queue: list[tuple[Path, int]] = [(path, 0)]
    checked = 0
    while queue and checked < max_entries:
        current, depth = queue.pop(0)
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    checked += 1
                    if checked > max_entries:
                        break
                    name = entry.name
                    lower = name.lower()
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            if depth < max_depth and lower not in HINT_SKIP_DIR_NAMES:
                                queue.append((Path(entry.path), depth + 1))
                            continue
                        if entry.is_file(follow_symlinks=False):
                            suffix = Path(lower).suffix
                            if suffix in KEY_VIEW_SUFFIXES:
                                hints.add(suffix)
                    except OSError:
                        continue
        except OSError:
            continue
    return hints


def _delivery_instance_from_child(child: Path) -> tuple[bool, set[str], str]:
    if _is_negative_candidate_dir_name(child.name):
        return False, set(), "negative_name"
    hints = _bounded_hint_scan(child)
    if not hints:
        return False, set(), "no_view_hint"
    name_signal = _weak_name_signal(child.name)
    reason = "has_view_hint"
    if name_signal:
        reason += f"+name_hint={name_signal}"
    return True, hints, reason


def _cohort_reason(instance_hints: list[set[str]], min_versions: int) -> tuple[bool, str]:
    if len(instance_hints) < min_versions:
        return False, "too_few_instances"
    non_empty = [hints for hints in instance_hints if hints]
    if len(non_empty) < min_versions:
        return False, "too_few_hint_instances"
    core_count = sum(1 for hints in non_empty if hints & CORE_VIEW_SUFFIXES)
    if core_count >= min(2, min_versions):
        view_summary = ",".join(sorted(set().union(*non_empty)))
        return True, f"cohort_core_views={core_count};views={view_summary}"
    return False, "weak_hints_only"


def _iter_dirs(root: Path, max_depth: int) -> Iterable[Path]:
    root = root.resolve()
    stack: list[tuple[Path, int]] = [(root, 0)]
    while stack:
        path, depth = stack.pop()
        if depth > 0:
            yield path
        if depth >= max_depth:
            continue
        try:
            children = sorted([p for p in path.iterdir() if p.is_dir()], key=lambda p: p.name.lower(), reverse=True)
        except OSError:
            continue
        for child in children:
            if child.name.lower() in DEFAULT_IGNORE_DIRS:
                continue
            stack.append((child, depth + 1))


def _version_children(path: Path) -> list[Path]:
    children = _direct_dirs(path)
    instances = []
    for child in children:
        ok, _hints, _reason = _delivery_instance_from_child(child)
        if ok:
            instances.append(child)
    return instances


def _key_file_hint(path: Path, sample_versions: list[Path]) -> tuple[int, list[str]]:
    hits: list[str] = []
    for version in sample_versions[:3]:
        for suffix in sorted(_bounded_hint_scan(version)):
            hits.append(f"{version.name}/**/*{suffix}")
            if len(hits) >= 5:
                return len(hits), hits
    return len(hits), hits


def _candidate_from_path(raw_root: Path, path: Path, *, min_versions: int) -> LibraryCandidate | None:
    if _is_negative_candidate_dir_name(path.name):
        return None
    versions = _version_children(path)
    coherent, cohort_reason = _cohort_reason([_bounded_hint_scan(version) for version in versions], min_versions)
    if not coherent:
        return None
    key_count, key_examples = _key_file_hint(path, versions)
    rel = path.resolve().relative_to(raw_root.resolve())
    parts = rel.parts
    vendor = parts[0] if len(parts) >= 1 else "unknown"
    display_name = parts[-1] if parts else path.name
    middle_path = "/".join(parts[1:-1]) if len(parts) > 2 else ""
    library_id = library_id_from_root(raw_root, path)
    reason_parts = [f"delivery_instances={len(versions)}", cohort_reason]
    if key_count:
        reason_parts.append("key_files_hint")
    confidence = 0.55 + min(0.25, len(versions) * 0.02) + (0.15 if key_count else 0.0)
    return LibraryCandidate(
        status="REVIEW",
        library_id=library_id,
        root_abs=str(path.resolve()),
        display_name=display_name,
        vendor=vendor,
        middle_path=middle_path,
        version_count=len(versions),
        example_versions=[p.name for p in versions[:5]],
        confidence=round(min(confidence, 0.98), 2),
        reason="+".join(reason_parts),
    )


def _is_descendant(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return child.resolve() != parent.resolve()
    except (OSError, ValueError):
        return False


def _suppress_ancestor_candidates(candidates: list[LibraryCandidate]) -> list[LibraryCandidate]:
    by_path = {Path(item.root_abs): item for item in candidates}
    kept: list[LibraryCandidate] = []
    suppressed: list[LibraryCandidate] = []
    for candidate in sorted(candidates, key=lambda item: len(Path(item.root_abs).parts), reverse=True):
        path = Path(candidate.root_abs)
        if any(_is_descendant(Path(item.root_abs), path) for item in kept):
            suppressed.append(
                LibraryCandidate(
                    status="IGNORE",
                    library_id=candidate.library_id,
                    root_abs=candidate.root_abs,
                    display_name=candidate.display_name,
                    vendor=candidate.vendor,
                    middle_path=candidate.middle_path,
                    version_count=candidate.version_count,
                    example_versions=candidate.example_versions,
                    confidence=candidate.confidence,
                    reason=f"{candidate.reason}+suppressed_by_child",
                )
            )
        else:
            kept.append(by_path[path])
    combined = kept + suppressed
    combined.sort(key=lambda x: (0 if x.status == "REVIEW" else 1, x.vendor, x.middle_path, x.display_name, x.root_abs))
    return combined


def discover_library_candidates(
    raw_root: str | Path,
    *,
    max_depth: int = 8,
    min_versions: int = 2,
    default_status: str = "REVIEW",
) -> list[LibraryCandidate]:
    raw = Path(raw_root).resolve()
    if not raw.exists() or not raw.is_dir():
        raise FileNotFoundError(f"raw_root does not exist or is not a directory: {raw}")
    status = default_status.upper()
    if status not in {"REVIEW", "OK"}:
        raise ValueError("default_status must be REVIEW or OK")
    candidates: list[LibraryCandidate] = []
    stack: list[tuple[Path, int]] = [(raw, 0)]
    while stack:
        path, depth = stack.pop()
        if depth > 0:
            try:
                path.resolve().relative_to(raw)
            except (OSError, ValueError):
                continue
            item = _candidate_from_path(raw, path, min_versions=min_versions)
            if item:
                candidates.append(item)
        if depth >= max_depth:
            continue
        try:
            children = sorted([p for p in path.iterdir() if p.is_dir()], key=lambda p: p.name.lower(), reverse=True)
        except OSError:
            continue
        for child in children:
            if child.name.lower() in DEFAULT_IGNORE_DIRS:
                continue
            try:
                child.resolve().relative_to(raw)
            except (OSError, ValueError):
                continue
            stack.append((child, depth + 1))
    return _suppress_ancestor_candidates(candidates)


def write_library_list(path: str | Path, candidates: list[LibraryCandidate]) -> None:
    lines = [
        "# 候选快照。把真实库根标为 OK 后运行：lg.csh library accept",
        "# 稳定人工 registry 位于 config/library_registry.tsv；discover 不会覆盖它。",
        "# status: OK = 合并进 registry；IGNORE = 排除；REVIEW = 暂缓",
        "# library_id 在这里表示正式库名；若自动路径名不合适，请用：lg.csh library add <formal_id> --root <library_root>",
        "\t".join(LIST_COLUMNS),
    ]
    for item in candidates:
        row = [item.status, item.library_id, item.root_abs, item.display_name, item.vendor, item.middle_path]
        lines.append("\t".join(str(x or "") for x in row))
    _atomic_write_text(path, "\n".join(lines) + "\n")


def write_library_rows(path: str | Path, rows: list[Mapping[str, Any]], *, header_note: str | None = None) -> None:
    lines = []
    if header_note:
        lines.append(f"# {header_note}")
    lines.append("\t".join(LIST_COLUMNS))
    for row in rows:
        lines.append("\t".join(str(row.get(column, "") or "") for column in LIST_COLUMNS))
    _atomic_write_text(path, "\n".join(lines) + "\n")


def render_discovery_html(path: str | Path, candidates: list[LibraryCandidate]) -> None:
    rows = []
    for item in candidates:
        rows.append(
            "<tr>"
            f"<td>{html_escape(item.status)}</td>"
            f"<td><code>{html_escape(item.library_id)}</code></td>"
            f"<td>{html_escape(item.vendor)}</td>"
            f"<td>{html_escape(item.middle_path)}</td>"
            f"<td>{html_escape(item.display_name)}</td>"
            f"<td><code>{html_escape(item.root_abs)}</code></td>"
            f"<td>{item.version_count}</td>"
            f"<td>{html_escape(', '.join(item.example_versions))}</td>"
            f"<td>{item.confidence:.2f}</td>"
            f"<td>{html_escape(item.reason)}</td>"
            "</tr>"
        )
    text = """<!doctype html>
<html><head><meta charset='utf-8'><title>库候选发现</title>
<style>
body{font-family:Arial,sans-serif;margin:24px;background:#f6f7fb;color:#151923}table{border-collapse:collapse;width:100%;background:white}th,td{border:1px solid #ddd;padding:8px;text-align:left;vertical-align:top}th{background:#eef1f8}code{white-space:nowrap}.hint{color:#5b6375;margin-bottom:16px;line-height:1.7}.tag{display:inline-block;border:1px solid #c9d2e3;border-radius:6px;padding:2px 6px;background:#fff}
</style></head><body>
<h1>库候选发现</h1>
<div class='hint'><span class='tag'>候选快照</span> 这里不是正式 registry。把真实库根标为 <code>OK</code> 后运行 <code>lg.csh library accept</code>；已知库根直接用 <code>lg.csh library add &lt;正式库名&gt; --root &lt;库根目录&gt;</code>。</div>
<table><thead><tr><th>状态</th><th>正式库名</th><th>Vendor</th><th>中间路径</th><th>显示名</th><th>库根目录</th><th>版本数</th><th>版本示例</th><th>置信度</th><th>判定原因</th></tr></thead><tbody>
""" + "\n".join(rows) + "\n</tbody></table></body></html>\n"
    _atomic_write_text(path, text)


def read_library_list(path: str | Path) -> list[dict[str, str]]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"library.list not found: {p}")
    rows: list[dict[str, str]] = []
    header: list[str] | None = None
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip("\n")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = line.split("\t")
        if header is None:
            header = [x.strip() for x in parts]
            missing = [x for x in LIST_COLUMNS if x not in header]
            if missing:
                raise ValueError(f"library.list header missing columns: {missing}")
            continue
        if len(parts) < len(header):
            parts += [""] * (len(header) - len(parts))
        rows.append({header[i]: parts[i].strip() for i in range(len(header))})
    return rows


def _upsert_registry_rows(existing: list[dict[str, str]], incoming: list[dict[str, str]]) -> list[dict[str, str]]:
    by_root: dict[str, dict[str, str]] = {str(Path(row.get("root_abs", "")).resolve()): dict(row) for row in existing if row.get("root_abs")}
    ordered_roots = [str(Path(row.get("root_abs", "")).resolve()) for row in existing if row.get("root_abs")]
    for row in incoming:
        root_text = str(row.get("root_abs") or "").strip()
        if not root_text:
            continue
        root_key = str(Path(root_text).resolve())
        clean = {column: str(row.get(column, "") or "") for column in LIST_COLUMNS}
        clean["status"] = "OK"
        clean["root_abs"] = root_key
        by_root[root_key] = clean
        if root_key not in ordered_roots:
            ordered_roots.append(root_key)
    return [by_root[root] for root in ordered_roots if root in by_root]


def add_library_to_registry(
    raw_root: str | Path,
    *,
    registry_path: str | Path,
    library_id: str,
    root_abs: str | Path,
    display_name: str | None = None,
    vendor: str | None = None,
    middle_path: str | None = None,
) -> dict[str, Any]:
    raw = Path(raw_root).resolve()
    root = Path(root_abs).resolve()
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(f"library root does not exist or is not a directory: {root}")
    if not _is_under(root, raw):
        raise ValueError(f"library root is outside RAW: {root}")
    rel = root.relative_to(raw)
    parts = rel.parts
    clean_vendor = vendor or (parts[0] if parts else "")
    clean_display = display_name or (parts[-1] if parts else root.name)
    clean_middle = middle_path if middle_path is not None else "/".join(parts[1:-1]) if len(parts) > 2 else ""
    row = {
        "status": "OK",
        "library_id": str(library_id).strip(),
        "root_abs": str(root),
        "display_name": clean_display,
        "vendor": clean_vendor,
        "middle_path": clean_middle,
    }
    registry = Path(registry_path)
    existing = read_library_list(registry) if registry.exists() else []
    rows = _upsert_registry_rows(existing, [row])
    write_library_rows(registry, rows, header_note="稳定人工 library registry。请谨慎编辑；正式 catalog 只使用 OK 行。library_id 表示正式库名。")
    return {"status": "PASS", "registry": str(registry), "library_id": row["library_id"], "root_abs": str(root), "count": len(rows)}


def accept_candidates_to_registry(
    raw_root: str | Path,
    *,
    candidates_path: str | Path,
    registry_path: str | Path,
) -> dict[str, Any]:
    raw = Path(raw_root).resolve()
    candidates = read_library_list(candidates_path)
    accepted = []
    skipped = 0
    for row in candidates:
        status = str(row.get("status") or "").upper()
        if status not in VALID_OK_STATUS:
            skipped += 1
            continue
        root_text = str(row.get("root_abs") or "").strip()
        if not root_text:
            skipped += 1
            continue
        root = Path(root_text).resolve()
        if not root.exists() or not root.is_dir() or not _is_under(root, raw):
            skipped += 1
            continue
        clean = {column: str(row.get(column, "") or "") for column in LIST_COLUMNS}
        clean["status"] = "OK"
        clean["root_abs"] = str(root)
        accepted.append(clean)
    registry = Path(registry_path)
    existing = read_library_list(registry) if registry.exists() else []
    rows = _upsert_registry_rows(existing, accepted)
    write_library_rows(registry, rows, header_note="稳定人工 library registry。请谨慎编辑；正式 catalog 只使用 OK 行。library_id 表示正式库名。")
    return {"status": "PASS", "registry": str(registry), "accepted": len(accepted), "skipped": skipped, "count": len(rows)}


def _is_under(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _yaml_quote(value: Any) -> str:
    text = "" if value is None else str(value)
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _formal_library_identity(item: Mapping[str, str]) -> tuple[str, str | None]:
    original_id = str(item.get("library_id") or "").strip()
    vendor = str(item.get("vendor") or "").strip()
    display = str(item.get("display_name") or "").strip()
    middle_path = str(item.get("middle_path") or "").strip()
    if "." in original_id:
        parts = [part for part in original_id.split(".") if part]
        if not vendor and parts:
            vendor = parts[0]
        if not display and parts:
            display = parts[-1]
        category = ".".join(parts[1:-1]) if len(parts) > 2 else None
        return original_id, category
    if not vendor:
        vendor = original_id.split("_")[0] if "_" in original_id else "unknown"
    if not display:
        display = original_id.split("_")[-1] if original_id else "unknown"
    category: str | None = None
    parts = [part for part in middle_path.replace("\\", "/").split("/") if part]
    if parts:
        category = ".".join(_sanitize_id_part(part) for part in parts)
    elif display.startswith("openroad_"):
        category = "openroad_platform"
    formal_parts = [_sanitize_id_part(vendor)]
    if category:
        formal_parts.append(category)
    formal_parts.append(_sanitize_id_part(display))
    return ".".join(formal_parts), category


def _rel_root(raw_root: Path, root_abs: Path) -> str:
    return root_abs.resolve().relative_to(raw_root.resolve()).as_posix()


def validate_library_rows(raw_root: str | Path, rows: list[dict[str, str]]) -> tuple[list[dict[str, str]], list[str], list[str]]:
    raw = Path(raw_root).resolve()
    errors: list[str] = []
    warnings: list[str] = []
    selected: list[dict[str, str]] = []
    seen_ids: dict[str, str] = {}
    seen_roots: dict[str, str] = {}
    for idx, row in enumerate(rows, start=2):
        status = str(row.get("status") or "").upper()
        if status in VALID_SKIP_STATUS:
            continue
        if status not in VALID_OK_STATUS:
            errors.append(f"line {idx}: invalid status {status!r}; use OK/IGNORE/REVIEW")
            continue
        library_id = str(row.get("library_id") or "").strip()
        root_text = str(row.get("root_abs") or "").strip()
        if not library_id:
            errors.append(f"line {idx}: empty library_id")
            continue
        if not root_text:
            errors.append(f"line {idx}: empty root_abs for {library_id}")
            continue
        root = Path(root_text).resolve()
        if not root.exists() or not root.is_dir():
            errors.append(f"line {idx}: root_abs does not exist or is not a directory: {root}")
            continue
        if not _is_under(root, raw):
            errors.append(f"line {idx}: root_abs is outside RAW: {root}")
            continue
        if _is_negative_candidate_dir_name(root.name):
            errors.append(f"line {idx}: root_abs is not a library root: {root}")
            continue
        if library_id in seen_ids:
            errors.append(f"line {idx}: duplicate library_id {library_id}; previous root={seen_ids[library_id]}")
            continue
        root_key = str(root)
        if root_key in seen_roots:
            errors.append(f"line {idx}: duplicate root_abs {root}; previous library_id={seen_roots[root_key]}")
            continue
        seen_ids[library_id] = root_key
        seen_roots[root_key] = library_id
        clean = dict(row)
        clean["status"] = "OK"
        clean["library_id"] = library_id
        clean["root_abs"] = root_key
        clean.setdefault("display_name", library_id.split("_")[-1])
        clean.setdefault("vendor", library_id.split("_")[0])
        clean.setdefault("middle_path", "")
        selected.append(clean)
    roots = [(item["library_id"], Path(item["root_abs"])) for item in selected]
    for i, (id_a, root_a) in enumerate(roots):
        for id_b, root_b in roots[i + 1 :]:
            if _is_under(root_a, root_b) or _is_under(root_b, root_a):
                errors.append(f"root overlap: {id_a}={root_a} ; {id_b}={root_b}")
    return selected, errors, warnings


def write_library_catalog(raw_root: str | Path, rows: list[dict[str, str]], out_path: str | Path, *, library_type: str = "ip") -> dict[str, Any]:
    raw = Path(raw_root).resolve()
    selected, errors, warnings = validate_library_rows(raw, rows)
    if errors:
        return {"status": "FAILED", "errors": errors, "warnings": warnings, "selected": len(selected)}
    lines = [
        "version: 1",
        f"raw_root: {_yaml_quote(raw)}",
        "",
        "defaults:",
        f"  library_type: {_yaml_quote(library_type)}",
        "  version_patterns:",
        *[f"    - {_yaml_quote(x)}" for x in DEFAULT_VERSION_PATTERNS],
        "  ignore_version_dirs:",
        "    - .git",
        "    - doc",
        "    - docs",
        "    - tmp",
        "    - backup",
        "    - old",
        "",
        "libraries:",
    ]
    for item in selected:
        root_abs = Path(item["root_abs"]).resolve()
        original_library_id = item["library_id"]
        library_id, category = _formal_library_identity(item)
        display = item.get("display_name") or library_id.split("_")[-1]
        vendor = item.get("vendor") or library_id.split("_")[0]
        middle_path = item.get("middle_path") or ""
        aliases = [display]
        if original_library_id != library_id:
            aliases.append(original_library_id)
        lines.extend(
            [
                f"  {library_id}:",
                "    enabled: true",
                f"    library_type: {_yaml_quote(library_type)}",
                f"    vendor: {_yaml_quote(vendor)}",
                f"    category: {_yaml_quote(category)}",
                f"    middle_path: {_yaml_quote(middle_path)}",
                f"    display_name: {_yaml_quote(display)}",
                f"    root_abs: {_yaml_quote(root_abs)}",
                f"    root: {_yaml_quote(_rel_root(raw, root_abs))}",
                "    aliases:",
                *[f"      - {_yaml_quote(alias)}" for alias in aliases],
                "",
            ]
        )
    _atomic_write_text(out_path, "\n".join(lines).rstrip() + "\n")
    return {"status": "PASS", "out": str(out_path), "selected": len(selected), "warnings": warnings}


def discover_to_files(
    raw_root: str | Path,
    *,
    list_out: str | Path,
    json_out: str | Path | None = None,
    html_out: str | Path | None = None,
    max_depth: int = 8,
    min_versions: int = 2,
    default_status: str = "REVIEW",
) -> dict[str, Any]:
    candidates = discover_library_candidates(raw_root, max_depth=max_depth, min_versions=min_versions, default_status=default_status)
    write_library_list(list_out, candidates)
    if json_out:
        _atomic_write_json(json_out, {"raw_root": str(Path(raw_root).resolve()), "candidates": [asdict(x) for x in candidates]})
    if html_out:
        render_discovery_html(html_out, candidates)
    return {"status": "PASS", "raw_root": str(Path(raw_root).resolve()), "list_out": str(list_out), "json_out": str(json_out) if json_out else None, "html_out": str(html_out) if html_out else None, "candidate_count": len(candidates)}


def apply_list_to_catalog(
    raw_root: str | Path,
    *,
    list_path: str | Path,
    out_path: str | Path,
    library_type: str = "ip",
) -> dict[str, Any]:
    rows = read_library_list(list_path)
    result = write_library_catalog(raw_root, rows, out_path, library_type=library_type)
    result["list_path"] = str(list_path)
    result["raw_root"] = str(Path(raw_root).resolve())
    return result
