from __future__ import annotations

from argparse import ArgumentParser, Namespace, RawDescriptionHelpFormatter, SUPPRESS
from pathlib import Path
from typing import Any
import json
import os
import shlex
import sys

from lib_guard.project_config import (
    BINARY_METADATA_ONLY_TYPES,
    CATALOG_POLICY_FILE,
    CONFIG_NAME,
    DEFAULT_LIBRARY_TYPE,
    DEFAULT_FILE_DIFF_TYPES,
    DEFAULT_PARSE_JOBS,
    DEFAULT_SCAN_MODE,
    PROJECT_CONFIG_DIR,
    RELEASE_POLICY_FILE,
    SCAN_STRATEGY_CONFIG_KEYS,
    SUMMARY_ONLY_TYPES,
    project_policy_path,
    workspace_config_file_defaults,
    workspace_defaults,
)

PAIRWISE_FILE_DIFF_TYPES = set(DEFAULT_FILE_DIFF_TYPES)
FORCE_LARGE_FILE_DIFF_TYPES = set(SUMMARY_ONLY_TYPES) | set(BINARY_METADATA_ONLY_TYPES)
MANUAL_FILE_DIFF_TYPES = PAIRWISE_FILE_DIFF_TYPES | FORCE_LARGE_FILE_DIFF_TYPES
SHORT_COMMAND_ALIASES: dict[str, str] = {}
LEGACY_SHORT_COMMAND_REWRITES = {
    "catalog": ["cat"],
    "diff": ["cmp"],
    "file-diff": ["fd"],
    "release": ["rel"],
    "refresh": ["cat", "--update-detail"],
    "override": ["library", "override"],
    "rv-build": ["rv", "build"],
    "rv-check": ["rv", "check"],
    "rv-list": ["rv", "list"],
    "rv-accept": ["rv", "accept"],
    "rv-waive": ["rv", "waive"],
}


def _norm(path: str | Path) -> str:
    return str(Path(path))


def write_default_config(
    workspace: str | Path,
    *,
    raw_root: str | Path | None = None,
    library_type: str = DEFAULT_LIBRARY_TYPE,
) -> Path:
    root = Path(workspace)
    root.mkdir(parents=True, exist_ok=True)
    cfg = workspace_defaults(root, raw_root=raw_root, library_type=library_type)
    ordered_keys = [
        "workspace",
        "raw_root",
        "catalog",
        "catalog_html",
        "reports",
        "diff",
        "file_diff",
        "release_root",
        "versions",
        "actions_dir",
        "library_type",
        "mode",
        "parse_jobs",
    ]
    lines = [
        "# lib_guard short command workspace",
        *[f"{key}: {cfg[key]}" for key in ordered_keys],
    ]
    path = root / CONFIG_NAME
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _parse_config(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        data[key.strip()] = value.strip().strip("\"'")
    return data


def _find_config(cwd: str | Path, explicit: str | Path | None = None) -> Path:
    configured = explicit or os.environ.get("LIB_GUARD_CONFIG")
    if configured:
        path = Path(configured)
        if not path.exists():
            raise FileNotFoundError(f"config not found: {path}")
        return path
    current = Path(cwd).resolve()
    for item in [current, *current.parents]:
        candidate = item / CONFIG_NAME
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"{CONFIG_NAME} not found. Run init once or set LIB_GUARD_CONFIG to the config path.")


def _load_config(cwd: str | Path, explicit: str | Path | None = None) -> dict[str, str]:
    path = _find_config(cwd, explicit)
    cfg = _parse_config(path)
    project_root = os.environ.get("LIB_GUARD_PROJECT_ROOT") or Path(__file__).resolve().parents[2]
    default_catalog_policy = project_policy_path(project_root, CATALOG_POLICY_FILE)
    default_release_policy = project_policy_path(project_root, RELEASE_POLICY_FILE)
    workspace_root = Path(cfg.get("workspace") or path.parent)
    defaults = workspace_defaults(workspace_root, library_type=cfg.get("library_type", DEFAULT_LIBRARY_TYPE))
    derived_config_keys = {"config_dir", "library_list", "library_registry", "library_candidates", "library_catalog", "library_versions", "versions"}
    for key, value in defaults.items():
        if key in derived_config_keys:
            continue
        cfg.setdefault(key, value)
    config_defaults = workspace_config_file_defaults(workspace_root, cfg.get("config_dir") or defaults["config_dir"])
    for key, value in config_defaults.items():
        cfg.setdefault(key, value)
    if cfg.get("versions"):
        cfg.setdefault("library_versions", cfg["versions"])
    else:
        cfg.setdefault("library_versions", config_defaults["library_versions"])
    cfg.setdefault("versions", cfg["library_versions"])
    if "catalog_policy" not in cfg:
        library_catalog = Path(cfg["library_catalog"])
        if library_catalog.exists():
            cfg["catalog_policy"] = str(library_catalog)
        elif default_catalog_policy and default_catalog_policy.exists():
            cfg["catalog_policy"] = str(default_catalog_policy)
    if "release_policy" not in cfg and default_release_policy and default_release_policy.exists():
        cfg["release_policy"] = str(default_release_policy)
    cfg.setdefault("mode", DEFAULT_SCAN_MODE)
    cfg.setdefault("parse_jobs", DEFAULT_PARSE_JOBS)
    return cfg


def _safe_path_name(value: str) -> str:
    text = str(value or "").strip().replace("\\", "/")
    return "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in text).strip("_") or "item"


def _read_tsv(path: str | Path) -> list[dict[str, str]]:
    p = Path(path)
    if not p.exists():
        return []
    lines = [line for line in p.read_text(encoding="utf-8").splitlines() if line.strip() and not line.lstrip().startswith("#")]
    if not lines:
        return []
    header = [item.strip() for item in lines[0].split("\t")]
    rows: list[dict[str, str]] = []
    for line in lines[1:]:
        values = line.split("\t")
        row = {key: values[idx].strip() if idx < len(values) else "" for idx, key in enumerate(header)}
        rows.append(row)
    return rows


def _version_ref_map(cfg: dict[str, str], library: str) -> dict[str, str]:
    refs: dict[str, str] = {}
    paths = [
        cfg.get("library_versions") or "",
        cfg.get("versions") or "",
        str(Path(cfg["workspace"]) / PROJECT_CONFIG_DIR / "library_versions.tsv"),
        str(Path(cfg["workspace"]) / "config" / "library_versions.tsv"),
    ]
    seen_paths: set[str] = set()
    rows: list[dict[str, str]] = []
    for path in paths:
        if not path or path in seen_paths:
            continue
        seen_paths.add(path)
        rows.extend(_read_tsv(path))
    for row in rows:
        if row.get("library_id") not in {library, f"{cfg.get('library_type', 'ip')}/{library}"}:
            continue
        version_id = row.get("version_id") or row.get("version")
        if not version_id:
            continue
        refs[version_id] = version_id
        if row.get("version_ref"):
            refs[row["version_ref"]] = version_id
    return refs


