from __future__ import annotations

from pathlib import Path
import os

from lib_guard.project_config import (
    CATALOG_POLICY_FILE,
    CONFIG_NAME,
    DEFAULT_LIBRARY_TYPE,
    DEFAULT_PARSE_JOBS,
    DEFAULT_SCAN_MODE,
    RELEASE_POLICY_FILE,
    project_policy_path,
    workspace_config_file_defaults,
    workspace_defaults,
)


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


def parse_config(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        data[key.strip()] = value.strip().strip("\"'")
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
