from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping
from datetime import datetime
import os

from lib_guard.project_config import (
    CATALOG_POLICY_FILE,
    CONFIG_NAME,
    DEFAULT_DISCOVER_MAX_CANDIDATES,
    DEFAULT_DISCOVER_MAX_DEPTH,
    DEFAULT_DISCOVER_MAX_DIRS,
    DEFAULT_DISCOVER_MIN_VERSIONS,
    DEFAULT_HASH_POLICY,
    DEFAULT_LIBRARY_TYPE,
    DEFAULT_PARSE_JOBS,
    DEFAULT_RENDER_DETAIL,
    DEFAULT_SCAN_MODE,
    DISCOVERY_CONFIG_KEYS,
    HASH_POLICIES,
    MAX_PARSE_JOBS,
    MIN_PARSE_JOBS,
    RELEASE_POLICY_FILE,
    SCAN_STRATEGY_CONFIG_KEYS,
    WORKSPACE_CONFIG_FILE_DEFAULTS,
    WORKSPACE_CONFIG_SCHEMA_VERSION,
    WORKSPACE_PATH_DEFAULTS,
    project_policy_path,
    workspace_config_file_defaults,
    workspace_defaults,
)


_CONFIG_KEYS = frozenset(
    {
        "config_version",
        "workspace",
        "library_type",
        "mode",
        "parse_jobs",
        "render_detail",
        "catalog_policy",
        "release_policy",
        "release_publish_name",
        "release_latest_name",
        "scan_out",
        "versions",
        *SCAN_STRATEGY_CONFIG_KEYS,
        *DISCOVERY_CONFIG_KEYS,
        *WORKSPACE_PATH_DEFAULTS,
        *WORKSPACE_CONFIG_FILE_DEFAULTS,
    }
)
EDITABLE_WORKSPACE_CONFIG_KEYS = frozenset(
    {
        "raw_root",
        "release_root",
        "library_type",
        "release_publish_name",
        "release_latest_name",
        "parse_jobs",
        "hash_policy",
        "force_hash_file_types",
        "skip_hash_file_types",
        "parse_file_types",
        "parse_exclude_file_types",
        "render_detail",
        *DISCOVERY_CONFIG_KEYS,
    }
)
_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}
_LEGACY_SCAN_MODES = {"candidate"}


@dataclass(frozen=True)
class WorkspaceConfig:
    """Validated workspace configuration with typed execution settings.

    Path-heavy legacy callers can keep using ``as_dict()``. New orchestration
    code should use the typed fields so boolean and integer parsing is not
    repeated at each command boundary.
    """

    config_version: str
    workspace: Path
    library_type: str
    mode: str
    parse_jobs: int
    hash_policy: str
    render_detail: bool
    _values: Mapping[str, str]

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> "WorkspaceConfig":
        normalized = {str(key): str(value) for key, value in values.items()}
        return cls(
            config_version=normalized["config_version"],
            workspace=Path(normalized["workspace"]),
            library_type=normalized["library_type"],
            mode=normalized["mode"],
            parse_jobs=int(normalized["parse_jobs"]),
            hash_policy=normalized["hash_policy"],
            render_detail=normalized["render_detail"] == "true",
            _values=MappingProxyType(normalized),
        )

    def as_dict(self) -> dict[str, str]:
        return dict(self._values)

    def get(self, key: str, default: str | None = None) -> str | None:
        return self._values.get(key, default)


