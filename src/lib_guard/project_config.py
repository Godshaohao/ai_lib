from __future__ import annotations

from pathlib import Path


CONFIG_NAME = "lib_guard.yml"
PROJECT_CONFIG_DIR = "configs"
WORKSPACE_CONFIG_DIR = "config"

DEFAULT_LIBRARY_TYPE = "ip"
DEFAULT_SCAN_MODE = "candidate"
DEFAULT_PARSE_JOBS = "8"

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
    "library_catalog": f"{WORKSPACE_CONFIG_DIR}/library_catalog.yml",
    "library_versions": f"{WORKSPACE_CONFIG_DIR}/library_versions.tsv",
    "actions_dir": "actions",
}

CONTROL_CONFIG_SPECS = [
    ("catalog_policy", DEFAULT_CATALOG_POLICY_PATH, True, ["catalog", "discovery"], ["catalog scan"]),
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
    }
    if raw_root is not None:
        defaults["raw_root"] = str(Path(raw_root))
    defaults["workspace"] = str(root)
    defaults["versions"] = defaults["library_versions"]
    defaults["library_type"] = library_type
    defaults["mode"] = DEFAULT_SCAN_MODE
    defaults["parse_jobs"] = DEFAULT_PARSE_JOBS
    return defaults


def project_policy_path(project_root: str | Path | None, filename: str) -> Path | None:
    if not project_root:
        return None
    return Path(project_root) / PROJECT_CONFIG_DIR / filename