def _review_action_path(cfg: dict[str, str], library: str) -> Path:
    actions_dir = Path(cfg.get("actions_dir") or Path(cfg["workspace"]) / "actions")
    candidates = [
        actions_dir / f"{library}.action",
        actions_dir / f"{_safe_path_name(library)}.action",
        Path(cfg["workspace"]) / PROJECT_CONFIG_DIR / "actions" / f"{library}.action",
        Path(cfg["workspace"]) / PROJECT_CONFIG_DIR / "actions" / f"{_safe_path_name(library)}.action",
        Path(cfg["workspace"]) / "work" / "actions" / f"{library}.action",
        Path(cfg["workspace"]) / "work" / "actions" / f"{_safe_path_name(library)}.action",
        actions_dir / f"{library}.review",
        actions_dir / f"{_safe_path_name(library)}.review",
        Path(cfg["workspace"]) / PROJECT_CONFIG_DIR / "actions" / f"{library}.review",
        Path(cfg["workspace"]) / PROJECT_CONFIG_DIR / "actions" / f"{_safe_path_name(library)}.review",
        Path(cfg["workspace"]) / "work" / "actions" / f"{library}.review",
        Path(cfg["workspace"]) / "work" / "actions" / f"{_safe_path_name(library)}.review",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"action file not found for {library}: {candidates[0]}")


def _parse_review_actions(path: Path) -> dict[str, Any]:
    actions: dict[str, Any] = {
        "redo_all": False,
        "effects": [],
        "scans": [],
        "diffs": [],
        "releases": [],
        "action_plan": {"force_all_redo": False, "source": "", "warning": ""},
    }
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        verb = parts[0]
        args = parts[1:]
        if verb == "@ALL":
            if args == ["redo"]:
                actions["redo_all"] = True
                actions["action_plan"] = {
                    "force_all_redo": True,
                    "source": "@ALL redo",
                    "warning": "All existing outputs may be regenerated.",
                }
                continue
            raise ValueError(f"{path}:{lineno}: @ALL only supports 'redo'")
        if verb == "@effect":
            if len(args) < 2:
                raise ValueError(f"{path}:{lineno}: @effect requires a name and at least one raw version")
            actions["effects"].append({"name": args[0], "versions": args[1:], "force": False})
            continue
        if verb in {"@scan", "@rescan"}:
            if not args:
                raise ValueError(f"{path}:{lineno}: {verb} requires auto or raw versions")
            actions["scans"].append({"versions": args, "force": verb == "@rescan"})
            continue
        if verb in {"@diff", "@rediff"}:
            if len(args) != 3:
                raise ValueError(f"{path}:{lineno}: {verb} requires OLD NEW NAME")
            actions["diffs"].append({"old": args[0], "new": args[1], "name": args[2], "force": verb == "@rediff"})
            continue
        if verb in {"@release", "@rerelease", "@preview", "@repreview"}:
            if len(args) != 1:
                raise ValueError(f"{path}:{lineno}: {verb} requires one target")
            actions["releases"].append({"target": args[0], "force": verb in {"@rerelease", "@repreview"}})
            continue
        raise ValueError(f"{path}:{lineno}: unsupported action {verb}")
    return actions


def _catalog_data(cfg: dict[str, str]) -> dict[str, Any]:
    path = Path(cfg["catalog"])
    if not path.exists():
        raise FileNotFoundError(f"catalog not found: {path}. Run: scripts/lg.ps1 scan")
    return json.loads(path.read_text(encoding="utf-8"))


def _library_match_score(item: dict[str, Any], library: str) -> int:
    exact = {
        str(item.get("formal_library_id") or ""),
        str(item.get("typed_library_id") or ""),
        str(item.get("library_id") or ""),
        str(item.get("library_name") or ""),
    }
    aliases = {str(a) for a in item.get("aliases", []) or [] if str(a)}
    if library in exact:
        return 100
    if library in aliases:
        return 10
    return 0


def _find_library(catalog: dict[str, Any], library: str) -> dict[str, Any]:
    scored = []
    for item in catalog.get("libraries", []) or []:
        score = _library_match_score(item, library)
        if score:
            scored.append((score, item))
    if not scored:
        raise ValueError(f"library not found in catalog: {library}")
    best = max(score for score, _ in scored)
    matches = [item for score, item in scored if score == best]
    if len(matches) > 1:
        choices = ", ".join(str(item.get("library_name") or item.get("library_id")) for item in matches)
        raise ValueError(f"ambiguous library alias {library!r}; use formal library name. Matched: {choices}")
    return matches[0]


def _find_version(library: dict[str, Any], version: str) -> dict[str, Any]:
    for item in library.get("versions", []) or []:
        if item.get("version_id") == version:
            return item
    raise ValueError(f"version not found in catalog: {version}")


def _latest_refresh_version(library: dict[str, Any]) -> dict[str, Any] | None:
    versions = [item for item in library.get("versions", []) or [] if isinstance(item, dict)]
    if not versions:
        return None
    by_id = {str(item.get("version_id") or ""): item for item in versions}
    summary = library.get("summary", {}) or {}
    for key in ["latest_version", "latest_delivery_version"]:
        value = _version_ref(summary.get(key))
        if value and value in by_id:
            return by_id[value]
    for key in ["latest_version", "latest_delivery_version"]:
        value = _version_ref(library.get(key))
        if value and value in by_id:
            return by_id[value]
    return versions[-1]


def _version_ref(value: Any, target_version: str = "") -> str | None:
    if not value or isinstance(value, bool):
        return None
    text = str(value)
    if text.startswith("raw:") or text.startswith("effective:"):
        text = text.split(":", 1)[1]
    if target_version and text == target_version:
        return None
    return text


def _library_summary_ref(library: dict[str, Any], target_version: str, keys: list[str]) -> str | None:
    summary = library.get("summary", {}) or {}
    for key in keys:
        value = _version_ref(summary.get(key), target_version)
        if value:
            return value
    for key in keys:
        value = _version_ref(library.get(key), target_version)
        if value:
            return value
    return None


def _manual_lineage_parent(version: dict[str, Any]) -> str | None:
    lineage = version.get("lineage", {}) or {}
    if str(lineage.get("source") or "").lower() == "manual":
        return _version_ref(lineage.get("parent_candidate"), str(version.get("version_id") or ""))
    return None


def _refresh_base_version(library: dict[str, Any], version: dict[str, Any], mode: str) -> str | None:
    base, _source = _refresh_base_version_with_source(library, version, mode)
    return base


