"""Release-related CLI command handlers."""

from __future__ import annotations

from argparse import Namespace

from .common import print_json


def run_release_check(args: Namespace) -> int:
    from lib_guard.history.index import resolve_scan_dir, HistoryIndex
    from lib_guard.release.checker import check_release_scan

    scan_dir = resolve_scan_dir(scan=args.scan, latest=args.latest, library_id=args.library_id, mode=args.mode, workdir=args.workdir)
    result = check_release_scan(scan_dir, policy_path=args.policy, diff_dir=args.diff)
    if args.register_history:
        meta = {}
        meta_path = Path(scan_dir) / "scan_meta.json"
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        library_id = args.library_id or meta.get("library_id") or "unknown/unknown/unknown"
        HistoryIndex(args.workdir).register_run(
            library_id=library_id,
            kind="release",
            mode=args.mode or meta.get("scan_mode"),
            scan_id=auto_scan_id(),
            out_dir=str(scan_dir),
            status=result.get("release_check_status", "UNKNOWN"),
            source_scan=str(scan_dir),
            update_latest=True,
            summary=result.get("summary", {}),
        )
    print_json(result)
    return 0 if result.get("release_check_status") not in {"FAILED", "BLOCK"} else 2


def run_release_link(args: Namespace) -> int:
    if getattr(args, "manifest", None):
        from lib_guard.release.linker import link_release_from_manifest

        result = link_release_from_manifest(
            args.manifest,
            apply=bool(args.apply),
            mode=getattr(args, "link_mode", None) or "symlink",
            overwrite=getattr(args, "overwrite", False),
            release_root=getattr(args, "release_root", None),
            alias=getattr(args, "alias", None),
        )
        print_json(result)
        return 0 if result.get("status") not in {"FAILED"} else 2

    from lib_guard.history.index import resolve_scan_dir
    from lib_guard.release.linker import link_release_from_scan

    if not getattr(args, "release_root", None):
        raise ValueError("release link --scan requires --release-root")

    scan_dir = resolve_scan_dir(scan=args.scan, latest=args.latest, library_id=args.library_id, mode=args.mode, workdir=args.workdir)
    dry_run = not bool(args.apply)
    result = link_release_from_scan(
        scan_dir=scan_dir,
        release_root=args.release_root,
        alias=args.alias,
        dry_run=dry_run,
        policy_path=args.policy,
        force=args.force,
        force_reason=args.force_reason,
        overwrite=getattr(args, "overwrite", False),
        diff_dir=getattr(args, "diff", None),
    )
    print_json(result)
    return 0 if result.get("status") not in {"FAILED", "BLOCKED"} else 2


def run_release_manifest_template(args: Namespace) -> int:
    from lib_guard.release.bundle import create_manifest_template_from_catalog

    result = create_manifest_template_from_catalog(
        args.catalog,
        args.out,
        release_root=args.release_root,
        alias=args.alias,
        release_id=args.release_id,
        library=args.library,
        versions=args.version or [],
        stage=args.stage,
        created_by=args.created_by,
    )
    print_json({"status": "PASS", "manifest": args.out, "release_id": result.get("release_id"), "library_count": len(result.get("libraries", []) or [])})
    return 0


def run_release_verify(args: Namespace) -> int:
    from lib_guard.release.postcheck import verify_release_manifest

    result = verify_release_manifest(
        args.manifest,
        link_result_path=args.link_result,
        out_dir=args.out,
        render=bool(args.render),
        html_out=args.html_out,
    )
    print_json(result)
    return 0 if result.get("status") in {"PASS", "PASS_WITH_WARNING"} else 2


def run_release_manifest_from_snapshot(args: Namespace) -> int:
    from lib_guard.release.bundle import create_manifest_from_snapshot

    result = create_manifest_from_snapshot(
        args.snapshot,
        args.out,
        release_root=args.release_root,
        alias=args.alias,
        release_id=args.release_id,
        created_by=args.created_by,
    )
    print_json({"status": "PASS", "manifest": args.out, "snapshot_id": result.get("snapshot_id"), "file_count": len(result.get("files", []) or [])})
    return 0

