"""
lib_guard CLI v5.

Commands:
- scan
- history list/latest
- render
- release check/link
- update file/type
- catalog scan/compare/release
- file-diff

This CLI keeps scan, render, release, update, catalog, and diff boundaries explicit.
"""

from __future__ import annotations

from argparse import ArgumentParser, Namespace
from typing import Any
import importlib
import logging
import sys


LOGGER = logging.getLogger("lib_guard")


def _lazy_command(module_name: str, function_name: str):
    """Import command handlers only when that subcommand is executed."""

    def _run(args: Namespace) -> int:
        try:
            module = importlib.import_module(module_name)
        except ModuleNotFoundError as exc:
            if exc.name == module_name:
                raise ModuleNotFoundError(
                    f"Command handler module is missing: {module_name}. "
                    f"Restore or install it before running {function_name}."
                ) from exc
            raise
        return int(getattr(module, function_name)(args))

    _run.__name__ = function_name
    return _run


run_catalog_batch = _lazy_command("lib_guard.cli_commands.catalog", "run_catalog_batch")
run_catalog_compare = _lazy_command("lib_guard.cli_commands.catalog", "run_catalog_compare")
run_catalog_compare_batch = _lazy_command("lib_guard.cli_commands.catalog", "run_catalog_compare_batch")
run_catalog_list = _lazy_command("lib_guard.cli_commands.catalog", "run_catalog_list")
run_catalog_override = _lazy_command("lib_guard.cli_commands.catalog", "run_catalog_override")
run_catalog_release_batch = _lazy_command("lib_guard.cli_commands.catalog", "run_catalog_release_batch")
run_catalog_release_check = _lazy_command("lib_guard.cli_commands.catalog", "run_catalog_release_check")
run_catalog_release_link = _lazy_command("lib_guard.cli_commands.catalog", "run_catalog_release_link")
run_catalog_render = _lazy_command("lib_guard.cli_commands.catalog", "run_catalog_render")
run_catalog_scan = _lazy_command("lib_guard.cli_commands.catalog", "run_catalog_scan")
run_catalog_workflow = _lazy_command("lib_guard.cli_commands.catalog", "run_catalog_workflow")
run_library_discover = _lazy_command("lib_guard.cli_commands.library", "run_library_discover")
run_library_apply = _lazy_command("lib_guard.cli_commands.library", "run_library_apply")
run_console_build = _lazy_command("lib_guard.cli_commands.console", "run_console_build")
run_console_config = _lazy_command("lib_guard.cli_commands.console", "run_console_config")
run_console_review = _lazy_command("lib_guard.cli_commands.console", "run_console_review")
run_diff_adjacent = _lazy_command("lib_guard.cli_commands.diff", "run_diff_adjacent")
run_diff_cumulative = _lazy_command("lib_guard.cli_commands.diff", "run_diff_cumulative")
run_diff_render = _lazy_command("lib_guard.cli_commands.diff", "run_diff_render")
run_diff_scan = _lazy_command("lib_guard.cli_commands.diff", "run_diff_scan")
run_file_diff = _lazy_command("lib_guard.cli_commands.diff", "run_file_diff")
run_history_latest = _lazy_command("lib_guard.cli_commands.history", "run_history_latest")
run_history_list = _lazy_command("lib_guard.cli_commands.history", "run_history_list")
run_package_assemble = _lazy_command("lib_guard.cli_commands.package", "run_package_assemble")
run_package_attach = _lazy_command("lib_guard.cli_commands.package", "run_package_attach")
run_package_classify = _lazy_command("lib_guard.cli_commands.package", "run_package_classify")
run_release_check = _lazy_command("lib_guard.cli_commands.release", "run_release_check")
run_release_link = _lazy_command("lib_guard.cli_commands.release", "run_release_link")
run_release_manifest_from_snapshot = _lazy_command("lib_guard.cli_commands.release", "run_release_manifest_from_snapshot")
run_release_manifest_template = _lazy_command("lib_guard.cli_commands.release", "run_release_manifest_template")
run_release_verify = _lazy_command("lib_guard.cli_commands.release", "run_release_verify")
run_render_command = _lazy_command("lib_guard.cli_commands.render", "run_render_command")
run_scan_command = _lazy_command("lib_guard.cli_commands.scan", "run_scan_command")
run_scan_status = _lazy_command("lib_guard.cli_commands.scan", "run_scan_status")
run_update_file = _lazy_command("lib_guard.cli_commands.update", "run_update_file")
run_update_type = _lazy_command("lib_guard.cli_commands.update", "run_update_type")
run_version_list = _lazy_command("lib_guard.cli_commands.version", "run_version_list")
run_version_register = _lazy_command("lib_guard.cli_commands.version", "run_version_register")