def _refresh_base_version_with_source(library: dict[str, Any], version: dict[str, Any], mode: str) -> tuple[str | None, str | None]:
    target = str(version.get("version_id") or "")
    lineage = version.get("lineage", {}) or {}
    diff = version.get("diff", {}) or {}
    if mode == "adjacent":
        return _version_ref(diff.get("adjacent_old_version"), target), "adjacent"
    if mode == "cumulative":
        return _version_ref(diff.get("cumulative_base_version") or version.get("base_full_version") or version.get("base_version") or lineage.get("base_candidate"), target), "cumulative"
    if mode == "current_effective":
        current = (
            _version_ref(version.get("current_effective_ref"), target)
            or _version_ref(version.get("latest_effective_ref"), target)
            or _library_summary_ref(library, target, ["current_effective", "current_effective_ref", "latest_effective_ref", "current_version"])
        )
        if current:
            return current, "current_effective"
        return _version_ref(version.get("previous_effective_version") or version.get("parent_version"), target) or _manual_lineage_parent(version), "previous_effective"
    previous = (
        _version_ref(version.get("previous_effective_version") or version.get("parent_version"), target)
        or _manual_lineage_parent(version)
    )
    if previous:
        return previous, "previous_effective"
    if mode == "previous_effective":
        return None, None
    current = (
        _version_ref(version.get("current_effective_ref"), target)
        or _version_ref(version.get("latest_effective_ref"), target)
        or _library_summary_ref(library, target, ["current_effective", "current_effective_ref", "latest_effective_ref", "current_version"])
    )
    if current:
        return current, "current_effective"
    return None, None


def _library_cli_name(library: dict[str, Any]) -> str:
    return str(library.get("formal_library_id") or library.get("library_name") or library.get("library_id") or "")


def _refresh_compare_command(
    cfg: dict[str, str],
    library: str,
    version: str,
    *,
    mode: str | None = None,
    base: str | None = None,
    base_source: str | None = None,
    rescan: bool = False,
) -> list[str]:
    command = [
        "compare",
        "--catalog",
        cfg["catalog"],
        "--library",
        library,
        "--new",
        version,
        "--workdir",
        cfg["workspace"],
        "--catalog-html-out",
        cfg["catalog_html"],
    ]
    if mode:
        command.extend(["--mode", mode])
    if base:
        command.extend(["--base", base])
    if base_source:
        command.extend(["--base-source", base_source])
    command.append("--rescan" if rescan else "--scan-if-missing")
    _append_scan_strategy(command, cfg)
    return command


def _refresh_commands(cfg: dict[str, str], args: Any) -> list[list[str]]:
    if bool(getattr(args, "all", False)) == bool(getattr(args, "library", None)):
        raise ValueError("refresh requires exactly one of: <library> or --all")
    commands: list[list[str]] = []
    if getattr(args, "refresh_catalog", False):
        commands.append(
            _catalog_scan_command(
                cfg,
                None if getattr(args, "all", False) else args.library,
                with_evidence=bool(getattr(args, "with_evidence", False)),
            )
        )
    data = _catalog_data(cfg)
    libraries = data.get("libraries", []) or []
    if getattr(args, "all", False):
        selected = [item for item in libraries if isinstance(item, dict)]
    else:
        selected = [_find_library(data, args.library)]
    for lib in selected:
        version = _latest_refresh_version(lib)
        if not version:
            continue
        library_name = _library_cli_name(lib)
        version_id = str(version.get("version_id") or "")
        if not library_name or not version_id:
            continue
        mode = getattr(args, "mode", "current_effective")
        base = None
        base_source = None
        if mode in {"previous_effective", "current_effective"}:
            base, base_source = _refresh_base_version_with_source(lib, version, mode)
            if not base:
                raise ValueError(f"refresh cannot resolve {mode} base for {library_name}/{version_id}; set previous_effective/current_effective or run cmp --base explicitly")
        commands.append(
            _refresh_compare_command(
                cfg,
                library_name,
                version_id,
                mode=mode if mode in {"adjacent", "cumulative"} else None,
                base=base,
                base_source=base_source,
                rescan=bool(getattr(args, "rescan", False)),
            )
        )
    if not commands:
        raise ValueError("refresh found no catalog versions to compare")
    return commands


def _resolve_old_version(library: dict[str, Any], version: dict[str, Any], explicit_base: str | None) -> dict[str, Any]:
    if explicit_base:
        return _find_version(library, explicit_base)
    lineage = version.get("lineage") or {}
    old_id = (
        version.get("previous_effective_version")
        or version.get("current_effective_ref")
        or version.get("latest_effective_ref")
        or version.get("base_version")
        or lineage.get("parent_candidate")
        or lineage.get("base_candidate")
        or (version.get("diff") or {}).get("adjacent_old_version")
    )
    if old_id:
        return _find_version(library, str(old_id))
    versions = list(library.get("versions", []) or [])
    for idx, item in enumerate(versions):
        if item.get("version_id") == version.get("version_id") and idx > 0:
            return versions[idx - 1]
    raise ValueError(f"cannot resolve base version for {version.get('version_id')}; pass --base")


def _infer_file_type(relpath: str) -> str:
    from lib_guard.scan.inventory import FileClassifier

    record = FileClassifier().classify({"path": relpath, "name": Path(relpath).name})
    file_type = str(record.get("file_type") or "unknown")
    if file_type not in MANUAL_FILE_DIFF_TYPES:
        raise ValueError(f"file type {file_type!r} is not supported by pairwise file-diff")
    return file_type


def _file_diff_lane(file_type: str) -> str:
    if file_type in SUMMARY_ONLY_TYPES:
        return "summary-only"
    if file_type in BINARY_METADATA_ONLY_TYPES:
        return "metadata-only"
    return "default"


def _validate_manual_file_diff_type(file_type: str, *, force_large: bool) -> None:
    if file_type in PAIRWISE_FILE_DIFF_TYPES:
        return
    if file_type in FORCE_LARGE_FILE_DIFF_TYPES:
        lane = _file_diff_lane(file_type)
        if force_large:
            return
        raise ValueError(
            f"{file_type} is {lane}; pass --force-large only for expert manual review."
        )
    supported = ", ".join(sorted(MANUAL_FILE_DIFF_TYPES))
    raise ValueError(f"unsupported file type for lg fd: {file_type}. Supported types: {supported}")


def _canonical_command(name: str | None) -> str | None:
    return SHORT_COMMAND_ALIASES.get(str(name), name) if name else name


def _rewrite_legacy_short_argv(argv: list[str]) -> list[str]:
    if not argv:
        return argv
    rewritten = list(argv)
    idx = 0
    while idx < len(rewritten):
        item = rewritten[idx]
        if item == "--config":
            idx += 2
            continue
        if item.startswith("--config="):
            idx += 1
            continue
        if item.startswith("-"):
            idx += 1
            continue
        replacement = LEGACY_SHORT_COMMAND_REWRITES.get(item)
        if replacement:
            return [*rewritten[:idx], *replacement, *rewritten[idx + 1 :]]
        return rewritten
    return rewritten


def _relpath_parts(relpath: str) -> tuple[str, ...]:
    normalized = relpath.replace("\\", "/").strip()
    drive_like = len(normalized) >= 2 and normalized[1] == ":"
    if not normalized or normalized.startswith("/") or drive_like:
        raise ValueError("file-diff relpath must be relative to the catalog version raw_path")
    parts = tuple(part for part in normalized.split("/") if part and part != ".")
    if not parts or any(part == ".." for part in parts):
        raise ValueError("file-diff relpath must not be empty or contain '..'")
    return parts


