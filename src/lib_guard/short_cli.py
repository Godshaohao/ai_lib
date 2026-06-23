from __future__ import annotations

from argparse import ArgumentParser, Namespace, RawDescriptionHelpFormatter
from pathlib import Path
from typing import Any
import json
import os
import sys


CONFIG_NAME = "lib_guard.yml"
PAIRWISE_FILE_DIFF_TYPES = {"lef", "liberty", "verilog", "cdl", "sdc", "upf", "cpf", "spef", "db"}


def _norm(path: str | Path) -> str:
    return str(Path(path))


def write_default_config(workspace: str | Path, *, raw_root: str | Path | None = None, library_type: str = "ip") -> Path:
    root = Path(workspace)
    root.mkdir(parents=True, exist_ok=True)
    raw = Path(raw_root) if raw_root else root / "raw"
    lines = [
        "# lib_guard short command workspace",
        f"workspace: {root}",
        f"raw_root: {raw}",
        f"catalog: {root / 'catalog' / 'catalog.json'}",
        f"catalog_html: {root / 'catalog' / 'html'}",
        f"reports: {root / 'reports'}",
        f"diff: {root / 'diff'}",
        f"file_diff: {root / 'file_diff'}",
        f"release_root: {root / 'release_area'}",
        f"library_type: {library_type}",
        "mode: signature",
        "parse_jobs: 8",
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
    project_root = os.environ.get("LIB_GUARD_PROJECT_ROOT")
    default_policy = Path(project_root) / "configs" / "catalog_policy.json" if project_root else None
    cfg.setdefault("workspace", str(path.parent))
    cfg.setdefault("raw_root", str(path.parent / "raw"))
    cfg.setdefault("catalog", str(path.parent / "catalog" / "catalog.json"))
    cfg.setdefault("catalog_html", str(path.parent / "catalog" / "html"))
    cfg.setdefault("reports", str(path.parent / "reports"))
    cfg.setdefault("diff", str(path.parent / "diff"))
    cfg.setdefault("file_diff", str(path.parent / "file_diff"))
    cfg.setdefault("release_root", str(path.parent / "release_area"))
    cfg.setdefault("config_dir", str(path.parent / "config"))
    cfg.setdefault("library_list", str(Path(cfg["config_dir"]) / "library.list"))
    cfg.setdefault("library_catalog", str(Path(cfg["config_dir"]) / "library_catalog.yml"))
    cfg.setdefault("library_type", "ip")
    if "catalog_policy" not in cfg:
        library_catalog = Path(cfg["library_catalog"])
        if library_catalog.exists():
            cfg["catalog_policy"] = str(library_catalog)
        elif default_policy and default_policy.exists():
            cfg["catalog_policy"] = str(default_policy)
    cfg.setdefault("mode", "signature")
    cfg.setdefault("parse_jobs", "8")
    return cfg


def _catalog_data(cfg: dict[str, str]) -> dict[str, Any]:
    path = Path(cfg["catalog"])
    if not path.exists():
        raise FileNotFoundError(f"catalog not found: {path}. Run: scripts/lg.ps1 scan")
    return json.loads(path.read_text(encoding="utf-8"))


def _library_match_score(item: dict[str, Any], library: str) -> int:
    exact = {str(item.get("library_id") or ""), str(item.get("library_name") or "")}
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
        raise ValueError(f"ambiguous library alias {library!r}; use full library_id. Matched: {choices}")
    return matches[0]


def _find_version(library: dict[str, Any], version: str) -> dict[str, Any]:
    for item in library.get("versions", []) or []:
        if item.get("version_id") == version:
            return item
    raise ValueError(f"version not found in catalog: {version}")


def _resolve_old_version(library: dict[str, Any], version: dict[str, Any], explicit_base: str | None) -> dict[str, Any]:
    if explicit_base:
        return _find_version(library, explicit_base)
    old_id = ((version.get("diff") or {}).get("adjacent_old_version") or version.get("base_version") or (version.get("lineage") or {}).get("base_candidate"))
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
    if file_type not in PAIRWISE_FILE_DIFF_TYPES:
        raise ValueError(f"file type {file_type!r} is not supported by pairwise file-diff")
    return file_type


def _build_parser() -> ArgumentParser:
    parser = ArgumentParser(
        prog="lg",
        description="lib_guard short command shell",
        formatter_class=RawDescriptionHelpFormatter,
        epilog="""Examples:
  C Shell:
    lg.csh init $WORK --raw-root $RAW
    cd $WORK
    lg.csh catalog
    lg.csh catalog ucie
    lg.csh catalog ucie --with-evidence
    lg.csh scan
    lg.csh scan ucie --limit 3
    lg.csh scan ucie --missing
    lg.csh scan ucie --all-versions
    lg.csh scan ucie stable_20250608
    lg.csh diff ucie stable_20250608
    lg.csh diff ucie stable_20250608 --base initial_20250601 --scan-if-missing
    lg.csh file-diff ucie stable_20250608 lef/ucie.lef

  PowerShell:
    lg.ps1 init $WORK --raw-root $RAW
    cd $WORK
    lg.ps1 catalog
    lg.ps1 catalog ucie
    lg.ps1 catalog ucie --with-evidence
    lg.ps1 scan
    lg.ps1 scan ucie --limit 3
    lg.ps1 scan ucie --missing
    lg.ps1 scan ucie --all-versions
    lg.ps1 scan ucie stable_20250608
    lg.ps1 diff ucie stable_20250608
    lg.ps1 diff ucie stable_20250608 --base initial_20250601 --scan-if-missing
    lg.ps1 file-diff ucie stable_20250608 lef/ucie.lef

  Dry-run / without cd:
    setenv LIB_GUARD_CONFIG $WORK/lib_guard.yml
    lg.csh --dry-run scan ucie stable_20250608
""",
    )
    parser.add_argument("--config", help=f"Path to {CONFIG_NAME}")
    parser.add_argument("--dry-run", action="store_true", help="Print expanded python commands without executing them")
    sub = parser.add_subparsers(dest="short_command", required=True)

    p = sub.add_parser("init", help="Create lib_guard.yml in a workspace")
    p.add_argument("workspace")
    p.add_argument("--raw-root")
    p.add_argument("--library-type", default="ip")

    p = sub.add_parser("scan", help="Refresh catalog or scan explicit catalog versions")
    p.add_argument("library", nargs="?")
    p.add_argument("version", nargs="?")
    p.add_argument("--missing", action="store_true", help="Scan only versions without scan evidence")
    p.add_argument("--all-versions", action="store_true", help="Explicitly scan all selected versions")
    p.add_argument("--limit", type=int, help="Limit batch scan count for safe trial runs")
    p.add_argument("--stage", choices=["initial", "stable", "final", "ad-hoc", "dated", "unknown"], help="Limit batch scan to one catalog stage")
    p.add_argument("--with-evidence", action="store_true", help="Refresh catalog with file-type evidence before scanning")

    p = sub.add_parser("catalog", help="Refresh catalog index and catalog HTML only")
    p.add_argument("library", nargs="?")
    p.add_argument("--full", action="store_true", help="Force full catalog refresh instead of using catalog_state.json")
    p.add_argument("--fast", action="store_true", help="Directory-only catalog refresh. This is the default for short commands.")
    p.add_argument("--with-evidence", action="store_true", help="Collect lightweight file-type evidence for discovered versions; slower on large RAW trees.")

    root_library = sub.add_parser("library", help="Discover and apply the confirmed library registry")
    lsp = root_library.add_subparsers(dest="library_cmd", required=True)
    p = lsp.add_parser("discover", help="Discover candidate library roots from RAW and write editable library.list")
    p.add_argument("--out", help="Editable library.list output. Default: $WORK/config/library.list")
    p.add_argument("--json-out", help="Machine discovery evidence JSON. Default: $WORK/config/library_discovery.json")
    p.add_argument("--html-out", help="Discovery review HTML. Default: $WORK/config/library_discovery.html")
    p.add_argument("--max-depth", type=int, default=8)
    p.add_argument("--min-versions", type=int, default=2)
    p.add_argument("--default-status", choices=["REVIEW", "OK"], default="REVIEW")

    p = lsp.add_parser("apply", help="Convert confirmed library.list into library_catalog.yml")
    p.add_argument("--input", help="Input library.list. Default: $WORK/config/library.list")
    p.add_argument("--out", help="Formal library_catalog.yml output. Default: $WORK/config/library_catalog.yml")

    p = sub.add_parser("diff", help="Run base-aware catalog structural diff without hidden rescans")
    p.add_argument("library")
    p.add_argument("version")
    p.add_argument("--mode", default="adjacent", choices=["adjacent", "cumulative"], help="Catalog relation used when --base is not provided")
    p.add_argument("--base", help="Explicit base version. Required when catalog cannot infer a trustworthy base.")
    p.add_argument("--scan-if-missing", action="store_true", help="Scan only missing old/new scan evidence before compare")
    p.add_argument("--rescan", action="store_true", help="Force rescan of old and new versions before compare")
    p.add_argument("--auto-scan", action="store_true", help="Deprecated alias for --scan-if-missing; does not force rescan")
    p.add_argument("--refresh-catalog", action="store_true", help="Refresh this library catalog before compare. Default is to use existing catalog.json.")
    p.add_argument("--with-evidence", action="store_true", help="When --refresh-catalog is used, collect file-type evidence during catalog refresh")

    p = sub.add_parser("file-diff", help="Run pairwise file diff from catalog raw paths; never runs scan")
    p.add_argument("library")
    p.add_argument("version")
    p.add_argument("relpath")
    p.add_argument("--base")
    p.add_argument("--type")

    p = sub.add_parser("release", help="Run catalog release for an already-scanned version; never runs scan")
    p.add_argument("library")
    p.add_argument("version")
    p.add_argument("--alias", default="current")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--link-mode", default="copy", choices=["copy", "symlink"])
    p.add_argument("--check-only", action="store_true", help="Only run release-check for this catalog version")
    p.add_argument("--check-first", action="store_true", help="Run release-check before release-batch")
    p.add_argument("--only-checked", action="store_true", help="Release only if prior/latest release-check is PASS/PASS_WITH_WARNING")
    p.add_argument("--only-ready", action="store_true", help="Skip manual-review or blocked versions")
    p.add_argument("--force", action="store_true")
    p.add_argument("--force-reason")
    p.add_argument("--no-verify", action="store_true")
    p.add_argument("--no-render", action="store_true")
    return parser


def _catalog_scan_command(
    cfg: dict[str, str],
    library: str | None = None,
    *,
    full: bool = False,
    with_evidence: bool = False,
) -> list[str]:
    catalog = cfg["catalog"]
    command = [
        "catalog",
        "scan",
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

def _scan_run_command(cfg: dict[str, str], library: str, version: str) -> list[str]:
    return [
        "run",
        "--catalog",
        cfg["catalog"],
        "--library",
        library,
        "--version",
        version,
        "--mode",
        cfg["mode"],
        "--workdir",
        cfg["workspace"],
        "--console-progress",
        "--progress-interval",
        "1",
        "--parse-jobs",
        cfg["parse_jobs"],
        "--catalog-html-out",
        cfg["catalog_html"],
    ]


def _library_discover_command(cfg: dict[str, str], args: Any) -> list[str]:
    config_dir = Path(cfg.get("config_dir") or Path(cfg["workspace"]) / "config")
    return [
        "library",
        "discover",
        "--root",
        cfg["raw_root"],
        "--out",
        args.out or str(config_dir / "library.list"),
        "--json-out",
        args.json_out or str(config_dir / "library_discovery.json"),
        "--html-out",
        args.html_out or str(config_dir / "library_discovery.html"),
        "--max-depth",
        str(args.max_depth),
        "--min-versions",
        str(args.min_versions),
        "--default-status",
        args.default_status,
    ]


def _library_apply_command(cfg: dict[str, str], args: Any) -> list[str]:
    config_dir = Path(cfg.get("config_dir") or Path(cfg["workspace"]) / "config")
    return [
        "library",
        "apply",
        "--root",
        cfg["raw_root"],
        "--input",
        args.input or str(config_dir / "library.list"),
        "--out",
        args.out or str(config_dir / "library_catalog.yml"),
        "--library-type",
        cfg["library_type"],
    ]


def _scan_batch_command(
    cfg: dict[str, str],
    library: str | None,
    *,
    only_missing: bool = False,
    limit: int | None = None,
    stage: str | None = None,
) -> list[str]:
    command = [
        "run-batch",
        "--catalog",
        cfg["catalog"],
        "--mode",
        cfg["mode"],
        "--workdir",
        cfg["workspace"],
        "--console-progress",
        "--progress-interval",
        "1",
        "--parse-jobs",
        cfg["parse_jobs"],
        "--catalog-html-out",
        cfg["catalog_html"],
    ]
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

def build_cli_commands(argv: list[str], *, cwd: str | Path | None = None) -> list[list[str]]:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.short_command == "init":
        return []
    cfg = _load_config(cwd or Path.cwd(), args.config)
    catalog = cfg["catalog"]
    html = cfg["catalog_html"]
    if args.short_command == "library":
        if args.library_cmd == "discover":
            return [_library_discover_command(cfg, args)]
        if args.library_cmd == "apply":
            return [_library_apply_command(cfg, args)]
        raise ValueError(f"unsupported library command: {args.library_cmd}")
    if args.short_command == "catalog":
        return [
            _catalog_scan_command(
                cfg,
                args.library,
                full=bool(getattr(args, "full", False)),
                with_evidence=bool(getattr(args, "with_evidence", False)),
            )
        ]
    if args.short_command == "scan":
        with_evidence = bool(getattr(args, "with_evidence", False))
        if args.library and args.version:
            return [_catalog_scan_command(cfg, args.library, with_evidence=with_evidence), _scan_run_command(cfg, args.library, args.version)]
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
                ),
            ]
        return [_catalog_scan_command(cfg)]
    if args.short_command == "diff":
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
            compare.extend(["--scan-mode", cfg["mode"]])
            compare.extend(["--parse-jobs", cfg["parse_jobs"]])
            compare.extend(["--progress-interval", "1", "--console-progress"])
        if getattr(args, "rescan", False):
            compare.append("--rescan")
            compare.extend(["--scan-mode", cfg["mode"]])
            compare.extend(["--parse-jobs", cfg["parse_jobs"]])
            compare.extend(["--progress-interval", "1", "--console-progress"])
        commands.append(compare)
        return commands
    if args.short_command == "file-diff":
        data = _catalog_data(cfg)
        lib = _find_library(data, args.library)
        new_version = _find_version(lib, args.version)
        old_version = _resolve_old_version(lib, new_version, args.base)
        file_type = args.type or _infer_file_type(args.relpath)
        if file_type not in PAIRWISE_FILE_DIFF_TYPES:
            raise ValueError(f"file type {file_type!r} is not supported by pairwise file-diff")
        old_file = Path(str(old_version.get("raw_path"))) / args.relpath
        new_file = Path(str(new_version.get("raw_path"))) / args.relpath
        safe_name = args.relpath.replace("\\", "/").replace("/", "_").replace(":", "_")
        stem = Path(safe_name).stem
        out_name = stem if stem.startswith(f"{file_type}_") else f"{file_type}_{stem}"
        out = Path(cfg["file_diff"]) / args.library / args.version / out_name
        return [["file-diff", file_type, "--old", str(old_file), "--new", str(new_file), "--out", str(out)]]
    if args.short_command == "release":
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
        ]
        if args.check_only:
            return [check_cmd]
        if args.check_first:
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


def run_init(args: Namespace) -> int:
    path = write_default_config(args.workspace, raw_root=args.raw_root, library_type=args.library_type)
    print(json.dumps({"status": "PASS", "config": _norm(path)}, ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.short_command == "init":
        return run_init(args)
    commands = build_cli_commands(argv, cwd=Path.cwd())
    if args.short_command == "scan" and not getattr(args, "library", None):
        print("[WARN] 'lg scan' without target now refreshes catalog only.", file=sys.stderr)
        print("[INFO] Use 'lg catalog' for discovery, or 'lg scan <library> <version>' for scan HTML.", file=sys.stderr)
    if args.short_command == "diff" and getattr(args, "auto_scan", False):
        print("[WARN] 'lg diff --auto-scan' is deprecated and now means --scan-if-missing, not forced rescan.", file=sys.stderr)
        print("[INFO] Use --rescan only when you intentionally want to rebuild both scan outputs.", file=sys.stderr)
    for command in commands:
        print("python -m lib_guard.cli " + " ".join(command))
    if args.dry_run:
        return 0
    from lib_guard.cli import main as cli_main

    for command in commands:
        code = cli_main(command)
        if code != 0:
            return int(code)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