def build_scan_status(*args: Any, **kwargs: Any) -> Any:
    from lib_guard.cli_commands.scan import build_scan_status as _build_scan_status

    return _build_scan_status(*args, **kwargs)


def setup_logging(verbose: int = 0) -> None:
    level = logging.WARNING
    if verbose == 1:
        level = logging.INFO
    elif verbose >= 2:
        level = logging.DEBUG
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s")


def add_scan_parser(subparsers: Any) -> None:
    p = subparsers.add_parser("scan", help="Scan raw library")
    p.add_argument("--root", required=True)
    p.add_argument("--profile", required=True, help="Library type/profile, e.g. ip/stdcell/sram")
    p.add_argument("--name", required=True, help="Library name")
    p.add_argument("--version", dest="version", required=True, help="Library version")
    p.add_argument("--mode", default="inventory", choices=["quick", "inventory", "signature", "candidate", "release", "diff", "refresh", "full"])
    p.add_argument("--out")
    p.add_argument("--out-template")
    p.add_argument("--workdir", default="work")
    p.add_argument("--state-dir")
    p.add_argument("--cache-dir")
    p.add_argument("--config")
    p.add_argument("--scan-id")
    p.add_argument("--progress-interval", type=int, default=50)
    p.add_argument("--no-progress", action="store_true")
    p.add_argument("--console-progress", dest="console_progress", action="store_true", default=None, help="Force single-line console progress on stderr")
    p.add_argument("--no-console-progress", dest="console_progress", action="store_false", help="Disable single-line console progress")
    p.add_argument("--parse-jobs", type=int, default=8, help="Parser worker count. Values greater than 1 enable the thread-based ParserExecutor.")
    p.add_argument("--skip-cache", action="store_true", help="Do not read parser cache; parsed results may still be written")
    p.add_argument("--no-cache", action="store_true", help="Do not read or write parser cache")
    p.add_argument("--register-history", action="store_true", default=True)
    p.add_argument("--no-register-history", dest="register_history", action="store_false")
    p.add_argument("--update-latest", action="store_true", default=True)
    p.add_argument("--no-update-latest", dest="update_latest", action="store_false")
    p.add_argument("--render", action="store_true")
    p.add_argument("--html-out")
    p.set_defaults(func=run_scan_command)


def add_scan_status_parser(subparsers: Any) -> None:
    p = subparsers.add_parser("scan-status", help="Show live or finished scan status")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--scan")
    src.add_argument("--latest", action="store_true")
    p.add_argument("--library-id")
    p.add_argument("--mode", default="signature")
    p.add_argument("--workdir", default="work")
    p.set_defaults(func=run_scan_status)


def add_history_parser(subparsers: Any) -> None:
    root = subparsers.add_parser("history", help="Scan history operations")
    sp = root.add_subparsers(dest="history_cmd", required=True)
    p = sp.add_parser("list")
    p.add_argument("--library-id")
    p.add_argument("--workdir", default="work")
    p.set_defaults(func=run_history_list)
    p = sp.add_parser("latest")
    p.add_argument("--library-id", required=True)
    p.add_argument("--mode")
    p.add_argument("--kind")
    p.add_argument("--workdir", default="work")
    p.set_defaults(func=run_history_latest)