def _resolved_version_file(version: dict[str, Any], relpath: str) -> Path:
    raw_path = version.get("raw_path")
    if not raw_path:
        raise ValueError(f"version {version.get('version_id')!r} has no raw_path in catalog")
    return Path(str(raw_path)).joinpath(*_relpath_parts(relpath))


def _file_diff_out_dir(cfg: dict[str, str], library: str, version: str, relpath: str, file_type: str) -> Path:
    safe_name = "_".join(_relpath_parts(relpath)).replace(":", "_")
    stem = Path(safe_name).stem
    out_name = stem if stem.startswith(f"{file_type}_") else f"{file_type}_{stem}"
    return Path(cfg["file_diff"]) / library / version / out_name


def _build_parser() -> ArgumentParser:
    file_diff_types = " ".join(sorted(PAIRWISE_FILE_DIFF_TYPES))
    parser = ArgumentParser(
        prog="lg",
        description="lib_guard 日常短命令入口",
        formatter_class=RawDescriptionHelpFormatter,
        epilog=f"""示例:
  日常流程:
    lg.csh init $WORK --raw-root $RAW --library-type ip
    cd $WORK
    lg.csh library add <正式库名> --root <库根目录> --apply
    lg.csh library discover             # 只生成候选快照，不覆盖人工 registry
    lg.csh library discover --max-depth 4 --max-dirs 5000 --max-candidates 200
    vi $WORK/config/library_candidates/latest.tsv
    lg.csh library accept
    lg.csh library apply
    lg.csh library list                 # 查看命令应使用的正式库名
    lg.csh library list <正式库名> --versions
    lg.csh cat --with-evidence
    lg.csh cat ucie stable_20250608     # 只重渲染一个版本详情页，不重新 scan
    lg.csh library override ucie stable_20250608 --base initial_20250601 --stage stable
    lg.csh scan ucie stable_20250608
    lg.csh cat ucie --update-detail
    # 手动 compare/debug 时再显式指定 base 或 adjacent/cumulative
    lg.csh cmp ucie stable_20250608 --base initial_20250601 --scan-if-missing
    lg.csh fd ucie stable_20250608 lef/ucie.lef --base initial_20250601
    lg.csh rv check ucie stable_20250608 --gate current
    lg.csh rv accept ucie stable_20250608 --item metadata.db.changed:db/ucie.db --by lib_owner --reason accepted
    lg.csh rel ucie stable_20250608       # 默认先 release-check，再生成 symlink release 规划

  Action 文件批处理:
    lg.csh scan ucie --missing
    lg.csh action ucie

  PowerShell 使用同名命令，例如:
    lg.ps1 scan ucie stable_20250608

  不 cd 到 WORK 时:
    setenv LIB_GUARD_CONFIG $WORK/lib_guard.yml
    lg.csh --dry-run cmp ucie stable_20250608 --base initial_20250601

  支持的两两文件 diff 类型:
    {file_diff_types}

  专家手动 fd:
    需要下钻 summary-only / metadata-only 视图时显式传 --type FILE_TYPE --force-large。
""",
    )
    parser.add_argument("--config", help=f"{CONFIG_NAME} 路径")
    parser.add_argument("--dry-run", action="store_true", help="只打印展开后的底层 python 命令，不执行")
    sub = parser.add_subparsers(dest="short_command", required=True)

    p = sub.add_parser("init", help="在 workspace 中创建 lib_guard.yml")
    p.add_argument("workspace")
    p.add_argument("--raw-root")
    p.add_argument("--library-type", default="ip")

    p = sub.add_parser("scan", help="扫描指定版本，或按策略批量补 scan evidence")
    p.add_argument("library", nargs="?")
    p.add_argument("version", nargs="?")
    p.add_argument("--missing", action="store_true", help="只扫描缺少或已过期 scan evidence 的版本")
    p.add_argument("--all-versions", action="store_true", help="扫描选中 library 的全部版本")
    p.add_argument("--limit", type=int, help="限制批量扫描数量，便于试跑")
    p.add_argument("--stage", choices=["initial", "stable", "final", "ad-hoc", "dated", "unknown"], help="只扫描某个 catalog stage")
    p.add_argument("--with-evidence", action="store_true", help="扫描前刷新带文件类型 evidence 的 catalog")
    p.add_argument("--hash-policy", choices=["none", "smart", "full"], help="覆盖本次扫描的内容 hash 策略")
    p.add_argument("--parse-file-types", help="覆盖本次扫描进入 parser 的文件类型，例如 lef,cdl")
    p.add_argument("--parse-exclude-file-types", help="覆盖本次扫描不进入 parser 的文件类型，例如 verilog,liberty,spef")
    p.add_argument("--parse-jobs", help="覆盖本次扫描 parser 并发数")

    p = sub.add_parser("cat", help="刷新 catalog/HTML，或刷新版本详情更新证据")
    p.add_argument("library", nargs="?")
    p.add_argument("version", nargs="?")
    p.add_argument("--full", action="store_true", help="强制全量 catalog refresh，不复用 catalog_state.json")
    p.add_argument("--fast", action="store_true", help="只做目录级 catalog refresh；短命令默认使用该模式")
    p.add_argument("--with-evidence", action="store_true", help="为发现的版本收集轻量文件类型 evidence；大 RAW 树会更慢")
    p.add_argument("--update-detail", action="store_true", help="刷新 Version Review 更新详情；旧 refresh 命令会改写到这里")
    p.add_argument("--all", action="store_true", help="配合 --update-detail 刷新所有 catalog library 的更新详情")
    p.add_argument("--mode", default="current_effective", choices=["current_effective", "previous_effective", "adjacent", "cumulative"], help="更新详情默认使用 current/previous effective；adjacent 仅用于显式手动 compare")
    p.add_argument("--rescan", action="store_true", help="配合 --update-detail 强制重扫 old/new 版本")
    p.add_argument("--refresh-catalog", action="store_true", help="配合 --update-detail 先刷新 catalog")

    root_library = sub.add_parser("library", help="维护人工确认 library registry，并生成正式 library map")
    lsp = root_library.add_subparsers(dest="library_cmd", required=True)
    p = lsp.add_parser("discover", help="从 RAW 中发现候选 library root，写出候选快照；不会覆盖人工 registry")
    p.add_argument("--out", help="候选 TSV 输出，默认 $WORK/config/library_candidates/latest.tsv")
    p.add_argument("--json-out", help="机器发现 evidence JSON，默认 $WORK/config/library_candidates/latest.json")
    p.add_argument("--html-out", help="发现结果审查 HTML，默认 $WORK/config/library_candidates/latest.html")
    p.add_argument("--max-depth", type=int, default=4)
    p.add_argument("--min-versions", type=int, default=2)
    p.add_argument("--max-dirs", type=int, default=5000)
    p.add_argument("--max-candidates", type=int, default=200)
    p.add_argument("--default-status", choices=["REVIEW", "OK"], default="REVIEW")

    p = lsp.add_parser("accept", help="把候选 TSV 中标为 OK/ENABLE 的行合并进人工 registry")
    p.add_argument("--input", help="候选 TSV 输入，默认 $WORK/config/library_candidates/latest.tsv")
    p.add_argument("--registry", help="人工确认 registry，默认 $WORK/config/library_registry.tsv")

    p = lsp.add_parser("list", help="列出 catalog 中可直接用于命令的正式库名和版本名")
    p.add_argument("library", nargs="?", help="正式库名；传入后可配合 --versions 列版本")
    p.add_argument("--versions", action="store_true", help="列出该库的版本名")
    p.add_argument("--effective", action="store_true", help="并排列出交付库库存和当前 Effective 有效组合")

    p = lsp.add_parser("add", help="已知库根时直接加入人工 registry，不做 discover")
    p.add_argument("library_id", help="正式库名，例如 vendor_A.openroad_platform.openroad_asap7")
    p.add_argument("--root", required=True, help="库根目录，不是 RAW root")
    p.add_argument("--display-name")
    p.add_argument("--vendor")
    p.add_argument("--middle-path")
    p.add_argument("--registry", help="人工确认 registry，默认 $WORK/config/library_registry.tsv")
    p.add_argument("--apply", action="store_true", help="加入 registry 后立即生成正式 library_catalog.yml")

    p = lsp.add_parser("apply", help="把人工确认后的 registry 转成正式 library_catalog.yml")
    p.add_argument("--input", help="输入 registry，默认 $WORK/config/library_registry.tsv")
    p.add_argument("--out", help="正式 library_catalog.yml 输出，默认 $WORK/config/library_catalog.yml")

    p = lsp.add_parser("override", help="人工确认/修正一个 catalog 版本的 stage、base、package 关系")
    p.add_argument("library")
    p.add_argument("version")
    p.add_argument("--stage", choices=["initial", "stable", "final", "ad-hoc", "dated", "unknown"])
    p.add_argument("--parent", help="Compatibility alias for --previous-effective")
    p.add_argument("--base", help="Compatibility alias for --base-full")
    p.add_argument("--package-type", choices=["FULL_PACKAGE", "PARTIAL_UPDATE", "HOTFIX", "DOC_UPDATE", "UNKNOWN_PACKAGE"])
    p.add_argument("--update-scope", help="Comma/space separated scope, e.g. lib,lef")
    p.add_argument("--standalone", action="store_true", default=None)
    p.add_argument("--base-required", action="store_true", default=None)
    p.add_argument("--base-full", dest="base_full_version", help="Nearest confirmed full package baseline")
    p.add_argument("--previous-effective", dest="previous_effective_version", help="Previous accepted/effective version used as default diff target")
    p.add_argument("--compare-default", choices=["previous_effective", "full_baseline", "none"])
    p.add_argument("--current-effective", action="store_true", default=None)
    p.add_argument("--manual-review", action="store_true", default=None)
    p.add_argument("--note")
    p.add_argument("--updated-by", default="short_cli")

    p = sub.add_parser("cmp", help="按 base 关系运行结构 diff；默认不偷偷重扫")
    p.add_argument("library")
    p.add_argument("version")
    p.add_argument("--mode", default="adjacent", choices=["adjacent", "cumulative"], help="Catalog relation used when --base is not provided")
    p.add_argument("--base", help="显式指定 base version；catalog 无法可靠推断时必须传入")
    p.add_argument("--scan-if-missing", action="store_true", help="compare 前只扫描缺少或已过期 evidence 的 old/new 版本")
    p.add_argument("--rescan", action="store_true", help="compare 前强制重扫 old/new 版本")
    p.add_argument("--auto-scan", action="store_true", help=SUPPRESS)
    p.add_argument("--refresh-catalog", action="store_true", help="compare 前刷新该 library catalog；默认使用已有 catalog.json")
    p.add_argument("--with-evidence", action="store_true", help="配合 --refresh-catalog 收集文件类型 evidence")

    p = sub.add_parser("fd", help="基于 catalog raw path 运行单文件两两 diff；不会运行 scan")
    p.add_argument("library")
    p.add_argument("version")
    p.add_argument("relpath")
    p.add_argument("--base")
    p.add_argument("--type", metavar="FILE_TYPE", help="覆盖自动推断的文件类型；专家入口，具体类型按策略校验")
    p.add_argument("--force-large", action="store_true", help="Expert opt-in: allow summary-only or metadata-only file types to run manual file diff")

    p = sub.add_parser("rel", help="对已扫描版本执行 release check/link/verify 规划；不会运行 scan")
    p.add_argument("library")
    p.add_argument("version")
    p.add_argument("--alias", default="current")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--link-mode", default="symlink", choices=["copy", "symlink"])
    p.add_argument("--check-only", action="store_true", help="Only run release-check for this catalog version")
    p.add_argument("--check-first", action="store_true", help="兼容显式写法；rel 默认已先运行 release-check")
    p.add_argument("--explain", action="store_true", help="Print release-check explanation JSON without applying release")
    p.add_argument("--only-checked", action="store_true", help="Release only if prior/latest release-check is PASS/PASS_WITH_WARNING")
    p.add_argument("--only-ready", action="store_true", help="Skip manual-review or blocked versions")
    p.add_argument("--force", action="store_true")
    p.add_argument("--force-reason")
    p.add_argument("--force-by")
    p.add_argument("--no-verify", action="store_true")
    p.add_argument("--no-render", action="store_true")

    p = sub.add_parser("action", help="运行 $WORK/actions/<library>.action 中的人工编排动作")
    p.add_argument("library")
    p.add_argument("--action", help="Explicit action file path. Default: $WORK/actions/<library>.action")

    root_rv = sub.add_parser("rv", help="Review Gate 构建、检查、列表和 owner 决策")
    rvsp = root_rv.add_subparsers(dest="rv_cmd", required=True)
    for name in ["build", "check", "list"]:
        p = rvsp.add_parser(name, help="构建/检查/列出指定版本的轻量 Review Gate")
        p.add_argument("library")
        p.add_argument("version")
        p.add_argument("--gate", default="current", choices=["stage", "current", "approved"])

    for name in ["accept", "waive"]:
        p = rvsp.add_parser(name, help="记录 owner accept/waive 人工决策")
        p.add_argument("library")
        p.add_argument("version")
        p.add_argument("--gate", default="current", choices=["stage", "current", "approved"])
        p.add_argument("--item", required=True)
        p.add_argument("--by", required=True)
        p.add_argument("--reason", required=True)
    return parser


