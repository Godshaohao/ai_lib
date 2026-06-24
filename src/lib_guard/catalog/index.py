from __future__ import annotations

from datetime import datetime, timezone
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, Mapping
from collections import Counter
import json
import hashlib
import os
import re
import tempfile


STAGES = ["initial", "stable", "final", "ad-hoc", "dated", "unknown"]
DEFAULT_IGNORE_DIRS = [
    ".git",
    "__pycache__",
    "catalog",
    "diff",
    "index",
    "pages",
    "release_area",
    "reports",
    "scan_out",
    "source_package",
    "work",
]
DEFAULT_STAGE_RULES = [
    {"match": "*initial*", "stage": "initial"},
    {"match": "*stable*", "stage": "stable"},
    {"match": "*final*", "stage": "final"},
    {"match": "*ad-hoc*", "stage": "ad-hoc"},
    {"match": "*adhoc*", "stage": "ad-hoc"},
]


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _read_json(path: str | Path, default: Any = None) -> Any:
    p = Path(path)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def _sha256_file(path: str | Path | None) -> str | None:
    if not path:
        return None
    p = Path(path)
    if not p.exists() or not p.is_file():
        return None
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _write_json(path: str | Path, data: Any) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=p.name, suffix=".tmp", dir=str(p.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp_name, p)
    finally:
        try:
            if os.path.exists(tmp_name):
                os.remove(tmp_name)
        except OSError:
            pass


def _load_policy(policy_path: str | Path | None) -> dict[str, Any]:
    # JSON policy is still supported. YAML library_catalog.yml is treated as a
    # formal library map: catalog discovery must start from confirmed library
    # roots rather than guessing every RAW directory.
    policy: dict[str, Any] = {}
    yaml_library_catalog = False
    if policy_path:
        p = Path(policy_path)
        if p.exists() and p.suffix.lower() in {".yml", ".yaml"}:
            text = p.read_text(encoding="utf-8", errors="ignore")
            if "libraries:" in text:
                yaml_library_catalog = True
                policy = {"library_map": str(p), "pattern_fallback": False}
        else:
            loaded = _read_json(p, {}) if p.exists() else {}
            policy = dict(loaded) if isinstance(loaded, Mapping) else {}
    if not isinstance(policy, Mapping):
        policy = {}
    ignore_dirs = list(dict.fromkeys(DEFAULT_IGNORE_DIRS + [str(x) for x in policy.get("ignore_dirs", []) or []]))
    discovery = policy.get("discovery") if isinstance(policy.get("discovery"), Mapping) else {}
    discovery_patterns = discovery.get("patterns") if isinstance(discovery.get("patterns"), list) else []
    version_path_rules = list(policy.get("version_path_rules") or [])
    for pattern in discovery_patterns:
        if isinstance(pattern, str):
            version_path_rules.append({"pattern": pattern})
        elif isinstance(pattern, Mapping):
            version_path_rules.append(dict(pattern))
    return {
        "_policy_path": str(policy_path) if policy_path else None,
        "library_type": policy.get("library_type"),
        "library_name": policy.get("library_name"),
        "discovery": dict(discovery),
        "library_map": policy.get("library_map") or discovery.get("library_map"),
        "pattern_fallback": False if yaml_library_catalog else discovery.get("pattern_fallback", policy.get("pattern_fallback", True)),
        "stage_rules": policy.get("stage_rules") or DEFAULT_STAGE_RULES,
        "ignore_dirs": ignore_dirs,
        "version_path_rules": version_path_rules,
        "marker_files": policy.get("marker_files") or ["README", "README.md", "VERSION", "release_note.txt"],
    }


def _stage_for(version_id: str, rules: list[Mapping[str, Any]]) -> tuple[str, list[str]]:
    lower = version_id.lower()
    matched: list[str] = []
    for idx, rule in enumerate(rules):
        pattern = str(rule.get("match") or rule.get("contains") or "").lower()
        stage = str(rule.get("stage") or "unknown")
        ok = False
        if rule.get("contains"):
            ok = str(rule.get("contains")).lower() in lower
        elif pattern:
            ok = fnmatch(lower, pattern)
        if ok and stage in STAGES:
            matched.append(f"stage_rules.{idx}.{stage}")
            return stage, matched
    if re.match(r"^20\d{6}[_-]", version_id):
        return "dated", ["date_prefix.dated"]
    return "unknown", []


def _version_sort_key(version_id: str) -> tuple[int, str]:
    match = re.search(r"(20\d{6})", version_id)
    if match:
        return int(match.group(1)), version_id
    nums = re.findall(r"\d+", version_id)
    if nums:
        joined = "".join(n.zfill(4) for n in nums[:4])
        return int(joined[:12] or "0"), version_id
    return 0, version_id


def _version_type(stage: str) -> str:
    if stage == "final":
        return "full"
    if stage == "ad-hoc":
        return "hotfix"
    if stage in {"initial", "stable"}:
        return "candidate"
    if stage == "dated":
        return "candidate"
    return "daily"


def _coerce_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        raw_items = re.split(r"[,;\s]+", value)
    elif isinstance(value, (list, tuple, set)):
        raw_items = list(value)
    else:
        raw_items = [value]
    return [str(item).strip() for item in raw_items if str(item).strip()]


def _sync_diff_target(
    diff: dict[str, Any],
    *,
    target: str | None,
    status_key: str,
    version_key: str,
    dir_key: str,
    html_key: str,
) -> None:
    previous_target = diff.get(version_key)
    if not target:
        diff[status_key] = "NOT_APPLICABLE"
        diff[version_key] = None
        diff[dir_key] = None
        diff[html_key] = None
        return
    if previous_target != target:
        diff[status_key] = "PENDING"
        diff[dir_key] = None
        diff[html_key] = None
    elif diff.get(status_key) in {None, "NOT_APPLICABLE"}:
        diff[status_key] = "PENDING"
    diff[version_key] = target


def _sync_version_relation_fields(item: dict[str, Any]) -> dict[str, Any]:
    """Keep new relation semantics and legacy diff fields consistent."""

    version_id = str(item.get("version_id") or "")
    lineage = dict(item.get("lineage", {}) or {})
    diff = dict(item.get("diff", {}) or {})

    previous_effective = item.get("previous_effective_version") or lineage.get("parent_candidate") or diff.get("adjacent_old_version")
    base_full = item.get("base_full_version") or item.get("base_version") or lineage.get("base_candidate") or diff.get("cumulative_base_version")
    previous_effective = str(previous_effective) if previous_effective else None
    base_full = str(base_full) if base_full else None

    if previous_effective:
        item["previous_effective_version"] = previous_effective
        lineage["parent_candidate"] = previous_effective
    if base_full:
        item["base_full_version"] = base_full
        item["base_version"] = base_full
        lineage["base_candidate"] = base_full
    item["lineage"] = lineage

    cumulative_target = base_full if base_full and base_full != version_id else None
    _sync_diff_target(diff, target=previous_effective, status_key="adjacent_status", version_key="adjacent_old_version", dir_key="adjacent_diff_dir", html_key="adjacent_diff_html")
    _sync_diff_target(diff, target=cumulative_target, status_key="cumulative_status", version_key="cumulative_base_version", dir_key="cumulative_diff_dir", html_key="cumulative_diff_html")
    if bool(item.get("manual_review")) and cumulative_target:
        _sync_diff_target(diff, target=cumulative_target, status_key="base_status", version_key="base_version", dir_key="base_diff_dir", html_key="base_diff_html")
    elif not bool(item.get("manual_review")):
        diff.setdefault("base_status", "NOT_APPLICABLE")
        diff.setdefault("base_version", None)
        diff.setdefault("base_diff_dir", None)
        diff.setdefault("base_diff_html", None)
    item["diff"] = diff
    item.setdefault("compare_default", "previous_effective" if previous_effective else "full_baseline" if cumulative_target else "none")
    return item


