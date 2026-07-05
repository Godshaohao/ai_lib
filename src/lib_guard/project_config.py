from __future__ import annotations

from pathlib import Path


CONFIG_NAME = "lib_guard.yml"
PROJECT_CONFIG_DIR = "configs"
WORKSPACE_CONFIG_DIR = "config"

DEFAULT_LIBRARY_TYPE = "ip"
DEFAULT_SCAN_MODE = "scan"
DEFAULT_PARSE_JOBS = "8"
SCAN_STRATEGY_CONFIG_KEYS = (
    "hash_policy",
    "parse_file_types",
    "parse_exclude_file_types",
)

CATALOG_POLICY_FILE = "catalog_policy.json"
RELEASE_POLICY_FILE = "release_policy.json"

DEFAULT_CATALOG_POLICY_PATH = f"{PROJECT_CONFIG_DIR}/{CATALOG_POLICY_FILE}"
DEFAULT_RELEASE_POLICY_PATH = f"{PROJECT_CONFIG_DIR}/{RELEASE_POLICY_FILE}"

WORKSPACE_PATH_DEFAULTS = {
    "raw_root": "raw",
    "catalog": "catalog/catalog.json",
    "catalog_html": "catalog/html",
    "reports": "reports",
    "diff": "diff",
    "file_diff": "file_diff",
    "release_root": "release_area",
    "config_dir": WORKSPACE_CONFIG_DIR,
    "library_list": f"{WORKSPACE_CONFIG_DIR}/library.list",
    "library_registry": f"{WORKSPACE_CONFIG_DIR}/library_registry.tsv",
    "library_candidates": f"{WORKSPACE_CONFIG_DIR}/library_candidates/latest.tsv",
    "library_catalog": f"{WORKSPACE_CONFIG_DIR}/library_catalog.yml",
    "library_versions": f"{WORKSPACE_CONFIG_DIR}/library_versions.tsv",
    "actions_dir": "actions",
}

WORKSPACE_CONFIG_FILE_DEFAULTS = {
    "library_list": "library.list",
    "library_registry": "library_registry.tsv",
    "library_candidates": "library_candidates/latest.tsv",
    "library_catalog": "library_catalog.yml",
    "library_versions": "library_versions.tsv",
}

CONTROL_CONFIG_SPECS = [
    ("catalog_policy", DEFAULT_CATALOG_POLICY_PATH, True, ["catalog", "discovery"], ["catalog refresh"]),
    ("release_policy", DEFAULT_RELEASE_POLICY_PATH, True, ["release_check"], ["release check"]),
]

SUMMARY_ONLY_TYPES = {"verilog", "systemverilog", "liberty", "lib", "spef"}
BINARY_METADATA_ONLY_TYPES = {"db", "gds", "oas", "layout", "milkyway", "ndm"}
DEFAULT_FILE_DIFF_TYPES = {
    "lef",
    "cdl",
    "spice",
    "sp",
    "sdc",
    "upf",
    "cpf",
    "waiver",
    "ibis",
    "pwl",
    "snp",
    "touchstone",
    "cpm",
}


def workspace_path(workspace: str | Path, relative_path: str) -> str:
    return str(Path(workspace) / relative_path)


def workspace_config_dir(workspace: str | Path, config_dir: str | Path | None = None) -> Path:
    if config_dir is None:
        return Path(workspace) / WORKSPACE_CONFIG_DIR
    path = Path(config_dir)
    return path if path.is_absolute() else Path(workspace) / path


def workspace_config_file_defaults(workspace: str | Path, config_dir: str | Path | None = None) -> dict[str, str]:
    root = workspace_config_dir(workspace, config_dir)
    defaults = {"config_dir": str(root)}
    defaults.update({key: str(root / relpath) for key, relpath in WORKSPACE_CONFIG_FILE_DEFAULTS.items()})
    defaults["versions"] = defaults["library_versions"]
    return defaults


def workspace_defaults(
    workspace: str | Path,
    *,
    raw_root: str | Path | None = None,
    library_type: str = DEFAULT_LIBRARY_TYPE,
) -> dict[str, str]:
    root = Path(workspace)
    defaults = {
        key: workspace_path(root, relpath)
        for key, relpath in WORKSPACE_PATH_DEFAULTS.items()
        if key not in WORKSPACE_CONFIG_FILE_DEFAULTS and key not in {"config_dir"}
    }
    defaults.update(workspace_config_file_defaults(root))
    if raw_root is not None:
        defaults["raw_root"] = str(Path(raw_root))
    defaults["workspace"] = str(root)
    defaults["library_type"] = library_type
    defaults["mode"] = DEFAULT_SCAN_MODE
    defaults["parse_jobs"] = DEFAULT_PARSE_JOBS
    return defaults


def project_policy_path(project_root: str | Path | None, filename: str) -> Path | None:
    if not project_root:
        return None
    return Path(project_root) / PROJECT_CONFIG_DIR / filename