def _catalog_scan_command(
    cfg: dict[str, str],
    library: str | None = None,
    version: str | None = None,
    *,
    full: bool = False,
    with_evidence: bool = False,
) -> list[str]:
    catalog = cfg["catalog"]
    command = [
        "catalog",
        "refresh",
        "--root",
        cfg["raw_root"],
        "--out",
        str(Path(catalog).parent),
        "--library-type",
        cfg["library_type"],
        "--render",
        "--html-out",
        cfg["catalog_html"],
    ]
    if cfg.get("catalog_policy"):
        command.extend(["--policy", cfg["catalog_policy"]])
    if library:
        command.extend(["--library", library])
    if version:
        command.extend(["--render-version", version])
    if full:
        command.append("--full")
    # Short commands default to fast catalog discovery. Use --with-evidence when
    # you explicitly want catalog to recurse into version directories and count
    # file types.
    if with_evidence:
        command.append("--with-evidence")
    else:
        command.append("--fast")
    return command


def _catalog_render_command(cfg: dict[str, str], library: str | None = None, version: str | None = None) -> list[str]:
    command = [
        "catalog",
        "render",
        "--catalog",
        cfg["catalog"],
        "--out",
        cfg["catalog_html"],
    ]
    if library:
        command.extend(["--library", library])
    if version:
        command.extend(["--version", version])
    return command


