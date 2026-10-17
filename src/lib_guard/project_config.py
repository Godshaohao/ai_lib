from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


CONFIG_NAME = "lib_guard.yml"
WORKSPACE_CONFIG_SCHEMA_VERSION = "lib_guard_config.v1"
PROJECT_CONFIG_DIR = "configs"
WORKSPACE_CONFIG_DIR = "config"

DEFAULT_LIBRARY_TYPE = "ip"
DEFAULT_SCAN_MODE = "scan"
DEFAULT_PARSE_JOBS = "8"
DEFAULT_HASH_POLICY = "smart"
DEFAULT_RENDER_DETAIL = "true"
HASH_POLICIES = frozenset({"none", "smart", "full"})
MIN_PARSE_JOBS = 1
MAX_PARSE_JOBS = 32
SCAN_STRATEGY_CONFIG_KEYS = (
    "hash_policy",
    "force_hash_file_types",
    "skip_hash_file_types",
    "parse_file_types",
    "parse_exclude_file_types",
)
DEFAULT_DISCOVER_MAX_DEPTH = "4"
DEFAULT_DISCOVER_MIN_VERSIONS = "1"
DEFAULT_DISCOVER_MAX_DIRS = "5000"
DEFAULT_DISCOVER_MAX_CANDIDATES = "200"
DISCOVERY_CONFIG_KEYS = (
    "discover_max_depth",
    "discover_min_versions",
    "discover_max_dirs",
    "discover_max_candidates",
)

WEB_COMPARE_MODES = frozenset({"adjacent", "cumulative"})
WEB_MARK_TYPES = frozenset({"FULL", "FIX", "HOTFIX", "UNKNOWN"})
WEB_PACKAGE_TYPES = frozenset({"FULL_PACKAGE", "PARTIAL_UPDATE", "HOTFIX", "DOC_UPDATE", "UNKNOWN_PACKAGE"})
WEB_COMPARE_DEFAULTS = frozenset({"previous_effective", "full_baseline", "none"})
WEB_STAGES = frozenset({"initial", "stable", "final", "ad-hoc", "dated", "unknown"})
WEB_RELEASE_ALIASES = frozenset({"current", "stage", "approved"})
WEB_RELEASE_LINK_MODES = frozenset({"symlink", "copy"})

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
    "release_library_index": f"{WORKSPACE_CONFIG_DIR}/release_libraries/latest.json",
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
    "release_library_index": "release_libraries/latest.json",
}

CONTROL_CONFIG_SPECS = [
    ("catalog_policy", DEFAULT_CATALOG_POLICY_PATH, True, ["catalog", "discovery"], ["catalog refresh"]),
    ("release_policy", DEFAULT_RELEASE_POLICY_PATH, True, ["release_check"], ["release check"]),
]

@dataclass(frozen=True)
class ViewTypeSpec:
    """One explicit capability record shared by scan, diff, release and UI."""

    canonical_type: str
    evidence_mode: str
    aliases: tuple[str, ...] = ()
    default_file_diff: bool = False


@dataclass(frozen=True)
class WebActionSpec:
    """One allowlisted Web action mapped to the short CLI command surface."""

    scope: str
    cli_action: str
    label: str = ""
    requires_confirmation: bool = False
    confirmation: str = ""