def _count_files(path: Path, limit: int = 5000) -> int:
    count = 0
    for item in path.rglob("*"):
        if item.is_file():
            count += 1
            if count >= limit:
                return count
    return count


def _pattern_to_regex(pattern: str) -> re.Pattern[str]:
    parts: list[str] = ["^"]
    idx = 0
    for match in re.finditer(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", pattern):
        parts.append(re.escape(pattern[idx:match.start()]))
        name = match.group(1)
        parts.append(fr"(?P<{name}>[^/\\]+)")
        idx = match.end()
    parts.append(re.escape(pattern[idx:]))
    parts.append("$")
    return re.compile("".join(parts).replace(r"\*", ".*"))


def _has_ignored_part(path: Path, root: Path, ignore: set[str]) -> bool:
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        parts = path.parts
    return any(part.lower() in ignore for part in parts)


def _rule_library_name(rule: Mapping[str, Any], policy: Mapping[str, Any], match: re.Match[str]) -> str | None:
    groups = {k: v for k, v in match.groupdict().items() if v is not None}
    template = rule.get("library_id_template") or rule.get("library_name_template")
    if template:
        try:
            return str(template).format(**groups)
        except KeyError:
            pass
    if groups.get("vendor") or groups.get("category"):
        parts = [groups.get("vendor"), groups.get("category"), groups.get("library")]
        return ".".join(str(p) for p in parts if p)
    return (
        groups.get("library")
        or rule.get("library")
        or rule.get("library_name")
        or policy.get("library_name")
    )


def _looks_like_version(version_id: str, matched_stage_rules: list[str]) -> bool:
    return bool(matched_stage_rules or re.search(r"\d", version_id))


def _item_looks_like_version(item: Mapping[str, Any]) -> bool:
    return _looks_like_version(str(item.get("version_id") or ""), (item.get("detected", {}) or {}).get("matched_rules", []) or [])


def _inventory_evidence(path: Path, policy: Mapping[str, Any], limit: int = 5000) -> dict[str, Any]:
    from lib_guard.scan.file_classifier import FileClassifier

    classifier = FileClassifier()
    counts: Counter[str] = Counter()
    total = 0
    for item in path.rglob("*"):
        if not item.is_file():
            continue
        total += 1
        rel = item.relative_to(path).as_posix()
        record = classifier.classify({"path": rel, "name": item.name})
        counts[str(record.get("file_type") or "unknown")] += 1
        if total >= limit:
            break
    markers = []
    for marker in policy.get("marker_files", []) or []:
        marker_path = path / str(marker)
        if marker_path.exists():
            markers.append(str(marker))
    return {
        "evidence_mode": "sampled",
        "file_count": total,
        "file_type_counts": dict(sorted(counts.items())),
        "key_file_count": sum(counts.get(t, 0) for t in ["verilog", "lef", "liberty", "cdl", "db", "gds"]),
        "truncated": total >= limit,
    } | {"markers": markers}


def _inventory_evidence_fast(path: Path, policy: Mapping[str, Any]) -> dict[str, Any]:
    """Directory-only catalog evidence.

    This intentionally avoids ``path.rglob('*')`` so catalog refresh stays fast
    on multi-vendor RAW trees. Full file-type evidence is produced by real
    per-version scan reports, or by catalog --with-evidence when explicitly
    requested.
    """
    markers = []
    for marker in policy.get("marker_files", []) or []:
        marker_path = path / str(marker)
        if marker_path.exists():
            markers.append(str(marker))
    return {
        "evidence_mode": "fast",
        "file_count": None,
        "file_type_counts": {},
        "key_file_count": 0,
        "truncated": False,
        "markers": markers,
    }


def _confidence(*, stage: str, structure_rule: str | None, inventory: Mapping[str, Any], matched_rules: list[str]) -> float:
    score = 0.25
    if structure_rule:
        score += 0.3
    if matched_rules:
        score += 0.2
    if int(inventory.get("key_file_count") or 0) > 0:
        score += 0.2
    if inventory.get("markers"):
        score += 0.05
    if stage == "unknown":
        score -= 0.15
    return round(max(0.05, min(0.99, score)), 2)


def _detected(
    path: Path,
    version_id: str,
    stage: str,
    matched: list[str],
    policy: Mapping[str, Any],
    structure_rule: str | None = None,
    *,
    collect_evidence: bool = False,
) -> dict[str, Any]:
    evidence = _inventory_evidence(path, policy) if collect_evidence else _inventory_evidence_fast(path, policy)
    markers = list(evidence.pop("markers", []) or [])
    file_count_hint = evidence.get("file_count")
    return {
        "path_name": version_id,
        "mtime": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat().replace("+00:00", "Z"),
        "size_hint": None,
        "file_count_hint": file_count_hint,
        "matched_rules": matched,
        "structure_rule": structure_rule,
        "inventory": evidence,
        "markers": markers,
        "confidence": _confidence(stage=stage, structure_rule=structure_rule, inventory={**evidence, "markers": markers}, matched_rules=matched),
    }


def _discover_by_rules(root: Path, library_type: str, policy: Mapping[str, Any], *, collect_evidence: bool = False) -> dict[str, list[dict[str, Any]]]:
    libraries: dict[str, list[dict[str, Any]]] = {}
    rules = [r for r in policy.get("version_path_rules", []) or [] if isinstance(r, Mapping) and r.get("pattern")]
    if not rules:
        return libraries
    ignore = set(str(x).lower() for x in policy.get("ignore_dirs", []))
    compiled = [(rule, str(rule.get("pattern")), _pattern_to_regex(str(rule.get("pattern")))) for rule in rules]
    for candidate in sorted([p for p in root.rglob("*") if p.is_dir() and not _has_ignored_part(p, root, ignore)], key=lambda p: p.as_posix().lower()):
        rel = candidate.relative_to(root).as_posix()
        for rule, pattern, regex in compiled:
            match = regex.match(rel)
            if not match:
                continue
            lib_name = _rule_library_name(rule, policy, match)
            version_id = match.groupdict().get("version")
            if not lib_name or not version_id:
                continue
            stage, matched = _stage_for(version_id, list(policy.get("stage_rules", DEFAULT_STAGE_RULES)))
            if "{library}" not in pattern and not _looks_like_version(version_id, matched):
                continue
            libraries.setdefault(lib_name, []).append(
                {
                    "library_type": library_type,
                    "library_name": lib_name,
                    "library_root": str(candidate.parent),
                    "display_name": match.groupdict().get("library") or lib_name,
                    "vendor": match.groupdict().get("vendor"),
                    "category": match.groupdict().get("category"),
                    "aliases": [],
                    "version_id": version_id,
                    "stage": stage,
                    "raw_path": str(candidate),
                    "detected": _detected(candidate, version_id, stage, matched, policy, structure_rule=pattern, collect_evidence=collect_evidence),
                }
            )
            break
    return libraries


def _discover_by_library_map(root: Path, library_type: str, policy: Mapping[str, Any], *, collect_evidence: bool = False) -> dict[str, list[dict[str, Any]]]:
    from lib_guard.discovery import discover_versions, load_library_map

    libraries: dict[str, list[dict[str, Any]]] = {}
    ignore = set(str(x).lower() for x in policy.get("ignore_dirs", []))
    refs = load_library_map(root, policy, policy.get("_policy_path"))
    for ref in refs:
        ref_type = ref.library_type or library_type
        if ref_type != library_type:
            continue
        versions = discover_versions(ref, ignore)
        for version in versions:
            stage, matched = _stage_for(version.version_id, list(policy.get("stage_rules", DEFAULT_STAGE_RULES)))
            detected = _detected(version.path, version.version_id, stage, matched, policy, structure_rule=version.structure_rule, collect_evidence=collect_evidence)
            detected["discovery_source"] = version.discovery_source
            libraries.setdefault(ref.library_id, []).append(
                {
                    "library_type": library_type,
                    "library_name": ref.library_id,
                    "library_root": str(ref.root),
                    "display_name": ref.display_name or ref.library_id,
                    "vendor": ref.vendor,
                    "category": ref.category,
                    "middle_path": getattr(ref, "middle_path", None),
                    "aliases": list(ref.aliases),
                    "version_id": version.version_id,
                    "stage": stage,
                    "raw_path": str(version.path),
                    "detected": detected,
                }
            )
    return libraries


def _discover_flat_version_root(root: Path, library_type: str, policy: Mapping[str, Any], ignore: set[str], *, collect_evidence: bool = False) -> dict[str, list[dict[str, Any]]]:
    library_name = str(policy.get("library_name") or root.name)
    versions: list[dict[str, Any]] = []
    if not root.exists():
        return {}
    for version_dir in sorted([p for p in root.iterdir() if p.is_dir() and p.name.lower() not in ignore], key=lambda p: p.name.lower()):
        stage, matched = _stage_for(version_dir.name, list(policy.get("stage_rules", DEFAULT_STAGE_RULES)))
        if not _looks_like_version(version_dir.name, matched):
            continue
        versions.append(
            {
                "library_type": library_type,
                "library_name": library_name,
                "library_root": str(root),
                "display_name": library_name,
                "vendor": None,
                "category": None,
                "aliases": [],
                "version_id": version_dir.name,
                "stage": stage,
                "raw_path": str(version_dir),
                "detected": _detected(version_dir, version_dir.name, stage, matched, policy, structure_rule="auto-flat:{version}", collect_evidence=collect_evidence),
            }
        )
    return {library_name: versions} if versions else {}


def _discover(root: Path, library_type: str, policy: Mapping[str, Any], *, collect_evidence: bool = False) -> dict[str, list[dict[str, Any]]]:
    ignore = set(str(x).lower() for x in policy.get("ignore_dirs", []))
    libraries: dict[str, list[dict[str, Any]]] = _discover_by_library_map(root, library_type, policy, collect_evidence=collect_evidence)
    if libraries and policy.get("pattern_fallback") is False:
        return libraries
    mapped_paths = {str(Path(item["raw_path"])) for items in libraries.values() for item in items}
    rule_libraries = _discover_by_rules(root, library_type, policy, collect_evidence=collect_evidence)
    for lib_name, items in rule_libraries.items():
        filtered = [item for item in items if str(Path(item["raw_path"])) not in mapped_paths]
        if filtered:
            libraries.setdefault(lib_name, []).extend(filtered)
    seen_paths = {str(Path(item["raw_path"])) for items in libraries.values() for item in items}
    if not root.exists():
        raise FileNotFoundError(f"catalog root does not exist: {root}")
    if libraries and policy.get("version_path_rules"):
        return libraries
    if not libraries:
        flat_libraries = _discover_flat_version_root(root, library_type, policy, ignore, collect_evidence=collect_evidence)
        if len(next(iter(flat_libraries.values()), [])) > 1:
            return flat_libraries
    for lib_dir in sorted([p for p in root.iterdir() if p.is_dir() and p.name.lower() not in ignore], key=lambda p: p.name.lower()):
        version_dirs = [p for p in lib_dir.iterdir() if p.is_dir() and p.name.lower() not in ignore]
        if not version_dirs:
            version_dirs = [lib_dir]
        for version_dir in sorted(version_dirs, key=lambda p: p.name.lower()):
            if str(version_dir) in seen_paths:
                continue
            lib_name = lib_dir.name
            version_id = version_dir.name
            stage, matched = _stage_for(version_id, list(policy.get("stage_rules", DEFAULT_STAGE_RULES)))
            libraries.setdefault(lib_name, []).append(
                {
                    "library_type": library_type,
                    "library_name": lib_name,
                    "library_root": str(lib_dir),
                    "display_name": lib_name,
                    "vendor": None,
                    "category": None,
                    "aliases": [],
                    "version_id": version_id,
                    "stage": stage,
                    "raw_path": str(version_dir),
                    "detected": _detected(version_dir, version_id, stage, matched, policy, structure_rule="default:{library}/{version}", collect_evidence=collect_evidence),
                }
            )
    return libraries


def _library_filter_names_for_ref(ref: Any, library_type: str) -> set[str]:
    ref_type = getattr(ref, "library_type", None) or library_type
    library_id = str(getattr(ref, "library_id", "") or "")
    display_name = str(getattr(ref, "display_name", "") or "")
    names = {library_id, f"{ref_type}/{library_id}"}
    if display_name:
        names.add(display_name)
    names.update(str(a) for a in getattr(ref, "aliases", ()) or () if str(a))
    return {name for name in names if name}


def _discover_from_library_ref(ref: Any, library_type: str, policy: Mapping[str, Any], ignore: set[str], *, collect_evidence: bool = False) -> dict[str, list[dict[str, Any]]]:
    from lib_guard.discovery import discover_versions

    ref_type = getattr(ref, "library_type", None) or library_type
    versions = discover_versions(ref, ignore)
    items: list[dict[str, Any]] = []
    for version in versions:
        stage, matched = _stage_for(version.version_id, list(policy.get("stage_rules", DEFAULT_STAGE_RULES)))
        detected = _detected(version.path, version.version_id, stage, matched, policy, structure_rule=version.structure_rule, collect_evidence=collect_evidence)
        detected["discovery_source"] = version.discovery_source
        items.append(
            {
                "library_type": ref_type,
                "library_name": ref.library_id,
                "library_root": str(ref.root),
                "display_name": ref.display_name or ref.library_id,
                "vendor": ref.vendor,
                "category": ref.category,
                "aliases": list(ref.aliases),
                "version_id": version.version_id,
                "stage": stage,
                "raw_path": str(version.path),
                "detected": detected,
            }
        )
    return {ref.library_id: items} if items else {}


def _discover_single_library(
    root: Path,
    library_type: str,
    policy: Mapping[str, Any],
    previous: Mapping[str, Any],
    library_filter: str,
    *,
    collect_evidence: bool = False,
) -> dict[str, list[dict[str, Any]]]:
    """Refresh one library without walking the whole RAW tree when possible.

    Priority:
    1. library_map.yml exact root;
    2. previous catalog library_root;
    3. fallback to full discovery + filter.
    """
    ignore = set(str(x).lower() for x in policy.get("ignore_dirs", []))
    try:
        from lib_guard.discovery import LibraryRef, load_library_map

        refs = load_library_map(root, policy, policy.get("_policy_path"))
        for ref in refs:
            ref_type = ref.library_type or library_type
            if ref_type != library_type:
                continue
            if library_filter in _library_filter_names_for_ref(ref, library_type):
                return _discover_from_library_ref(ref, library_type, policy, ignore, collect_evidence=collect_evidence)
    except Exception:
        LibraryRef = None  # type: ignore[assignment]

    for lib in previous.get("libraries", []) or []:
        names = {str(lib.get("library_name") or ""), str(lib.get("library_id") or "")}
        names.update(str(a) for a in lib.get("aliases", []) or [] if str(a))
        if library_filter not in names:
            continue
        root_value = lib.get("library_root")
        if not root_value:
            continue
        lib_root = Path(str(root_value))
        if not lib_root.exists() or not lib_root.is_dir():
            continue
        try:
            from lib_guard.discovery import LibraryRef

            ref = LibraryRef(
                library_id=str(lib.get("library_name") or library_filter),
                root=lib_root,
                library_type=str(lib.get("library_type") or library_type),
                display_name=str(lib.get("display_name") or lib.get("library_name") or library_filter),
                vendor=str(lib.get("vendor")) if lib.get("vendor") else None,
                category=str(lib.get("category")) if lib.get("category") else None,
                aliases=tuple(str(a) for a in lib.get("aliases", []) or [] if str(a)),
                discovery_source="previous_catalog",
            )
            return _discover_from_library_ref(ref, library_type, policy, ignore, collect_evidence=collect_evidence)
        except Exception:
            break

    discovered = _discover(root, library_type, policy, collect_evidence=collect_evidence)
    return {
        name: items
        for name, items in discovered.items()
        if library_filter in {name, f"{library_type}/{name}"}
    }


def _manual_for(overrides: Mapping[str, Any], version_key: str) -> Mapping[str, Any]:
    item = overrides.get(version_key, {}) if isinstance(overrides, Mapping) else {}
    return item if isinstance(item, Mapping) else {}


def _runtime_for(runtime_state: Mapping[str, Any], version_key: str) -> Mapping[str, Any]:
    item = runtime_state.get(version_key, {}) if isinstance(runtime_state, Mapping) else {}
    return item if isinstance(item, Mapping) else {}


def _collect_runtime_state(data: Mapping[str, Any]) -> dict[str, Any]:
    runtime: dict[str, Any] = {}
    if isinstance(data.get("runtime_state"), Mapping):
        runtime.update({str(k): dict(v) for k, v in data.get("runtime_state", {}).items() if isinstance(v, Mapping)})
    overrides = data.get("manual_overrides", {}) if isinstance(data.get("manual_overrides"), Mapping) else {}
    for version_key, item in overrides.items():
        if not isinstance(item, Mapping):
            continue
        legacy = {k: item.get(k) for k in ["scan", "diff", "release"] if isinstance(item.get(k), Mapping)}
        if not legacy:
            continue
        current = dict(runtime.get(str(version_key), {}) or {})
        for key, value in legacy.items():
            current[key] = dict(current.get(key, {}) or {}) | dict(value or {})
        runtime[str(version_key)] = current
    return runtime


def _apply_overrides(version: dict[str, Any], overrides: Mapping[str, Any]) -> dict[str, Any]:
    item = dict(version)
    version_key = item["version_key"]
    manual = _manual_for(overrides, version_key)
    if not manual:
        return item
    for src, dst in [
        ("stage", "stage"),
        ("release_line", "release_line"),
        ("display_name", "display_name"),
        ("manual_review", "manual_review"),
        ("package_type", "package_type"),
        ("update_scope", "update_scope"),
        ("standalone", "standalone"),
        ("base_required", "base_required"),
        ("base_version", "base_version"),
        ("base_full_version", "base_full_version"),
        ("previous_effective_version", "previous_effective_version"),
        ("compare_default", "compare_default"),
        ("current_effective", "current_effective"),
    ]:
        if src in manual and manual[src] is not None:
            item[dst] = manual[src]
    if "update_scope" in item:
        item["update_scope"] = _coerce_list(item.get("update_scope"))
    if "base_version" in manual and "base_full_version" not in manual:
        item["base_full_version"] = manual.get("base_version")
    if "base_full_version" in manual and "base_version" not in manual:
        item["base_version"] = manual.get("base_full_version")
    if "parent_version" in manual and "previous_effective_version" not in manual:
        item["previous_effective_version"] = manual.get("parent_version")
    parent_value = manual.get("previous_effective_version") if "previous_effective_version" in manual else manual.get("parent_version")
    if parent_value is not None:
        item.setdefault("lineage", {})["parent_candidate"] = parent_value
        item.setdefault("lineage", {})["source"] = "manual"
    base_value = manual.get("base_full_version") if "base_full_version" in manual else manual.get("base_version")
    if base_value is not None:
        item.setdefault("lineage", {})["base_candidate"] = base_value
        item.setdefault("lineage", {})["source"] = "manual"
    notes = list(item.get("notes", []) or [])
    notes.extend(manual.get("notes", []) or [])
    item["notes"] = notes
    if item.get("stage") != "unknown" and manual.get("stage") is not None and "manual_review" not in manual:
        item["manual_review"] = False
    elif item.get("stage") != "unknown" and item.get("lineage", {}).get("source") == "manual":
        item["manual_review"] = bool(manual.get("manual_review", False))
    elif item.get("stage") != "unknown" and "manual_review" in manual:
        item["manual_review"] = bool(manual.get("manual_review"))
    return _sync_version_relation_fields(item)


def _apply_runtime(version: dict[str, Any], runtime_state: Mapping[str, Any]) -> dict[str, Any]:
    item = dict(version)
    runtime = _runtime_for(runtime_state, item["version_key"])
    for nested in ["scan", "diff", "release"]:
        if isinstance(runtime.get(nested), Mapping):
            item.setdefault(nested, {}).update(runtime[nested])
    return _sync_version_relation_fields(item)


def _library_match_names(lib: Mapping[str, Any]) -> set[str]:
    names = {str(lib.get("library_id") or ""), str(lib.get("library_name") or "")}
    names.update(str(a) for a in lib.get("aliases", []) or [] if str(a))
    return {name for name in names if name}


def _build_library(library_type: str, library_name: str, discovered: list[dict[str, Any]], overrides: Mapping[str, Any], runtime_state: Mapping[str, Any]) -> dict[str, Any]:
    versions: list[dict[str, Any]] = []
    ordered = sorted(discovered, key=lambda item: _version_sort_key(item["version_id"]))
    first = ordered[0] if ordered else {}
    library_root = first.get("library_root")
    display_name = first.get("display_name") or library_name
    vendor = first.get("vendor")
    category = first.get("category")
    middle_path = first.get("middle_path")
    aliases = sorted({str(a) for item in ordered for a in (item.get("aliases") or []) if str(a)})
    initial_versions = [v for v in ordered if v["stage"] == "initial"]
    base = None
    if len(ordered) > 1:
        base = ordered[0]["version_id"] if _item_looks_like_version(ordered[0]) else (initial_versions[0]["version_id"] if initial_versions else ordered[0]["version_id"])
    previous_by_stage: dict[str, str] = {}
    latest_known: str | None = None
    for item in ordered:
        stage = item["stage"]
        version_id = item["version_id"]
        version_key = f"{library_type}/{library_name}/{version_id}"
        parent = None
        if stage in {"stable", "final"}:
            parent = previous_by_stage.get(stage) or latest_known
        elif stage == "ad-hoc":
            parent = previous_by_stage.get("stable") or previous_by_stage.get("final")
        if parent is None and version_id != base and _item_looks_like_version(item):
            parent = latest_known
        lineage_source = "auto"
        manual_review = stage == "unknown" or (stage == "ad-hoc" and not parent)
        if stage == "ad-hoc" and parent:
            manual_review = True
        try:
            from lib_guard.package.classifier import classify_package

            package_info = classify_package(item["raw_path"], library_type=library_type)
        except Exception:
            package_info = {
                "package_type": "UNKNOWN_PACKAGE",
                "update_scope": [],
                "standalone": False,
                "base_required": True,
                "classification_confidence": 0.0,
                "classification_evidence": {},
                "classification_risks": ["classification_failed"],
            }
        package_type = str(package_info.get("package_type") or "UNKNOWN_PACKAGE")
        update_scope = _coerce_list(package_info.get("update_scope", []))
        standalone = bool(package_info.get("standalone")) or package_type == "FULL_PACKAGE"
        base_required = bool(package_info.get("base_required"))
        previous_effective_version = parent
        base_full_version = version_id if standalone else (base if version_id != base else None)
        if base_required and not standalone and not base_full_version:
            manual_review = True
        version = {
            "version_key": version_key,
            "version_id": version_id,
            "display_name": version_id,
            "stage": stage,
            "version_type": _version_type(stage),
            "release_line": "main",
            "raw_path": item["raw_path"],
            "library_root": item.get("library_root") or library_root,
            "version_path": item["raw_path"],
            "package_type": package_type,
            "update_scope": update_scope,
            "standalone": standalone,
            "base_required": base_required,
            "base_version": base_full_version,
            "base_full_version": base_full_version,
            "previous_effective_version": previous_effective_version,
            "compare_default": "previous_effective" if previous_effective_version else "none",
            "current_effective": False,
            "classification_confidence": package_info.get("classification_confidence"),
            "classification_evidence": package_info.get("classification_evidence", {}),
            "classification_risks": package_info.get("classification_risks", []),
            "detected": item["detected"],
            "lineage": {
                "parent_candidate": parent,
                "base_candidate": base_full_version,
                "previous_final_candidate": previous_by_stage.get("final"),
                "confidence": "HIGH" if item.get("detected", {}).get("confidence", 0) >= 0.7 else "LOW",
                "source": lineage_source,
            },
            "scan": {"status": "NOT_SCANNED", "scan_dir": None, "scan_id": None, "last_scan_at": None, "scan_html": None, "console_html": None},
            "diff": {
                "adjacent_status": "PENDING" if parent else "NOT_APPLICABLE",
                "adjacent_old_version": parent,
                "adjacent_diff_dir": None,
                "adjacent_diff_html": None,
                "cumulative_status": "PENDING" if base_full_version and base_full_version != version_id else "NOT_APPLICABLE",
                "cumulative_base_version": base_full_version if base_full_version and base_full_version != version_id else None,
                "cumulative_diff_dir": None,
                "cumulative_diff_html": None,
                "base_status": "PENDING" if manual_review and base_full_version and base_full_version != version_id else "NOT_APPLICABLE",
                "base_version": base_full_version if manual_review and base_full_version and base_full_version != version_id else None,
                "base_diff_dir": None,
                "base_diff_html": None,
            },
            "release": {"status": "UNKNOWN", "check_status": None, "check_json": None, "link_status": None, "link_json": None, "release_dir": None, "alias": None},
            "recommended_action": "manual_review" if manual_review else "scan_then_diff",
            "manual_review": manual_review,
            "notes": [],
        }
        version = _sync_version_relation_fields(version)
        version = _apply_overrides(version, overrides)
        version = _apply_runtime(version, runtime_state)
        versions.append(version)
        if version["stage"] != "unknown":
            previous_by_stage[version["stage"]] = version_id
            latest_known = version_id
        elif _item_looks_like_version(item):
            latest_known = version_id

    stage_counts = {stage: 0 for stage in STAGES}
    for version in versions:
        stage_counts[version.get("stage", "unknown")] = stage_counts.get(version.get("stage", "unknown"), 0) + 1
    return {
        "library_id": f"{library_type}/{library_name}",
        "library_type": library_type,
        "library_name": library_name,
        "display_name": display_name,
        "aliases": aliases,
        "vendor": vendor,
        "category": category,
        "middle_path": middle_path,
        "library_root": library_root,
        "raw_roots": sorted({v["raw_path"] for v in discovered}),
        "summary": {
            "version_count": len(versions),
            "latest_version": versions[-1]["version_id"] if versions else None,
            "stage_counts": stage_counts,
            "scan_pending": sum(1 for v in versions if v["scan"]["status"] == "NOT_SCANNED"),
            "diff_pending": sum(1 for v in versions if v["diff"]["adjacent_status"] == "PENDING"),
            "manual_review": sum(1 for v in versions if v.get("manual_review")),
        },
        "versions": versions,
    }


def _build_issues(catalog: Mapping[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    idx = 1
    for lib in catalog.get("libraries", []) or []:
        for version in lib.get("versions", []) or []:
            if version.get("stage") == "unknown":
                issues.append(
                    {
                        "issue_id": f"catalog_issue_{idx:04d}",
                        "severity": "warning",
                        "category": "stage_unknown",
                        "library_id": lib.get("library_id"),
                        "version_key": version.get("version_key"),
                        "message": "无法根据规则识别版本阶段",
                        "suggested_action": "manual_override_stage",
                        "suggested_command": f"python -m lib_guard.cli catalog override --version {version.get('version_key')} --stage stable",
                    }
                )
                idx += 1
            if version.get("manual_review"):
                issues.append(
                    {
                        "issue_id": f"catalog_issue_{idx:04d}",
                        "severity": "warning",
                        "category": "manual_review",
                        "library_id": lib.get("library_id"),
                        "version_key": version.get("version_key"),
                        "message": "该版本需要人工确认 parent/base 或阶段归属",
                        "suggested_action": "catalog_override",
                        "suggested_command": f"python -m lib_guard.cli catalog override --version {version.get('version_key')} --parent <parent_version> --base <base_version>",
                    }
                )
                idx += 1
    return issues


def _task_command(version: Mapping[str, Any], task_type: str) -> str:
    library_name = str(version.get("version_key", "")).split("/")[1] if "/" in str(version.get("version_key", "")) else str(version.get("version_key", ""))
    if task_type == "scan":
        return f'python -m lib_guard.cli run --catalog "$WORK/catalog/catalog.json" --library {library_name} --version {version.get("version_id")}'
    if task_type == "diff_adjacent":
        return f'python -m lib_guard.cli compare --catalog "$WORK/catalog/catalog.json" --library {library_name} --new {version.get("version_id")} --mode adjacent'
    return f'python -m lib_guard.cli catalog override --catalog "$WORK/catalog/catalog.json" --version {version.get("version_key")}'


def _build_tasks(catalog: Mapping[str, Any]) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    idx = 1
    for lib in catalog.get("libraries", []) or []:
        for version in lib.get("versions", []) or []:
            if version.get("manual_review"):
                tasks.append(
                    {
                        "task_id": f"task_manual_{idx:04d}",
                        "task_type": "manual_review",
                        "priority": "P0",
                        "library_id": lib.get("library_id"),
                        "version_key": version.get("version_key"),
                        "title": f"人工确认 {lib.get('library_name')} {version.get('version_id')}",
                        "reason": "系统无法可靠推导版本阶段或 parent/base",
                        "command": _task_command(version, "manual_review"),
                    }
                )
                idx += 1
                continue
            if version.get("scan", {}).get("status") == "NOT_SCANNED":
                tasks.append(
                    {
                        "task_id": f"task_scan_{idx:04d}",
                        "task_type": "scan",
                        "priority": "P1",
                        "library_id": lib.get("library_id"),
                        "version_key": version.get("version_key"),
                        "title": f"扫描 {lib.get('library_name')} {version.get('version_id')}",
                        "reason": "发现版本但尚未扫描",
                        "command": _task_command(version, "scan"),
                    }
                )
                idx += 1
            if version.get("diff", {}).get("adjacent_status") == "PENDING":
                tasks.append(
                    {
                        "task_id": f"task_diff_{idx:04d}",
                        "task_type": "diff_adjacent",
                        "priority": "P2",
                        "library_id": lib.get("library_id"),
                        "version_key": version.get("version_key"),
                        "title": f"相邻比较 {lib.get('library_name')} {version.get('version_id')}",
                        "reason": "该版本已有 parent 候选版本",
                        "command": _task_command(version, "diff_adjacent"),
                    }
                )
                idx += 1
    return tasks


def _summary(libraries: list[dict[str, Any]], tasks: list[dict[str, Any]]) -> dict[str, Any]:
    stage_counts = {stage: 0 for stage in STAGES}
    version_count = 0
    manual_review_count = 0
    scanned = 0
    diff_done = 0
    release_blocked = 0
    for lib in libraries:
        for version in lib.get("versions", []) or []:
            version_count += 1
            stage = version.get("stage", "unknown")
            stage_counts[stage] = stage_counts.get(stage, 0) + 1
            manual_review_count += 1 if version.get("manual_review") else 0
            scanned += 1 if version.get("scan", {}).get("status") != "NOT_SCANNED" else 0
            diff_done += 1 if version.get("diff", {}).get("adjacent_status") == "DIFF_DONE" else 0
            release_blocked += 1 if version.get("release", {}).get("check_status") in {"BLOCK", "FAILED"} else 0
    return {
        "library_count": len(libraries),
        "version_count": version_count,
        "stage_counts": stage_counts,
        "scan_status_counts": {"SCANNED": scanned, "NOT_SCANNED": version_count - scanned},
        "diff_status_counts": {
            "DIFF_DONE": diff_done,
            "DIFF_PENDING": sum(1 for t in tasks if t.get("task_type", "").startswith("diff")),
            "NOT_APPLICABLE": 0,
        },
        "manual_review_count": manual_review_count,
        "release_blocked_count": release_blocked,
        "recommended_scan_count": sum(1 for t in tasks if t.get("task_type") == "scan"),
        "recommended_diff_count": sum(1 for t in tasks if t.get("task_type", "").startswith("diff")),
    }


def _rebuild_catalog(data: dict[str, Any]) -> dict[str, Any]:
    overrides = data.get("manual_overrides", {}) if isinstance(data.get("manual_overrides"), Mapping) else {}
    runtime_state = _collect_runtime_state(data)
    discovered = data.get("_discovered", {}) if isinstance(data.get("_discovered"), Mapping) else {}
    libraries = [
        _build_library(lib_type, lib_name, list(items), overrides, runtime_state)
        for key, items in sorted(discovered.items())
        for lib_type, lib_name in [key.split("/", 1)]
    ]
    shell = {
        "schema_version": "1.0",
        "catalog_id": data.get("catalog_id") or f"catalog_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "generated_at": data.get("generated_at") or _now(),
        "root": data.get("root"),
        "policy_path": data.get("policy_path"),
        "libraries": libraries,
        "manual_overrides": overrides,
        "runtime_state": runtime_state,
        "_discovered": discovered,
    }
    shell["issues"] = _build_issues(shell)
    shell["recommended_tasks"] = _build_tasks(shell)
    shell["summary"] = _summary(libraries, shell["recommended_tasks"])
    return shell


def _path_mtime(path: str | Path | None) -> float | None:
    if not path:
        return None
    try:
        return Path(path).stat().st_mtime
    except OSError:
        return None


def _catalog_library_state(catalog: Mapping[str, Any]) -> dict[str, Any]:
    libraries: dict[str, Any] = {}
    for lib in catalog.get("libraries", []) or []:
        name = str(lib.get("library_name") or lib.get("library_id") or "")
        if not name:
            continue
        root = lib.get("library_root")
        if not root:
            versions = lib.get("versions", []) or []
            if versions:
                raw_path = versions[0].get("raw_path")
                root = str(Path(str(raw_path)).parent) if raw_path else None
        libraries[name] = {
            "root": str(root) if root else None,
            "last_seen": _now(),
            "root_mtime": _path_mtime(root),
            "version_count": len(lib.get("versions", []) or []),
        }
    return libraries


def _build_catalog_state(root: Path, policy_hash: str | None, catalog: Mapping[str, Any], *, collect_evidence: bool = False) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "raw_root": str(root),
        "library_map_hash": policy_hash,
        "evidence_mode": "sampled" if collect_evidence else "fast",
        "generated_at": _now(),
        "libraries": _catalog_library_state(catalog),
    }


def _catalog_state_unchanged(state: Mapping[str, Any], root: Path, policy_hash: str | None, *, collect_evidence: bool = False) -> bool:
    if str(state.get("raw_root") or "") != str(root):
        return False
    if state.get("library_map_hash") != policy_hash:
        return False
    expected_mode = "sampled" if collect_evidence else "fast"
    if state.get("evidence_mode", "sampled") != expected_mode:
        return False
    libraries = state.get("libraries") or {}
    if not libraries:
        return False
    for item in libraries.values():
        if not isinstance(item, Mapping):
            return False
        if _path_mtime(item.get("root")) != item.get("root_mtime"):
            return False
    return True


def scan_catalog(
    root: str | Path,
    *,
    out_dir: str | Path,
    library_type: str = "ip",
    policy_path: str | Path | None = None,
    library: str | None = None,
    force: bool = False,
    collect_evidence: bool = False,
) -> dict[str, Any]:
    root_path = Path(root)
    out = Path(out_dir)
    previous = _read_json(out / "catalog.json", {}) or {}
    state_path = out / "catalog_state.json"
    previous_state = _read_json(state_path, {}) or {}
    policy_hash = _sha256_file(policy_path)
    if not force and not library and isinstance(previous, Mapping) and previous.get("libraries") and isinstance(previous_state, Mapping):
        if _catalog_state_unchanged(previous_state, root_path, policy_hash, collect_evidence=collect_evidence):
            catalog = dict(previous)
            catalog["incremental_refresh"] = {
                "mode": "skipped",
                "reason": "raw_root_policy_and_library_roots_unchanged",
                "state_path": str(state_path),
            }
            return {"status": "PASS", "catalog_path": str(out / "catalog.json"), "state_path": str(state_path), "skipped": True, "evidence_mode": "sampled" if collect_evidence else "fast", "catalog": catalog}
    overrides = previous.get("manual_overrides", {}) if isinstance(previous, Mapping) else {}
    runtime_state = _collect_runtime_state(previous) if isinstance(previous, Mapping) else {}
    policy = _load_policy(policy_path)
    resolved_library_type = str(policy.get("library_type") or library_type or "ip")
    library_filter = str(library or "").strip()
    if library_filter:
        discovered_by_name = _discover_single_library(
            root_path,
            resolved_library_type,
            policy,
            previous if isinstance(previous, Mapping) else {},
            library_filter,
            collect_evidence=collect_evidence,
        )
    else:
        discovered_by_name = _discover(root_path, resolved_library_type, policy, collect_evidence=collect_evidence)
    discovered = {f"{resolved_library_type}/{name}": items for name, items in discovered_by_name.items()}
    catalog = _rebuild_catalog(
        {
            "catalog_id": f"catalog_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            "generated_at": _now(),
            "root": str(root_path),
            "policy_path": str(policy_path) if policy_path else None,
            "manual_overrides": overrides,
            "runtime_state": runtime_state,
            "_discovered": discovered,
        }
    )
    if library_filter and isinstance(previous, Mapping):
        refreshed_names = {str(lib.get("library_name")) for lib in catalog.get("libraries", []) or []}
        refreshed_ids = {str(lib.get("library_id")) for lib in catalog.get("libraries", []) or []}
        merged_libraries = [
            lib
            for lib in previous.get("libraries", []) or []
            if library_filter not in {str(lib.get("library_name")), str(lib.get("library_id"))}
            and str(lib.get("library_name")) not in refreshed_names
            and str(lib.get("library_id")) not in refreshed_ids
        ]
        merged_libraries.extend(catalog.get("libraries", []) or [])
        merged_libraries = sorted(merged_libraries, key=lambda lib: str(lib.get("library_id") or lib.get("library_name") or ""))
        catalog["libraries"] = merged_libraries
        catalog["issues"] = _build_issues(catalog)
        catalog["recommended_tasks"] = _build_tasks(catalog)
        catalog["summary"] = _summary(merged_libraries, catalog["recommended_tasks"])
        catalog["partial_refresh"] = {"library": library_filter, "refreshed_library_count": len(refreshed_names)}
    _write_json(out / "catalog.json", catalog)
    state = _build_catalog_state(root_path, policy_hash, catalog, collect_evidence=collect_evidence)
    _write_json(state_path, state)
    for lib in catalog["libraries"]:
        _write_json(out / "libraries" / f"{lib['library_name']}.json", lib)
    _write_json(out / "reports" / "catalog_summary.json", catalog["summary"])
    _write_json(out / "reports" / "scan_candidates.json", [t for t in catalog["recommended_tasks"] if t["task_type"] == "scan"])
    _write_json(out / "reports" / "diff_candidates.json", [t for t in catalog["recommended_tasks"] if t["task_type"].startswith("diff")])
    return {"status": "PASS", "catalog_path": str(out / "catalog.json"), "state_path": str(state_path), "evidence_mode": "sampled" if collect_evidence else "fast", "catalog": catalog}


def apply_catalog_override(
    catalog_path: str | Path,
    *,
    version_key: str,
    stage: str | None = None,
    parent_version: str | None = None,
    base_version: str | None = None,
    release_line: str | None = None,
    display_name: str | None = None,
    manual_review: bool | None = None,
    package_type: str | None = None,
    update_scope: str | list[str] | tuple[str, ...] | None = None,
    standalone: bool | None = None,
    base_required: bool | None = None,
    base_full_version: str | None = None,
    previous_effective_version: str | None = None,
    compare_default: str | None = None,
    current_effective: bool | None = None,
    note: str | None = None,
    updated_by: str | None = None,
) -> dict[str, Any]:
    path = Path(catalog_path)
    data = _read_json(path, {}) or {}
    overrides = data.setdefault("manual_overrides", {})
    item = dict(overrides.get(version_key, {}) or {})
    for key, value in [
        ("stage", stage),
        ("parent_version", parent_version),
        ("base_version", base_version),
        ("release_line", release_line),
        ("display_name", display_name),
        ("package_type", package_type),
        ("base_full_version", base_full_version),
        ("previous_effective_version", previous_effective_version),
        ("compare_default", compare_default),
    ]:
        if value is not None:
            item[key] = value
    if update_scope is not None:
        item["update_scope"] = _coerce_list(update_scope)
    for key, value in [("standalone", standalone), ("base_required", base_required), ("current_effective", current_effective)]:
        if value is not None:
            item[key] = bool(value)
    if manual_review is not None:
        item["manual_review"] = manual_review
    if note:
        notes = list(item.get("notes", []) or [])
        notes.append(note)
        item["notes"] = notes
    item["updated_by"] = updated_by or "manual"
    item["updated_at"] = _now()
    overrides[version_key] = item
    catalog = _rebuild_catalog(data)
    _write_json(path, catalog)
    return {"status": "PASS", "catalog_path": str(path), "catalog": catalog, "override": item}


def _library_match_score(lib: Mapping[str, Any], query: str) -> int:
    exact = {str(lib.get("library_id") or ""), str(lib.get("library_name") or "")}
    aliases = {str(a) for a in lib.get("aliases", []) or [] if str(a)}
    if query in exact:
        return 100
    if query in aliases:
        return 10
    return 0


def _select_catalog_library(catalog: Mapping[str, Any], library: str) -> Mapping[str, Any]:
    scored = []
    for lib in catalog.get("libraries", []) or []:
        score = _library_match_score(lib, library)
        if score:
            scored.append((score, lib))
    if not scored:
        raise ValueError(f"library not found in catalog: {library!r}")
    best = max(score for score, _ in scored)
    matches = [lib for score, lib in scored if score == best]
    if len(matches) > 1:
        choices = ", ".join(str(lib.get("library_name") or lib.get("library_id")) for lib in matches)
        raise ValueError(f"ambiguous library name or alias {library!r}; use full library_id. Matched: {choices}")
    return matches[0]


def find_catalog_version(catalog_path: str | Path, library: str, version: str) -> dict[str, Any]:
    """Return one catalog version enriched with library identity fields."""
    catalog = _read_json(catalog_path, {}) or {}
    lib = _select_catalog_library(catalog, library)
    for item in lib.get("versions", []) or []:
        if version not in {item.get("version_id"), item.get("version_key")}:
            continue
        out = dict(item)
        out["library_id"] = lib.get("library_id")
        out["library_type"] = lib.get("library_type")
        out["library_name"] = lib.get("library_name")
        out["library_display_name"] = lib.get("display_name")
        out["aliases"] = list(lib.get("aliases", []) or [])
        out["vendor"] = lib.get("vendor")
        out["category"] = lib.get("category")
        out["middle_path"] = lib.get("middle_path")
        out["library_root"] = out.get("library_root") or lib.get("library_root")
        return out
    raise ValueError(f"catalog version not found: library={library!r}, version={version!r}")


def resolve_catalog_pair(catalog_path: str | Path, library: str, new: str, *, mode: str = "adjacent", base: str | None = None) -> dict[str, Any]:
    """Resolve old/new scan directories for a catalog-driven diff."""
    new_item = find_catalog_version(catalog_path, library, new)
    diff = new_item.get("diff", {}) or {}
    if base:
        old_version = base
        relation_mode = "base"
        base_source = "manual"
    elif mode == "cumulative":
        old_version = diff.get("cumulative_base_version")
        relation_mode = "cumulative"
        base_source = "catalog.cumulative_base_version"
    else:
        old_version = diff.get("adjacent_old_version")
        relation_mode = "adjacent"
        base_source = "catalog.adjacent_old_version"
    if not old_version:
        raise ValueError(f"catalog version {new_item.get('version_key')} has no {mode} comparison target")
    old_item = find_catalog_version(catalog_path, library, str(old_version))
    old_scan = (old_item.get("scan", {}) or {}).get("scan_dir")
    new_scan = (new_item.get("scan", {}) or {}).get("scan_dir")
    if not old_scan:
        raise ValueError(f"catalog version {old_item.get('version_key')} has no scan_dir")
    if not new_scan:
        raise ValueError(f"catalog version {new_item.get('version_key')} has no scan_dir")
    return {
        "mode": mode,
        "old": old_item,
        "new": new_item,
        "old_scan": old_scan,
        "new_scan": new_scan,
        "version_relation": {
            "mode": relation_mode,
            "requested_mode": mode,
            "library_id": new_item.get("library_id"),
            "library_name": new_item.get("library_name"),
            "old_version": old_item.get("version_id"),
            "new_version": new_item.get("version_id"),
            "old_version_key": old_item.get("version_key"),
            "new_version_key": new_item.get("version_key"),
            "base_version": old_item.get("version_id"),
            "base_version_source": base_source,
            "compare_policy": relation_mode,
            "release_line": new_item.get("release_line") or old_item.get("release_line"),
        },
    }


def update_catalog_scan_status(
    catalog_path: str | Path,
    *,
    version_key: str,
    scan_dir: str | Path,
    scan_id: str | None,
    status: str,
    scan_html: str | Path | None = None,
    console_html: str | Path | None = None,
) -> dict[str, Any]:
    path = Path(catalog_path)
    data = _read_json(path, {}) or {}
    runtime = data.setdefault("runtime_state", {})
    item = dict(runtime.get(version_key, {}) or {})
    item["scan"] = {
        "status": "SCANNED" if status not in {"FAILED", "BLOCK"} else status,
        "scan_dir": str(scan_dir),
        "scan_id": scan_id,
        "last_scan_at": _now(),
        "scan_html": str(scan_html) if scan_html else None,
        "console_html": str(console_html) if console_html else None,
    }
    item["updated_by"] = "lib_guard.run"
    item["updated_at"] = _now()
    runtime[version_key] = item
    catalog = _rebuild_catalog(data)
    _write_json(path, catalog)
    return {"status": "PASS", "catalog_path": str(path), "catalog": catalog}


def update_catalog_diff_status(
    catalog_path: str | Path,
    *,
    version_key: str,
    mode: str,
    old_version: str | None,
    diff_dir: str | Path,
    status: str,
    diff_html: str | Path | None = None,
) -> dict[str, Any]:
    path = Path(catalog_path)
    data = _read_json(path, {}) or {}
    runtime = data.setdefault("runtime_state", {})
    item = dict(runtime.get(version_key, {}) or {})
    diff = dict(item.get("diff", {}) or {})
    if mode == "cumulative":
        diff.update({"cumulative_status": "DIFF_DONE", "cumulative_base_version": old_version, "cumulative_diff_dir": str(diff_dir), "cumulative_diff_html": str(diff_html) if diff_html else None})
    elif mode == "base":
        diff.update({"base_status": "DIFF_DONE", "base_version": old_version, "base_diff_dir": str(diff_dir), "base_diff_html": str(diff_html) if diff_html else None})
    else:
        diff.update({"adjacent_status": "DIFF_DONE", "adjacent_old_version": old_version, "adjacent_diff_dir": str(diff_dir), "adjacent_diff_html": str(diff_html) if diff_html else None})
    item["diff"] = diff
    item["updated_by"] = "lib_guard.compare"
    item["updated_at"] = _now()
    runtime[version_key] = item
    catalog = _rebuild_catalog(data)
    _write_json(path, catalog)
    return {"status": "PASS", "catalog_path": str(path), "catalog": catalog}


def update_catalog_release_status(
    catalog_path: str | Path,
    *,
    version_key: str,
    action: str,
    status: str,
    result_path: str | Path | None = None,
    release_dir: str | Path | None = None,
    alias: str | None = None,
    manifest_path: str | Path | None = None,
    postcheck_path: str | Path | None = None,
    html_path: str | Path | None = None,
) -> dict[str, Any]:
    path = Path(catalog_path)
    data = _read_json(path, {}) or {}
    runtime = data.setdefault("runtime_state", {})
    item = dict(runtime.get(version_key, {}) or {})
    release = dict(item.get("release", {}) or {})
    if action == "link":
        release.update(
            {
                "status": status,
                "link_status": status,
                "link_json": str(result_path) if result_path else None,
                "release_dir": str(release_dir) if release_dir else release.get("release_dir"),
                "alias": alias if alias is not None else release.get("alias"),
                "manifest_json": str(manifest_path) if manifest_path else release.get("manifest_json"),
                "postcheck_json": str(postcheck_path) if postcheck_path else release.get("postcheck_json"),
                "release_html": str(html_path) if html_path else release.get("release_html"),
                "last_link_at": _now(),
            }
        )
    elif action == "verify":
        release.update(
            {
                "status": status,
                "verify_status": status,
                "postcheck_json": str(result_path) if result_path else str(postcheck_path) if postcheck_path else release.get("postcheck_json"),
                "release_dir": str(release_dir) if release_dir else release.get("release_dir"),
                "alias": alias if alias is not None else release.get("alias"),
                "manifest_json": str(manifest_path) if manifest_path else release.get("manifest_json"),
                "release_html": str(html_path) if html_path else release.get("release_html"),
                "last_verify_at": _now(),
            }
        )
    else:
        release.update(
            {
                "status": status,
                "check_status": status,
                "check_json": str(result_path) if result_path else None,
                "manifest_json": str(manifest_path) if manifest_path else release.get("manifest_json"),
                "last_check_at": _now(),
            }
        )
    item["release"] = release
    item["updated_by"] = f"lib_guard.release.{action}"
    item["updated_at"] = _now()
    runtime[version_key] = item
    catalog = _rebuild_catalog(data)
    _write_json(path, catalog)
    return {"status": "PASS", "catalog_path": str(path), "catalog": catalog}

def render_catalog_html(
    catalog_path: str | Path,
    out_dir: str | Path,
    *,
    render_library_pages: bool = True,
    max_attention_items: int = 10,
    max_report_rows: int = 16,
) -> dict[str, Any]:
    """Render Catalog HTML through the UI-layer renderer."""
    from lib_guard.render.catalog_report import render_catalog_html as _render_catalog_html

    return _render_catalog_html(
        catalog_path,
        out_dir,
        render_library_pages=render_library_pages,
        max_attention_items=max_attention_items,
        max_report_rows=max_report_rows,
    )