def _scan_run_command(cfg: dict[str, str], library: str, version: str, args: Any | None = None) -> list[str]:
    command = [
        "run",
        "--catalog",
        cfg["catalog"],
        "--library",
        library,
        "--version",
        version,
        "--workdir",
        cfg["workspace"],
        "--console-progress",
        "--progress-interval",
        "1",
        "--catalog-html-out",
        cfg["catalog_html"],
    ]
    _append_scan_strategy(command, cfg, args)
    return command


def _scan_strategy_value(cfg: dict[str, str], args: Any | None, key: str) -> str:
    override = getattr(args, key, None) if args is not None else None
    value = override if override not in {None, ""} else cfg.get(key)
    return str(value or "")


def _append_scan_strategy(command: list[str], cfg: dict[str, str], args: Any | None = None) -> None:
    parse_jobs = _scan_strategy_value(cfg, args, "parse_jobs") or cfg["parse_jobs"]
    command.extend(["--parse-jobs", parse_jobs])
    for key in SCAN_STRATEGY_CONFIG_KEYS:
        value = _scan_strategy_value(cfg, args, key)
        if value:
            command.extend([f"--{key.replace('_', '-')}", value])


def _library_discover_command(cfg: dict[str, str], args: Any) -> list[str]:
    candidates = Path(cfg["library_candidates"])
    return [
        "library",
        "discover",
        "--root",
        cfg["raw_root"],
        "--out",
        args.out or str(candidates),
        "--json-out",
        args.json_out or str(candidates.with_suffix(".json")),
        "--html-out",
        args.html_out or str(candidates.with_suffix(".html")),
        "--max-depth",
        str(args.max_depth),
        "--min-versions",
        str(args.min_versions),
        "--max-dirs",
        str(args.max_dirs),
        "--max-candidates",
        str(args.max_candidates),
        "--default-status",
        args.default_status,
    ]


def _library_accept_command(cfg: dict[str, str], args: Any) -> list[str]:
    return [
        "library",
        "accept",
        "--root",
        cfg["raw_root"],
        "--input",
        args.input or cfg["library_candidates"],
        "--registry",
        args.registry or cfg["library_registry"],
    ]


def _library_add_command(cfg: dict[str, str], args: Any) -> list[str]:
    command = [
        "library",
        "add",
        "--root",
        cfg["raw_root"],
        "--registry",
        args.registry or cfg["library_registry"],
        "--library-id",
        args.library_id,
        "--library-root",
        args.root,
    ]
    for opt, value in [
        ("--display-name", args.display_name),
        ("--vendor", args.vendor),
        ("--middle-path", args.middle_path),
    ]:
        if value:
            command.extend([opt, value])
    return command


def _library_list_command(cfg: dict[str, str], args: Any) -> list[str]:
    command = ["catalog", "list", "--catalog", cfg["catalog"]]
    if getattr(args, "library", None):
        command.extend(["--library", args.library])
    if getattr(args, "versions", False):
        command.append("--versions")
    if getattr(args, "effective", False):
        command.extend(["--effective", "--html-out", cfg["catalog_html"]])
    return command


def _library_apply_command(cfg: dict[str, str], args: Any) -> list[str]:
    registry_path = Path(cfg["library_registry"])
    legacy_list = Path(cfg["library_list"])
    default_input = str(registry_path if registry_path.exists() or not legacy_list.exists() else legacy_list)
    return [
        "library",
        "apply",
        "--root",
        cfg["raw_root"],
        "--input",
        args.input or default_input,
        "--out",
        args.out or cfg["library_catalog"],
        "--library-type",
        cfg["library_type"],
    ]


def _override_command(cfg: dict[str, str], args: Any) -> list[str]:
    data = _catalog_data(cfg)
    lib = _find_library(data, args.library)
    version_key = f"{lib.get('library_type') or cfg['library_type']}/{lib.get('library_name')}/{args.version}"
    command = [
        "catalog",
        "override",
        "--catalog",
        cfg["catalog"],
        "--version",
        version_key,
        "--updated-by",
        args.updated_by,
    ]
    for opt, value in [
        ("--stage", args.stage),
        ("--parent", args.parent),
        ("--base", args.base),
        ("--package-type", args.package_type),
        ("--update-scope", args.update_scope),
        ("--base-full", args.base_full_version),
        ("--previous-effective", args.previous_effective_version),
        ("--compare-default", args.compare_default),
        ("--note", args.note),
    ]:
        if value is not None:
            command.extend([opt, str(value)])
    for opt, value in [
        ("--standalone", args.standalone),
        ("--base-required", args.base_required),
        ("--current-effective", args.current_effective),
        ("--manual-review", args.manual_review),
    ]:
        if value:
            command.append(opt)
    return command


def _review_gate_command(cfg: dict[str, str], args: Any, subcommand: str) -> list[str]:
    command = [
        "review",
        subcommand,
        "--catalog",
        cfg["catalog"],
        "--library",
        args.library,
        "--version",
        args.version,
        "--gate",
        args.gate,
        "--catalog-html-out",
        cfg["catalog_html"],
    ]
    if subcommand in {"accept", "waive"}:
        command.extend(["--item", args.item, "--by", args.by, "--reason", args.reason])
    return command


def _scan_batch_command(
    cfg: dict[str, str],
    library: str | None,
    *,
    only_missing: bool = False,
    limit: int | None = None,
    stage: str | None = None,
    strategy_args: Any | None = None,
) -> list[str]:
    command = [
        "run-batch",
        "--catalog",
        cfg["catalog"],
        "--workdir",
        cfg["workspace"],
        "--console-progress",
        "--progress-interval",
        "1",
        "--catalog-html-out",
        cfg["catalog_html"],
    ]
    _append_scan_strategy(command, cfg, strategy_args)
    if library:
        command.extend(["--library", library])
    if only_missing:
        command.append("--only-missing")
    if limit is not None:
        command.extend(["--limit", str(limit)])
    if stage:
        command.extend(["--stage", stage])
    return command


def _scan_library_help(library: str) -> str:
    return (
        f"scan {library!r} is ambiguous because one library can have many versions.\n"
        "Use one explicit mode:\n"
        f"  lg.csh scan {library} <version>\n"
        f"  lg.csh scan {library} --missing\n"
        f"  lg.csh scan {library} --all-versions\n"
        f"  lg.csh scan {library} --limit 3\n"
        f"  lg.csh scan {library} --stage stable --missing"
    )


def _find_version_in_catalog(cfg: dict[str, str], library: str, version: str) -> dict[str, Any] | None:
    try:
        lib = _find_library(_catalog_data(cfg), library)
        return _find_version(lib, version)
    except Exception:
        return None