def _validate_config(data: dict[str, str], *, path: Path) -> None:
    config_version = str(data.get("config_version") or WORKSPACE_CONFIG_SCHEMA_VERSION)
    if config_version != WORKSPACE_CONFIG_SCHEMA_VERSION:
        raise ValueError(
            f"config_version 只支持 {WORKSPACE_CONFIG_SCHEMA_VERSION}，实际为 {config_version}: {path}"
        )
    data["config_version"] = config_version

    unknown = sorted(set(data) - _CONFIG_KEYS)
    if unknown:
        raise ValueError(f"未知配置项 {', '.join(unknown)}: {path}")
    from lib_guard.release.bundle import validate_release_name
    for key in ("release_publish_name", "release_latest_name"):
        if data.get(key):
            data[key] = validate_release_name(data[key])
    if data.get("release_publish_name") and data["release_publish_name"] == (data.get("release_latest_name") or "latest"):
        raise ValueError("正式目录名与最新指针名不能相同")

    mode = str(data.get("mode") or DEFAULT_SCAN_MODE).lower()
    if mode in _LEGACY_SCAN_MODES:
        mode = DEFAULT_SCAN_MODE
    elif mode != DEFAULT_SCAN_MODE:
        raise ValueError(f"mode 只支持 {DEFAULT_SCAN_MODE}: {path}")

    parse_jobs = str(data.get("parse_jobs") or DEFAULT_PARSE_JOBS)
    try:
        jobs = int(parse_jobs)
    except ValueError as exc:
        raise ValueError(f"parse_jobs 必须是 1 到 32 的整数: {path}") from exc
    if not MIN_PARSE_JOBS <= jobs <= MAX_PARSE_JOBS:
        raise ValueError(f"parse_jobs 必须是 {MIN_PARSE_JOBS} 到 {MAX_PARSE_JOBS} 的整数: {path}")

    hash_policy = str(data.get("hash_policy") or DEFAULT_HASH_POLICY).lower()
    if hash_policy not in HASH_POLICIES:
        raise ValueError(f"hash_policy 只能是 none、smart 或 full: {path}")

    render_detail = str(data.get("render_detail") or DEFAULT_RENDER_DETAIL).lower()
    if render_detail not in _TRUE_VALUES | _FALSE_VALUES:
        raise ValueError(f"render_detail 必须是 true 或 false: {path}")

    discovery_limits = {
        "discover_max_depth": (DEFAULT_DISCOVER_MAX_DEPTH, 1, 8, "发现深度"),
        "discover_min_versions": (DEFAULT_DISCOVER_MIN_VERSIONS, 1, 100, "最少版本数"),
        "discover_max_dirs": (DEFAULT_DISCOVER_MAX_DIRS, 1, 100000, "最大目录数"),
        "discover_max_candidates": (DEFAULT_DISCOVER_MAX_CANDIDATES, 1, 10000, "最多候选数"),
    }
    for key, (default, minimum, maximum, label) in discovery_limits.items():
        raw_value = str(data.get(key) or default)
        try:
            number = int(raw_value)
        except ValueError as exc:
            raise ValueError(f"{label}必须是整数: {path}") from exc
        if not minimum <= number <= maximum:
            raise ValueError(f"{label}必须在 {minimum} 到 {maximum} 之间: {path}")
        data[key] = str(number)

    data["mode"] = mode
    data["parse_jobs"] = str(jobs)
    data["hash_policy"] = hash_policy
    data["render_detail"] = "true" if render_detail in _TRUE_VALUES else "false"


def norm(path: str | Path) -> str:
    return str(Path(path))