WEB_ACTION_SPECS = {
    "catalog-refresh": WebActionSpec("library", "cat", "目录刷新", True, "即将刷新当前库的 Catalog 投影，可能覆盖该库的目录 HTML。是否继续？"),
    "worklist": WebActionSpec("workspace", "worklist", "工作清单"),
    "library-discover": WebActionSpec("workspace", "library", "候选库发现"),
    "library-accept": WebActionSpec("workspace", "library", "候选库登记合并", True),
    "library-apply": WebActionSpec("workspace", "library", "应用并刷新目录", True),
    "library-add": WebActionSpec("workspace", "library", "手工库登记", True, "即将登记库并刷新目录；同名库将更新原有库根。不会扫描或切换当前有效组合。是否继续？"),
    "scan": WebActionSpec("version", "scan", "扫描"),
    "cmp": WebActionSpec("version", "cmp", "对比"),
    "rel": WebActionSpec("version", "rel", "发布检查"),
    "release-plan": WebActionSpec("version", "rel", "发布预演"),
    "release-apply": WebActionSpec("version", "rel", "实际发布", True, "即将创建发布链接并切换发布别名。底层会检查门禁并校验链接，未通过则不发布。是否继续？"),
    "release-set-plan": WebActionSpec("workspace", "release-set", "多库发布预演"),
    "release-set-apply": WebActionSpec("workspace", "release-set", "多库实际发布", True),
    "release-overwrite-preview": WebActionSpec("version", "rel", "正式库覆盖预演"),
    "release-force": WebActionSpec("version", "rel", "受控强制发布", True, "即将覆盖正式发布链接并写入强制发布审计。底层仍会执行发布校验。是否继续？"),
    "next": WebActionSpec("library", "next", "处理建议"),
    "intake": WebActionSpec("library", "intake", "处理计划"),
    "window": WebActionSpec("library", "window", "接入建议"),
    "accept-window": WebActionSpec("library", "accept-window", "确认当前可用版本", True),
    "mark": WebActionSpec("version", "mark", "版本类型标记", True),
    "override": WebActionSpec("version", "override", "目录修正", True),
    "file-diff": WebActionSpec("version", "fd", "文件级对比"),
    "semantic-review": WebActionSpec("library", "semantic-review", "生成技术检查报告"),
    "review-gate": WebActionSpec("version", "rv", "审查门禁"),
    "review-packet": WebActionSpec("version", "review", "审查记录包"),
    "action-file": WebActionSpec("library", "action", "动作文件", True),
    "effective-rollback": WebActionSpec("library", "effective", "当前可用版本回退", True, "即将回退当前可用版本，此操作会写入状态和审计记录。是否继续？"),
}
WEB_MUTATING_ACTIONS = frozenset(WEB_ACTION_SPECS)


def web_action_catalog() -> dict[str, dict[str, str | bool]]:
    """Serialize the Web action surface for the API and browser console."""

    return {
        key: {
            "scope": spec.scope,
            "cli_action": spec.cli_action,
            "label": spec.label or key,
            "requires_confirmation": spec.requires_confirmation,
            "confirmation": spec.confirmation,
        }
        for key, spec in WEB_ACTION_SPECS.items()
    }


VIEW_TYPE_SPECS = {
    spec.canonical_type: spec
    for spec in (
        ViewTypeSpec("verilog", "summary"),
        ViewTypeSpec("systemverilog", "summary"),
        ViewTypeSpec("liberty", "summary", aliases=("lib",)),
        ViewTypeSpec("spef", "summary"),
        ViewTypeSpec("db", "metadata"),
        ViewTypeSpec("gds", "metadata"),
        ViewTypeSpec("oas", "metadata"),
        ViewTypeSpec("layout", "metadata"),
        ViewTypeSpec("milkyway", "metadata"),
        ViewTypeSpec("ndm", "metadata"),
        ViewTypeSpec("lef", "parsed", default_file_diff=True),
        ViewTypeSpec("cdl", "parsed", default_file_diff=True),
        ViewTypeSpec("spice", "parsed", aliases=("sp",), default_file_diff=True),
        ViewTypeSpec("sdc", "parsed", default_file_diff=True),
        ViewTypeSpec("upf", "parsed", default_file_diff=True),
        ViewTypeSpec("cpf", "parsed", default_file_diff=True),
        ViewTypeSpec("waiver", "parsed", default_file_diff=True),
        ViewTypeSpec("ibis", "parsed", default_file_diff=True),
        ViewTypeSpec("pwl", "parsed", default_file_diff=True),
        ViewTypeSpec("touchstone", "parsed", aliases=("snp",), default_file_diff=True),
        ViewTypeSpec("cpm", "parsed", default_file_diff=True),
    )
}