def _scan_evidence_exists(cfg: dict[str, str], library: str, version: str) -> bool:
    item = _find_version_in_catalog(cfg, library, version)
    if not item:
        return False
    scan = item.get("scan") or {}
    if str(scan.get("status") or "").upper() in {"NOT_SCANNED", "STALE_SCAN"}:
        return False
    scan_dir = ((item.get("scan") or {}).get("scan_dir") or item.get("scan_dir"))
    return bool(scan_dir and Path(str(scan_dir)).exists())


def _library_report_key(cfg: dict[str, str], library: str) -> str:
    try:
        lib = _find_library(_catalog_data(cfg), library)
        return _safe_path_name(str(lib.get("library_id") or lib.get("library_name") or library))
    except Exception:
        return _safe_path_name(library)


def _effective_dir(cfg: dict[str, str], library: str, effective_id: str) -> Path:
    return Path(cfg["catalog_html"]) / "libraries" / _library_report_key(cfg, library) / "effective" / _safe_path_name(effective_id)


def _compare_dir(cfg: dict[str, str], library: str, compare_id: str) -> Path:
    return Path(cfg["catalog_html"]) / "libraries" / _library_report_key(cfg, library) / "compare" / _safe_path_name(compare_id)


def _current_effective_id(cfg: dict[str, str], library: str) -> str | None:
    current_path = Path(cfg["catalog_html"]) / "libraries" / _library_report_key(cfg, library) / "effective" / "current_effective.json"
    if not current_path.exists():
        return None
    try:
        data = json.loads(current_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return str(data.get("current_effective_id") or "") or None


def _resolve_review_version(token: str, refs: dict[str, str]) -> str:
    return refs.get(token, token)


def _review_effect_versions(actions: dict[str, Any], refs: dict[str, str]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for item in actions.get("effects", []) or []:
        result[str(item["name"])] = [_resolve_review_version(str(v), refs) for v in item.get("versions", [])]
    return result


def _review_target(token: str, cfg: dict[str, str], library: str, refs: dict[str, str], effect_names: set[str]) -> str:
    if ":" in token:
        return token
    if token == "current":
        current = _current_effective_id(cfg, library)
        return f"effective:{current or 'current'}"
    if token in effect_names:
        return f"effective:{token}"
    version = _resolve_review_version(token, refs)
    if version != token or _find_version_in_catalog(cfg, library, version):
        return f"raw:{version}"
    return f"effective:{token}"


def _review_commands(cfg: dict[str, str], args: Any) -> list[list[str]]:
    action_path = Path(args.action) if getattr(args, "action", None) else _review_action_path(cfg, args.library)
    actions = _parse_review_actions(action_path)
    refs = _version_ref_map(cfg, args.library)
    effect_versions = _review_effect_versions(actions, refs)
    effect_names = set(effect_versions)
    redo_all = bool(actions.get("redo_all"))
    commands: list[list[str]] = []
    queued_normal_scans: set[str] = set()

    def add_scan(version: str, *, force: bool) -> None:
        if not force and version in queued_normal_scans:
            return
        if not force and _scan_evidence_exists(cfg, args.library, version):
            return
        if not force:
            queued_normal_scans.add(version)
        commands.append(_scan_run_command(cfg, args.library, version))

    for scan in actions.get("scans", []) or []:
        force = redo_all or bool(scan.get("force"))
        for token in scan.get("versions", []) or []:
            if token == "auto":
                for versions in effect_versions.values():
                    for version in versions:
                        add_scan(version, force=force)
            else:
                add_scan(_resolve_review_version(str(token), refs), force=force)

    for effect in actions.get("effects", []) or []:
        name = str(effect["name"])
        versions = effect_versions[name]
        if not versions:
            continue
        out_dir = _effective_dir(cfg, args.library, name)
        manifest = out_dir / "effective_manifest.json"
        force = redo_all or bool(effect.get("force"))
        if manifest.exists() and not force:
            continue
        command = [
            "effective",
            "build",
            "--catalog",
            cfg["catalog"],
            "--library",
            args.library,
            "--base-full",
            versions[0],
            "--effective-id",
            name,
            "--out",
            str(manifest),
            "--html",
            str(out_dir / "index.html"),
        ]
        for version in versions[1:]:
            command.extend(["--include", version])
        commands.append(command)

    for diff in actions.get("diffs", []) or []:
        name = str(diff["name"])
        out_dir = _compare_dir(cfg, args.library, name)
        force = redo_all or bool(diff.get("force"))
        if (out_dir / "compare_manifest.json").exists() and not force:
            continue
        commands.append(
            [
                "effective",
                "compare",
                "--catalog",
                cfg["catalog"],
                "--library",
                args.library,
                "--old",
                _review_target(str(diff["old"]), cfg, args.library, refs, effect_names),
                "--new",
                _review_target(str(diff["new"]), cfg, args.library, refs, effect_names),
                "--out-dir",
                str(out_dir),
                "--html",
                str(out_dir / "index.html"),
                "--compare-id",
                name,
                "--search-root",
                cfg["catalog_html"],
            ]
        )

    for release in actions.get("releases", []) or []:
        target = str(release["target"])
        effective_id = target if target in effect_names else target.replace("effective:", "")
        out_dir = _effective_dir(cfg, args.library, effective_id)
        release_dir = out_dir / "release_preview"
        force = redo_all or bool(release.get("force"))
        if (release_dir / "release_manifest.json").exists() and not force:
            continue
        commands.append(
            [
                "effective",
                "release-preview",
                "--effective",
                str(out_dir / "effective_manifest.json"),
                "--release-root",
                cfg["release_root"],
                "--release-id",
                f"release_{effective_id}",
                "--out-dir",
                str(release_dir),
                "--html",
                str(release_dir / "index.html"),
            ]
        )
    return commands

def build_cli_commands(argv: list[str], *, cwd: str | Path | None = None) -> list[list[str]]:
    parser = _build_parser()
    argv = _rewrite_legacy_short_argv(list(argv))
    args = parser.parse_args(argv)
    args.short_command = _canonical_command(args.short_command)
    if args.short_command == "init":
        return []
    cfg = _load_config(cwd or Path.cwd(), args.config)
    catalog = cfg["catalog"]
    html = cfg["catalog_html"]
    if args.short_command == "library":
        if args.library_cmd == "discover":
            return [_library_discover_command(cfg, args)]
        if args.library_cmd == "accept":
            return [_library_accept_command(cfg, args)]
        if args.library_cmd == "list":
            return [_library_list_command(cfg, args)]
        if args.library_cmd == "add":
            commands = [_library_add_command(cfg, args)]
            if getattr(args, "apply", False):
                commands.append(_library_apply_command(cfg, Namespace(input=args.registry, out=None)))
            return commands
        if args.library_cmd == "apply":
            return [_library_apply_command(cfg, args)]
        if args.library_cmd == "override":
            return [_override_command(cfg, args)]
        raise ValueError(f"unsupported library command: {args.library_cmd}")
    if args.short_command == "cat":
        if getattr(args, "update_detail", False):
            return _refresh_commands(cfg, args)
        if args.library and getattr(args, "version", None):
            return [_catalog_render_command(cfg, args.library, args.version)]
        return [
            _catalog_scan_command(
                cfg,
                args.library,
                getattr(args, "version", None),
                full=bool(getattr(args, "full", False)),
                with_evidence=bool(getattr(args, "with_evidence", False)),
            )
        ]
    if args.short_command == "rv":
        review_subcommand = args.rv_cmd
        return [_review_gate_command(cfg, args, review_subcommand)]
    if args.short_command == "action":
        return _review_commands(cfg, args)
    if args.short_command == "scan":
        with_evidence = bool(getattr(args, "with_evidence", False))
        if args.library and args.version:
            commands: list[list[str]] = []
            if with_evidence or not _find_version_in_catalog(cfg, args.library, args.version):
                commands.append(_catalog_scan_command(cfg, args.library, with_evidence=with_evidence))
            commands.append(_scan_run_command(cfg, args.library, args.version, args))
            return commands
        if args.library:
            has_batch_intent = bool(
                getattr(args, "missing", False)
                or getattr(args, "all_versions", False)
                or getattr(args, "limit", None) is not None
                or getattr(args, "stage", None)
            )
            if not has_batch_intent:
                raise ValueError(_scan_library_help(args.library))
            return [
                _catalog_scan_command(cfg, args.library, with_evidence=with_evidence),
                _scan_batch_command(
                    cfg,
                    args.library,
                    only_missing=bool(getattr(args, "missing", False)),
                    limit=getattr(args, "limit", None),
                    stage=getattr(args, "stage", None),
                    strategy_args=args,
                ),
            ]
        raise ValueError("lg scan requires <library> <version> or <library> --missing/--all-versions. Use lg cat to refresh catalog/HTML.")
    if args.short_command == "cmp":
        commands: list[list[str]] = []
        if getattr(args, "rescan", False) and (getattr(args, "scan_if_missing", False) or getattr(args, "auto_scan", False)):
            raise ValueError("Use only one of --scan-if-missing/--auto-scan or --rescan")
        if getattr(args, "refresh_catalog", False):
            commands.append(_catalog_scan_command(cfg, args.library, with_evidence=bool(getattr(args, "with_evidence", False))))
        compare = [
            "compare",
            "--catalog",
            catalog,
            "--library",
            args.library,
            "--new",
            args.version,
            "--mode",
            args.mode,
            "--workdir",
            cfg["workspace"],
            "--catalog-html-out",
            html,
        ]
        if args.base:
            compare.extend(["--base", args.base])
        if getattr(args, "scan_if_missing", False) or getattr(args, "auto_scan", False):
            compare.append("--scan-if-missing")
            _append_scan_strategy(compare, cfg)
        if getattr(args, "rescan", False):
            compare.append("--rescan")
            _append_scan_strategy(compare, cfg)
        commands.append(compare)
        return commands
    if args.short_command == "fd":
        data = _catalog_data(cfg)
        lib = _find_library(data, args.library)
        new_version = _find_version(lib, args.version)
        old_version = _resolve_old_version(lib, new_version, args.base)
        file_type = args.type or _infer_file_type(args.relpath)
        _validate_manual_file_diff_type(file_type, force_large=bool(getattr(args, "force_large", False)))
        old_file = _resolved_version_file(old_version, args.relpath)
        new_file = _resolved_version_file(new_version, args.relpath)
        out = _file_diff_out_dir(cfg, args.library, args.version, args.relpath, file_type)
        command = [
            "file-diff",
            file_type,
            "--old",
            str(old_file),
            "--new",
            str(new_file),
            "--out",
            str(out),
            "--library-id",
            str(lib.get("library_id") or lib.get("library_name") or args.library),
            "--version-id",
            str(new_version.get("version_id") or args.version),
            "--base-version",
            str(old_version.get("version_id") or args.base or ""),
        ]
        if bool(getattr(args, "force_large", False)) and file_type in FORCE_LARGE_FILE_DIFF_TYPES:
            command.append("--manual-large-file-opt-in")
        return [command]
    if args.short_command == "rel":
        if args.force and not args.force_reason:
            raise ValueError("lg rel --force requires --force-reason")
        commands: list[list[str]] = []
        check_cmd = [
            "catalog",
            "release-check",
            "--catalog",
            catalog,
            "--library",
            args.library,
            "--version",
            args.version,
            "--policy",
            cfg["release_policy"],
            "--alias",
            args.alias,
        ]
        if args.explain:
            check_cmd.append("--explain")
            return [check_cmd]
        if args.check_only:
            return [check_cmd]
        commands.append(check_cmd)
        command = [
            "release-batch",
            "--catalog",
            catalog,
            "--library",
            args.library,
            "--version",
            args.version,
            "--release-root",
            cfg["release_root"],
            "--policy",
            cfg["release_policy"],
            "--alias",
            args.alias,
            "--link-mode",
            args.link_mode,
            "--catalog-html-out",
            html,
        ]
        if args.apply:
            command.append("--apply")
        if args.overwrite:
            command.append("--overwrite")
        if args.only_checked:
            command.append("--only-checked")
        if args.only_ready:
            command.append("--only-ready")
        if args.force:
            command.append("--force")
        if args.force_reason:
            command.extend(["--force-reason", args.force_reason])
        if args.force_by:
            command.extend(["--force-by", args.force_by])
        if args.no_verify:
            command.append("--no-verify")
        if args.no_render:
            command.append("--no-render")
        commands.append(command)
        return commands
    raise ValueError(f"unsupported short command: {args.short_command}")


def build_cli_command(argv: list[str], *, cwd: str | Path | None = None) -> list[str]:
    commands = build_cli_commands(argv, cwd=cwd)
    return commands[-1] if commands else []


def _command_for_execution(command: list[str]) -> list[str]:
    return [item for item in command if item != "--manual-large-file-opt-in"]


def run_init(args: Namespace) -> int:
    path = write_default_config(args.workspace, raw_root=args.raw_root, library_type=args.library_type)
    print(json.dumps({"status": "PASS", "config": _norm(path)}, ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    argv = _rewrite_legacy_short_argv(argv)
    parser = _build_parser()
    args = parser.parse_args(argv)
    args.short_command = _canonical_command(args.short_command)
    if args.short_command == "init":
        return run_init(args)
    try:
        commands = build_cli_commands(argv, cwd=Path.cwd())
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if args.short_command == "cmp" and getattr(args, "auto_scan", False):
        print("[WARN] 'lg cmp --auto-scan' is deprecated and now means --scan-if-missing, not forced rescan.", file=sys.stderr)
        print("[INFO] Use --rescan only when you intentionally want to rebuild both scan outputs.", file=sys.stderr)
    for command in commands:
        print("python -m lib_guard.cli " + shlex.join(_command_for_execution(command)))
    if args.dry_run:
        return 0
    from lib_guard.cli import main as cli_main

    for command in commands:
        code = cli_main(_command_for_execution(command))
        if code != 0:
            return int(code)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