def write_default_config(
    workspace: str | Path,
    *,
    raw_root: str | Path | None = None,
    library_type: str = DEFAULT_LIBRARY_TYPE,
) -> Path:
    root = Path(workspace).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    raw = Path(raw_root).expanduser().resolve() if raw_root is not None else None
    cfg = workspace_defaults(root, raw_root=raw, library_type=library_type)
    Path(cfg["release_root"]).mkdir(parents=True, exist_ok=True)
    ordered_keys = [
        "config_version",
        "workspace",
        "raw_root",
        "catalog",
        "catalog_html",
        "reports",
        "diff",
        "file_diff",
        "release_root",
        "release_library_index",
        "versions",
        "actions_dir",
        "library_type",
        "mode",
        "parse_jobs",
        "hash_policy",
        "force_hash_file_types",
        "skip_hash_file_types",
        "parse_file_types",
        "parse_exclude_file_types",
        "render_detail",
        "discover_max_depth",
        "discover_min_versions",
        "discover_max_dirs",
        "discover_max_candidates",
    ]
    lines = [
        "# lib_guard short command workspace",
        *[f"{key}: {cfg[key]}" for key in ordered_keys],
    ]
    path = root / CONFIG_NAME
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def parse_config(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            raise ValueError(f"配置行缺少冒号，第 {line_number} 行: {path}")
        key, value = line.split(":", 1)
        key = key.strip()
        if not key:
            raise ValueError(f"配置项名称为空，第 {line_number} 行: {path}")
        if key in data:
            raise ValueError(f"重复配置项 {key}，第 {line_number} 行: {path}")
        data[key] = value.strip().strip("\"'")
    return data


def find_config(cwd: str | Path, explicit: str | Path | None = None) -> Path:
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


def load_config(cwd: str | Path, explicit: str | Path | None = None) -> dict[str, str]:
    path = find_config(cwd, explicit)
    cfg = parse_config(path)
    _validate_config(cfg, path=path)
    project_root = os.environ.get("LIB_GUARD_PROJECT_ROOT") or Path(__file__).resolve().parents[2]
    default_catalog_policy = project_policy_path(project_root, CATALOG_POLICY_FILE)
    default_release_policy = project_policy_path(project_root, RELEASE_POLICY_FILE)
    cwd_root = Path(cwd).resolve()
    workspace_text = cfg.get("workspace") or ""
    workspace_value = Path(workspace_text).expanduser() if workspace_text else path.parent
    if workspace_value.is_absolute():
        workspace_root = workspace_value.resolve()
    else:
        cwd_candidate = (cwd_root / workspace_value).resolve()
        if (cwd_candidate / CONFIG_NAME) == path.resolve():
            workspace_root = cwd_candidate
        elif path.parent.name == workspace_value.name:
            workspace_root = path.parent.resolve()
        else:
            workspace_root = (path.parent / workspace_value).resolve()
    cfg["workspace"] = str(workspace_root)
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
    workspace_prefix = Path(workspace_text).expanduser() if workspace_text else None

    def normalize_workspace_path(key: str) -> None:
        value = cfg.get(key)
        if not value:
            return
        p = Path(value).expanduser()
        if p.is_absolute():
            cfg[key] = str(p.resolve())
            return
        if workspace_prefix and not workspace_prefix.is_absolute():
            try:
                rel = p.relative_to(workspace_prefix)
                cfg[key] = str((workspace_root / rel).resolve())
                return
            except ValueError:
                pass
        cfg[key] = str((workspace_root / p).resolve())

    def normalize_existing_or_cwd_path(key: str) -> None:
        value = cfg.get(key)
        if not value:
            return
        p = Path(value).expanduser()
        if p.is_absolute():
            cfg[key] = str(p.resolve())
            return
        for base in [cwd_root, Path(project_root).resolve(), path.parent.resolve()]:
            candidate = (base / p).resolve()
            if candidate.exists():
                cfg[key] = str(candidate)
                return
        cfg[key] = str((cwd_root / p).resolve())

    for key in [
        "catalog",
        "catalog_html",
        "reports",
        "diff",
        "file_diff",
        "release_root",
        "release_library_index",
        "versions",
        "actions_dir",
        "config_dir",
        "library_list",
        "library_registry",
        "library_candidates",
        "library_catalog",
        "library_versions",
    ]:
        normalize_workspace_path(key)
    normalize_existing_or_cwd_path("raw_root")
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


def _config_value_to_text(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple, set)):
        return ",".join(str(item).strip() for item in value if str(item).strip())
    return str(value or "").strip()