_VIEW_TYPE_BY_NAME = {
    name: spec
    for spec in VIEW_TYPE_SPECS.values()
    for name in (spec.canonical_type, *spec.aliases)
}


def view_type_spec(file_type: str) -> ViewTypeSpec | None:
    return _VIEW_TYPE_BY_NAME.get(str(file_type or "").strip().lower())


def canonical_view_type(file_type: str) -> str:
    key = str(file_type or "").strip().lower()
    spec = view_type_spec(key)
    return spec.canonical_type if spec else key


def file_diff_allowed(file_type: str) -> bool:
    spec = view_type_spec(file_type)
    return bool(spec and (spec.default_file_diff or spec.evidence_mode in {"summary", "metadata"}))


def file_diff_requires_force_large(file_type: str) -> bool:
    spec = view_type_spec(file_type)
    return bool(spec and spec.evidence_mode in {"summary", "metadata"})


def _view_names(*, evidence_mode: str | None = None, default_file_diff: bool | None = None) -> set[str]:
    result: set[str] = set()
    for spec in VIEW_TYPE_SPECS.values():
        if evidence_mode is not None and spec.evidence_mode != evidence_mode:
            continue
        if default_file_diff is not None and spec.default_file_diff != default_file_diff:
            continue
        result.update((spec.canonical_type, *spec.aliases))
    return result


# Compatibility exports. Their values are derived from VIEW_TYPE_SPECS so all
# existing scan/diff/render callers continue to consume one source of truth.
SUMMARY_ONLY_TYPES = _view_names(evidence_mode="summary")
BINARY_METADATA_ONLY_TYPES = _view_names(evidence_mode="metadata")
DEFAULT_FILE_DIFF_TYPES = _view_names(default_file_diff=True)


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
    defaults["config_version"] = WORKSPACE_CONFIG_SCHEMA_VERSION
    defaults["library_type"] = library_type
    defaults["mode"] = DEFAULT_SCAN_MODE
    defaults["parse_jobs"] = DEFAULT_PARSE_JOBS
    defaults["hash_policy"] = DEFAULT_HASH_POLICY
    defaults["force_hash_file_types"] = ""
    defaults["skip_hash_file_types"] = ""
    defaults["parse_file_types"] = ""
    defaults["parse_exclude_file_types"] = ""
    defaults["render_detail"] = DEFAULT_RENDER_DETAIL
    defaults["discover_max_depth"] = DEFAULT_DISCOVER_MAX_DEPTH
    defaults["discover_min_versions"] = DEFAULT_DISCOVER_MIN_VERSIONS
    defaults["discover_max_dirs"] = DEFAULT_DISCOVER_MAX_DIRS
    defaults["discover_max_candidates"] = DEFAULT_DISCOVER_MAX_CANDIDATES
    return defaults


def default_scan_strategy() -> dict[str, str]:
    """Return default scan strategy values in the same shape as lib_guard.yml."""

    return {
        "hash_policy": DEFAULT_HASH_POLICY,
        "parse_jobs": DEFAULT_PARSE_JOBS,
        "force_hash_file_types": "",
        "skip_hash_file_types": "",
        "parse_file_types": "",
        "parse_exclude_file_types": "",
        "render_detail": DEFAULT_RENDER_DETAIL,
    }


def default_discovery_strategy() -> dict[str, str]:
    """Return default library-discovery strategy values in config-file form."""

    return {
        "max_depth": DEFAULT_DISCOVER_MAX_DEPTH,
        "min_versions": DEFAULT_DISCOVER_MIN_VERSIONS,
        "max_dirs": DEFAULT_DISCOVER_MAX_DIRS,
        "max_candidates": DEFAULT_DISCOVER_MAX_CANDIDATES,
    }


def project_policy_path(project_root: str | Path | None, filename: str) -> Path | None:
    if not project_root:
        return None
    return Path(project_root) / PROJECT_CONFIG_DIR / filename