def add_render_parser(subparsers: Any) -> None:
    p = subparsers.add_parser("render", help="Render HTML report from scan output")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--scan")
    src.add_argument("--latest", action="store_true")
    p.add_argument("--library-id")
    p.add_argument("--mode", default="signature")
    p.add_argument("--workdir", default="work")
    p.add_argument("--out")
    p.set_defaults(func=run_render_command)


def add_release_parser(subparsers: Any) -> None:
    root = subparsers.add_parser("release", help="Release operations")
    sp = root.add_subparsers(dest="release_cmd", required=True)
    for name, fn in [("check", run_release_check), ("link", run_release_link)]:
        p = sp.add_parser(name)
        src = p.add_mutually_exclusive_group(required=True)
        src.add_argument("--scan")
        src.add_argument("--latest", action="store_true")
        if name == "link":
            src.add_argument("--manifest", help="Manifest-driven release_manifest.json. This path does not run a pre-release gate.")
        p.add_argument("--library-id")
        p.add_argument("--mode", default="signature")
        p.add_argument("--workdir", default="work")
        p.add_argument("--policy", default="configs/release_policy.json")
        if name == "link":
            p.add_argument("--release-root", help="Required for --scan; optional override for --manifest.")
            p.add_argument("--alias", default="current")
            p.add_argument("--apply", action="store_true", help="Actually apply release links. Default is dry-run.")
            p.add_argument("--overwrite", action="store_true", help="Allow replacing an existing release version directory.")
            p.add_argument("--link-mode", default="symlink", choices=["symlink", "copy"], help="Manifest release filesystem mode.")
            p.add_argument("--force", action="store_true", help="Force release even when release check is BLOCK/FAILED; requires --apply and --force-reason.")
            p.add_argument("--force-reason", help="Audit reason for forced release.")
            p.add_argument("--diff", help="Optional diff_output directory used as an alias gate")
        else:
            p.add_argument("--diff", help="Optional diff_output directory used as a release gate")
            p.add_argument("--register-history", action="store_true", default=True)
        p.set_defaults(func=fn)

    p = sp.add_parser("manifest-template", help="Create a human-editable release_manifest.json from catalog selections")
    p.add_argument("--catalog", required=True)
    p.add_argument("--release-root", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--alias", default="current")
    p.add_argument("--release-id")
    p.add_argument("--library")
    p.add_argument("--version", action="append", default=[], help="Version id or version_key. Repeat to select multiple versions.")
    p.add_argument("--stage", choices=["initial", "stable", "final", "ad-hoc", "dated", "unknown"])
    p.add_argument("--created-by")
    p.set_defaults(func=run_release_manifest_template)

    p = sp.add_parser("verify", help="Post-release manifest verification and optional Release HTML rendering")
    p.add_argument("--manifest", required=True)
    p.add_argument("--link-result")
    p.add_argument("--out")
    p.add_argument("--render", action="store_true")
    p.add_argument("--html-out")
    p.set_defaults(func=run_release_verify)

    p = sp.add_parser("manifest", help="Create release_manifest.json from an assembled snapshot")
    p.add_argument("--snapshot", required=True)
    p.add_argument("--release-root", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--alias", default="current")
    p.add_argument("--release-id")
    p.add_argument("--created-by")
    p.set_defaults(func=run_release_manifest_from_snapshot)


def add_update_parser(subparsers: Any) -> None:
    root = subparsers.add_parser("update", help="Safe incremental update operations")
    sp = root.add_subparsers(dest="update_cmd", required=True)
    p = sp.add_parser("file")
    p.add_argument("--library-id", required=True)
    p.add_argument("--file", required=True)
    p.add_argument("--mode", default="signature")
    p.add_argument("--scope", default="summary", choices=["parser", "summary", "parser-summary", "all"])
    p.add_argument("--workdir", default="work")
    p.add_argument("--policy", default="configs/summary_policy.json")
    p.add_argument("--no-rebuild-summary", action="store_true")
    p.set_defaults(func=run_update_file)

    p = sp.add_parser("type")
    p.add_argument("--library-id", required=True)
    p.add_argument("--type", required=True)
    p.add_argument("--mode", default="signature")
    p.add_argument("--scope", default="summary", choices=["parser", "summary", "parser-summary", "all"])
    p.add_argument("--workdir", default="work")
    p.add_argument("--policy", default="configs/summary_policy.json")
    p.add_argument("--skip-cache", action="store_true")
    p.add_argument("--no-rebuild-summary", action="store_true")
    p.set_defaults(func=run_update_type)


def add_package_parser(subparsers: Any) -> None:
    root = subparsers.add_parser("package", help="Delivery package classification, base binding, and snapshot assembly")
    sp = root.add_subparsers(dest="package_cmd", required=True)

    p = sp.add_parser("classify", help="Classify a raw delivery package as full, partial, doc update, or unknown")
    p.add_argument("--root", required=True)
    p.add_argument("--library-type", default="ip")
    p.add_argument("--catalog")
    p.add_argument("--render", action="store_true")
    p.add_argument("--out")
    p.set_defaults(func=run_package_classify)

    p = sp.add_parser("attach", help="Attach a partial package to a base package in catalog.json")
    p.add_argument("--catalog", required=True)
    p.add_argument("--package", required=True, help="version_key or version_id for the partial package")
    p.add_argument("--base", required=True, help="base package version_id or version_key")
    p.add_argument("--updated-by")
    p.set_defaults(func=run_package_attach)

    p = sp.add_parser("assemble", help="Assemble base + updates into snapshot JSON")
    p.add_argument("--catalog", required=True)
    p.add_argument("--library", required=True)
    p.add_argument("--base", required=True)
    p.add_argument("--update", action="append", default=[])
    p.add_argument("--out", required=True)
    p.add_argument("--snapshot-id")
    p.add_argument("--render", action="store_true")
    p.add_argument("--html-out")
    p.set_defaults(func=run_package_assemble)


def add_console_parser(subparsers: Any) -> None:
    root = subparsers.add_parser("console", help="Build v5 HTML control console and review data")
    sp = root.add_subparsers(dest="console_cmd", required=True)

    p = sp.add_parser("build", help="Build HTML console from scan output")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--scan")
    src.add_argument("--latest", action="store_true")
    p.add_argument("--library-id")
    p.add_argument("--mode", default="signature")
    p.add_argument("--workdir", default="work")
    p.add_argument("--config-dir", default="configs")
    p.add_argument("--out")
    p.set_defaults(func=run_console_build)

    p = sp.add_parser("config", help="Export merged user-facing config view")
    p.add_argument("--library-id")
    p.add_argument("--workdir", default="work")
    p.add_argument("--config-dir", default="configs")
    p.add_argument("--out", required=True)
    p.set_defaults(func=run_console_config)

    p = sp.add_parser("review", help="Export manual review items")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--scan")
    src.add_argument("--latest", action="store_true")
    p.add_argument("--library-id")
    p.add_argument("--mode", default="signature")
    p.add_argument("--workdir", default="work")
    p.add_argument("--config-dir", default="configs")
    p.add_argument("--out", required=True)
    p.set_defaults(func=run_console_review)


def add_diff_parser(subparsers: Any) -> None:
    root = subparsers.add_parser("diff", help="Diff scan outputs")
    sp = root.add_subparsers(dest="diff_cmd", required=True)
    p = sp.add_parser("scan", help="Compare two scan output directories")
    p.add_argument("--old", required=True)
    p.add_argument("--new", required=True)
    p.add_argument("--out")
    p.add_argument("--diff-mode", default="explicit", choices=["explicit", "adjacent", "cumulative"])
    p.add_argument("--old-version-type", choices=["full", "hotfix", "candidate", "daily"])
    p.add_argument("--new-version-type", choices=["full", "hotfix", "candidate", "daily"])
    p.add_argument("--release-line")
    p.add_argument("--parent-version")
    p.add_argument("--base-version")
    p.set_defaults(func=run_diff_scan)

    p = sp.add_parser("adjacent", help="Compare a version against its parent_version from version index")
    p.add_argument("--library-id", required=True)
    p.add_argument("--new-version", required=True)
    p.add_argument("--workdir", default="work")
    p.add_argument("--out")
    p.add_argument("--scan-if-missing", action="store_true", help="Reserved for future scan-on-demand support")
    p.set_defaults(func=run_diff_adjacent)

    p = sp.add_parser("cumulative", help="Compare a version against its base_version from version index")
    p.add_argument("--library-id", required=True)
    p.add_argument("--new-version", required=True)
    p.add_argument("--workdir", default="work")
    p.add_argument("--out")
    p.add_argument("--scan-if-missing", action="store_true", help="Reserved for future scan-on-demand support")
    p.set_defaults(func=run_diff_cumulative)

    p = sp.add_parser("render", help="Render a diff_output directory into an HTML report")
    p.add_argument("--diff", required=True, help="diff_output directory produced by diff scan/adjacent/cumulative")
    p.add_argument("--out", required=True, help="Output directory for HTML assets")
    p.set_defaults(func=run_diff_render)


def add_file_diff_parser(subparsers: Any) -> None:
    root = subparsers.add_parser("file-diff", help="Run explicit pairwise file diff")
    sp = root.add_subparsers(dest="file_type", required=True)
    for file_type in ["lef", "liberty", "verilog", "cdl", "sdc", "upf", "cpf", "spef", "db"]:
        p = sp.add_parser(file_type, help=f"Compare two {file_type} files")
        p.add_argument("--old", required=True)
        p.add_argument("--new", required=True)
        p.add_argument("--out", required=True)
        p.add_argument("--task-id")
        p.add_argument("--library-id")
        p.add_argument("--version-id")
        p.add_argument("--base-version")
        p.set_defaults(func=run_file_diff)


def add_library_parser(subparsers: Any) -> None:
    root = subparsers.add_parser("library", help="Library registry discovery and apply")
    sp = root.add_subparsers(dest="library_cmd", required=True)

    p = sp.add_parser("discover", help="Discover candidate library roots from RAW")
    p.add_argument("--root", required=True)
    p.add_argument("--out", required=True, help="Editable library.list output")
    p.add_argument("--json-out", help="Machine discovery evidence JSON")
    p.add_argument("--html-out", help="Discovery review HTML")
    p.add_argument("--max-depth", type=int, default=8)
    p.add_argument("--min-versions", type=int, default=2)
    p.add_argument("--default-status", choices=["REVIEW", "OK"], default="REVIEW")
    p.set_defaults(func=run_library_discover)

    p = sp.add_parser("apply", help="Convert confirmed library.list into library_catalog.yml")
    p.add_argument("--root", required=True)
    p.add_argument("--input", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--library-type", default="ip")
    p.set_defaults(func=run_library_apply)


def add_catalog_parser(subparsers: Any) -> None:
    root = subparsers.add_parser("catalog", help="Discover raw library assets and render catalog HTML")
    sp = root.add_subparsers(dest="catalog_cmd", required=True)

    p = sp.add_parser("scan", help="Discover libraries and versions from a raw root")
    p.add_argument("--root", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--library-type", default="ip")
    p.add_argument("--library", help="Refresh only this library in the catalog; keeps previous catalog entries for other libraries.")
    p.add_argument("--full", action="store_true", help="Force a full catalog refresh and ignore catalog_state.json.")
    p.add_argument("--fast", action="store_true", help="Directory-only discovery; do not recurse into version directories for file-type evidence.")
    p.add_argument("--with-evidence", action="store_true", help="Collect lightweight file-type evidence during catalog discovery; slower on large RAW trees.")
    p.add_argument("--policy")
    p.add_argument("--render", action="store_true", help="Also render Chinese catalog HTML")
    p.add_argument("--html-out")
    p.set_defaults(func=run_catalog_scan)

    p = sp.add_parser("list", help="List libraries or versions in a catalog")
    p.add_argument("--catalog", required=True)
    p.add_argument("--library")
    p.add_argument("--versions", action="store_true")
    p.set_defaults(func=run_catalog_list)

    p = sp.add_parser("render", help="Render catalog.json into Chinese HTML")
    p.add_argument("--catalog", required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(func=run_catalog_render)

    p = sp.add_parser("override", help="Apply a manual catalog correction")
    p.add_argument("--catalog", required=True)
    p.add_argument("--version", required=True, help="version_key, e.g. ip/ucie/stable_20250608")
    p.add_argument("--stage", choices=["initial", "stable", "final", "ad-hoc", "dated", "unknown"])
    p.add_argument("--parent")
    p.add_argument("--base")
    p.add_argument("--release-line")
    p.add_argument("--display-name")
    p.add_argument("--manual-review", action="store_true", default=None)
    p.add_argument("--note")
    p.add_argument("--updated-by")
    p.set_defaults(func=run_catalog_override)

    p = sp.add_parser("release-check", help="Run release check from a catalog version")
    p.add_argument("--catalog", required=True)
    p.add_argument("--library", required=True)
    p.add_argument("--version", required=True)
    p.add_argument("--policy", default="configs/release_policy.json")
    p.add_argument("--diff")
    p.add_argument("--diff-mode", choices=["adjacent", "cumulative"])
    p.set_defaults(func=run_catalog_release_check)

    p = sp.add_parser("release-link", help="Run release link dry-run/apply from a catalog version")
    p.add_argument("--catalog", required=True)
    p.add_argument("--library", required=True)
    p.add_argument("--version", required=True)
    p.add_argument("--policy", default="configs/release_policy.json")
    p.add_argument("--release-root", required=True)
    p.add_argument("--alias", default="current")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--link-mode", default="symlink", choices=["symlink", "copy"])
    p.add_argument("--force", action="store_true")
    p.add_argument("--force-reason")
    p.add_argument("--diff")
    p.add_argument("--diff-mode", choices=["adjacent", "cumulative"])
    p.set_defaults(func=run_catalog_release_link)


def add_workflow_parsers(subparsers: Any) -> None:
    p = subparsers.add_parser("run", help="Run catalog-driven scan + HTML from a catalog version")
    p.add_argument("--catalog", required=True)
    p.add_argument("--library", required=True)
    p.add_argument("--version", required=True)
    p.add_argument("--mode", default="signature", choices=["quick", "inventory", "signature", "candidate", "release", "diff", "refresh", "full"])
    p.add_argument("--workdir", default="work")
    p.add_argument("--out")
    p.add_argument("--html-out")
    p.add_argument("--console-out")
    p.add_argument("--catalog-html-out")
    p.add_argument("--no-catalog-render", action="store_true")
    p.add_argument("--config-dir", default="configs")
    p.add_argument("--state-dir")
    p.add_argument("--cache-dir")
    p.add_argument("--config")
    p.add_argument("--scan-id")
    p.add_argument("--progress-interval", type=int, default=50)
    p.add_argument("--no-progress", action="store_true")
    p.add_argument("--console-progress", dest="console_progress", action="store_true", default=None)
    p.add_argument("--no-console-progress", dest="console_progress", action="store_false")
    p.add_argument("--parse-jobs", type=int, default=8)
    p.add_argument("--skip-cache", action="store_true")
    p.add_argument("--no-cache", action="store_true")
    p.set_defaults(func=run_catalog_workflow)

    p = subparsers.add_parser("compare", help="Run catalog-driven diff + diff HTML")
    p.add_argument("--catalog", required=True)
    p.add_argument("--library", required=True)
    p.add_argument("--new", required=True)
    p.add_argument("--mode", default="adjacent", choices=["adjacent", "cumulative"])
    p.add_argument("--base", help="Explicit old/base version for this comparison")
    p.add_argument("--workdir", default="work")
    p.add_argument("--out")
    p.add_argument("--html-out")
    p.add_argument("--catalog-html-out")
    p.add_argument("--no-catalog-render", action="store_true")
    p.add_argument("--scan-if-missing", action="store_true", help="Scan only missing old/new scan evidence before compare")
    p.add_argument("--rescan", action="store_true", help="Force rescan of old and new versions before compare")
    p.add_argument("--scan-mode", default="signature", choices=["quick", "inventory", "signature", "candidate", "release", "diff", "refresh", "full"])
    p.add_argument("--config-dir", default="configs")
    p.add_argument("--state-dir")
    p.add_argument("--cache-dir")
    p.add_argument("--config")
    p.add_argument("--progress-interval", type=int, default=50)
    p.add_argument("--no-progress", action="store_true")
    p.add_argument("--console-progress", dest="console_progress", action="store_true", default=None)
    p.add_argument("--no-console-progress", dest="console_progress", action="store_false")
    p.add_argument("--parse-jobs", type=int, default=8)
    p.add_argument("--skip-cache", action="store_true")
    p.add_argument("--no-cache", action="store_true")
    p.set_defaults(func=run_catalog_compare)

    p = subparsers.add_parser("run-batch", help="Run catalog-driven scan workflow for many versions")
    p.add_argument("--catalog", required=True)
    p.add_argument("--library")
    p.add_argument("--stage", choices=["initial", "stable", "final", "ad-hoc", "dated", "unknown"])
    p.add_argument("--only-missing", action="store_true")
    p.add_argument("--limit", type=int)
    p.add_argument("--mode", default="signature", choices=["quick", "inventory", "signature", "candidate", "release", "diff", "refresh", "full"])
    p.add_argument("--workdir", default="work")
    p.add_argument("--catalog-html-out")
    p.add_argument("--no-catalog-render", action="store_true")
    p.add_argument("--config-dir", default="configs")
    p.add_argument("--state-dir")
    p.add_argument("--cache-dir")
    p.add_argument("--config")
    p.add_argument("--scan-id")
    p.add_argument("--progress-interval", type=int, default=50)
    p.add_argument("--no-progress", action="store_true")
    p.add_argument("--console-progress", dest="console_progress", action="store_true", default=None)
    p.add_argument("--no-console-progress", dest="console_progress", action="store_false")
    p.add_argument("--parse-jobs", type=int, default=8)
    p.add_argument("--skip-cache", action="store_true")
    p.add_argument("--no-cache", action="store_true")
    p.set_defaults(func=run_catalog_batch)

    p = subparsers.add_parser("compare-batch", help="Run catalog-driven diff workflow for many versions")
    p.add_argument("--catalog", required=True)
    p.add_argument("--library")
    p.add_argument("--stage", choices=["initial", "stable", "final", "ad-hoc", "dated", "unknown"])
    p.add_argument("--mode", default="adjacent", choices=["adjacent", "cumulative"])
    p.add_argument("--workdir", default="work")
    p.add_argument("--catalog-html-out")
    p.add_argument("--no-catalog-render", action="store_true")
    p.add_argument("--only-ready", action="store_true")
    p.add_argument("--only-pending", action="store_true")
    p.add_argument("--limit", type=int)
    p.set_defaults(func=run_catalog_compare_batch)

    p = subparsers.add_parser("release-batch", help="Run catalog-driven release link workflow for many scanned versions")
    p.add_argument("--catalog", required=True)
    p.add_argument("--library")
    p.add_argument("--version", action="append", default=[], help="Version id or version_key. Repeat to select multiple versions.")
    p.add_argument("--stage", choices=["initial", "stable", "final", "ad-hoc", "dated", "unknown"])
    p.add_argument("--policy", default="configs/release_policy.json")
    p.add_argument("--release-root", required=True)
    p.add_argument("--alias", default="current")
    p.add_argument("--release-id")
    p.add_argument("--out", help="Release run directory. Defaults beside the catalog work area.")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--link-mode", default="symlink", choices=["symlink", "copy"])
    p.add_argument("--force", action="store_true")
    p.add_argument("--force-reason")
    p.add_argument("--diff")
    p.add_argument("--diff-mode", choices=["adjacent", "cumulative"])
    p.add_argument("--only-checked", action="store_true", help="Only select versions with PASS/PASS_WITH_WARNING release-check status.")
    p.add_argument("--only-ready", action="store_true", help="Skip manual-review versions and versions with blocking release-check status.")
    p.add_argument("--limit", type=int)
    p.add_argument("--no-verify", action="store_true", help="Skip post-release verify after --apply.")
    p.add_argument("--no-render", action="store_true", help="Skip release HTML rendering after verify.")
    p.add_argument("--catalog-html-out")
    p.add_argument("--no-catalog-render", action="store_true")
    p.set_defaults(func=run_catalog_release_batch)


def add_version_parser(subparsers: Any) -> None:
    root = subparsers.add_parser("version", help="Version graph/index operations")
    sp = root.add_subparsers(dest="version_cmd", required=True)

    p = sp.add_parser("register", help="Register a scan output as a release version")
    p.add_argument("--scan")
    p.add_argument("--raw-root")
    p.add_argument("--library-id")
    p.add_argument("--version-id")
    p.add_argument("--version-type", default="full", choices=["full", "hotfix", "candidate", "daily", "milestone"])
    p.add_argument("--release-line")
    p.add_argument("--parent-version")
    p.add_argument("--base-version")
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--workdir", default="work")
    p.set_defaults(func=run_version_register)

    p = sp.add_parser("list", help="List registered versions")
    p.add_argument("--library-id")
    p.add_argument("--workdir", default="work")
    p.set_defaults(func=run_version_list)


def build_parser() -> ArgumentParser:
    parser = ArgumentParser(prog="lib_guard", description="lib_guard v5 CLI")
    parser.add_argument("-v", "--verbose", action="count", default=0)
    parser.add_argument("--tool-version", action="store_true")
    subparsers = parser.add_subparsers(dest="command")
    add_scan_parser(subparsers)
    add_scan_status_parser(subparsers)
    add_history_parser(subparsers)
    add_render_parser(subparsers)
    add_release_parser(subparsers)
    add_package_parser(subparsers)
    add_update_parser(subparsers)
    add_console_parser(subparsers)
    add_diff_parser(subparsers)
    add_file_diff_parser(subparsers)
    add_library_parser(subparsers)
    add_catalog_parser(subparsers)
    add_workflow_parsers(subparsers)
    add_version_parser(subparsers)
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) >= 2 and argv[0] == "scan" and argv[1] == "status":
        argv = ["scan-status", *argv[2:]]
    parser = build_parser()
    args = parser.parse_args(argv)
    setup_logging(args.verbose)
    if args.tool_version:
        print("0.5.0")
        return 0
    if not hasattr(args, "func"):
        parser.print_help()
        return 1
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        LOGGER.error("interrupted")
        return 130
    except Exception as exc:
        LOGGER.exception("command failed: %s", exc)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