def update_config_file(path: str | Path, updates: Mapping[str, Any]) -> dict[str, str]:
    """Safely update human-facing workspace defaults in ``lib_guard.yml``.

    This intentionally supports a small allowlist instead of a free-form YAML
    editor.  The web console can expose useful defaults without becoming a
    second configuration language.
    """

    config_path = Path(path).expanduser().resolve()
    if not config_path.is_file():
        raise FileNotFoundError(f"配置文件不存在: {config_path}")
    unknown = sorted(str(key) for key in updates if str(key) not in EDITABLE_WORKSPACE_CONFIG_KEYS)
    if unknown:
        raise ValueError(f"网页不支持修改这些配置项: {', '.join(unknown)}")
    current = parse_config(config_path)
    normalized_updates = {str(key): _config_value_to_text(value) for key, value in updates.items()}
    candidate = {**current, **normalized_updates}
    _validate_config(candidate, path=config_path)
    raw_root = Path(candidate.get("raw_root") or "").expanduser()
    if not raw_root.is_absolute():
        raw_root = (config_path.parent / raw_root).resolve()
    if not raw_root.is_dir():
        raise ValueError(f"原始库根不存在或不是目录: {raw_root}")
    candidate["raw_root"] = str(raw_root.resolve())
    if "release_root" in normalized_updates:
        release_root = Path(candidate.get("release_root") or "").expanduser()
        if not release_root.is_absolute():
            release_root = (config_path.parent / release_root).resolve()
        if not release_root.is_dir():
            raise ValueError(f"正式发布根目录不存在或不是目录: {release_root}")
        candidate["release_root"] = str(release_root.resolve())

    original_lines = config_path.read_text(encoding="utf-8").splitlines()
    seen: set[str] = set()
    lines: list[str] = []
    for raw_line in original_lines:
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#") or ":" not in raw_line:
            lines.append(raw_line)
            continue
        key = raw_line.split(":", 1)[0].strip()
        if key in normalized_updates:
            lines.append(f"{key}: {candidate[key]}")
            seen.add(key)
        else:
            lines.append(raw_line)
            seen.add(key)
    append_order = [
        "config_version",
        "raw_root",
        "release_root",
        "release_publish_name",
        "release_latest_name",
        "library_type",
        "parse_jobs",
        "hash_policy",
        "force_hash_file_types",
        "skip_hash_file_types",
        "parse_file_types",
        "parse_exclude_file_types",
        "render_detail",
        "discover_max_depth",
        "discover_min_versions",
        "discover_max_dirs",
        "discover_max_candidates",
    ]
    for key in append_order:
        if key in candidate and key not in seen:
            lines.append(f"{key}: {candidate[key]}")
            seen.add(key)

    backup = config_path.with_name(f"{config_path.name}.bak_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    backup.write_text(config_path.read_text(encoding="utf-8"), encoding="utf-8")
    config_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return {
        "status": "PASS",
        "config": str(config_path),
        "backup": str(backup),
        "updated": ",".join(sorted(normalized_updates)),
    }


def load_workspace_config(cwd: str | Path, explicit: str | Path | None = None) -> WorkspaceConfig:
    """Load the canonical typed model without changing legacy consumers."""

    return WorkspaceConfig.from_mapping(load_config(cwd, explicit))


def merge_config_overrides(
    config: WorkspaceConfig,
    overrides: Mapping[str, Any],
) -> WorkspaceConfig:
    """Apply explicit per-run execution settings over workspace configuration."""

    allowed = {"mode", "parse_jobs", "hash_policy", "render_detail", *SCAN_STRATEGY_CONFIG_KEYS}
    unknown = sorted(key for key, value in overrides.items() if value is not None and key not in allowed)
    if unknown:
        raise ValueError(f"不支持的本次运行覆盖项: {', '.join(unknown)}")
    values = config.as_dict()
    for key, value in overrides.items():
        if value is None:
            continue
        if isinstance(value, bool):
            values[key] = "true" if value else "false"
        else:
            values[key] = str(value)
    _validate_config(values, path=Path("<cli-overrides>"))
    return WorkspaceConfig.from_mapping(values)
