"""Release link helper.

This module does not hard-code library paths. It uses scan_meta.root_path and a
configurable release root.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from datetime import datetime, timezone
import json
import os
import shutil
import uuid

from lib_guard.atomic import atomic_write_json, file_lock
from .checker import ReleaseChecker
from .config import ReleasePolicy
from .bundle import (
    immutable_release_dir_for,
    iter_release_files,
    load_release_manifest,
    manifest_run_dir,
    release_alias_for,
    release_dir_for,
    release_staging_dir_for,
    utc_now,
)


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: Any) -> None:
    atomic_write_json(path, data, lock=True)


def _utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")


class ReleaseLinker:
    def __init__(self, policy: ReleasePolicy | None = None) -> None:
        self.policy = policy or ReleasePolicy()

    def link(
        self,
        scan_dir: str | Path,
        release_root: str | Path,
        alias: str = "current",
        dry_run: bool = True,
        mode: str | None = None,
        out_dir: str | Path | None = None,
        force: bool = False,
        force_reason: str | None = None,
        overwrite: bool = False,
        diff_dir: str | Path | None = None,
    ) -> dict[str, Any]:
        scan = Path(scan_dir)
        release_root_path = Path(release_root)
        out = Path(out_dir) if out_dir else scan / "release"
        if force and not force_reason:
            raise ValueError("force release requires force_reason")
        if force and dry_run:
            raise ValueError("force release requires --apply")
        check = ReleaseChecker(self.policy).check(scan, out, diff_dir=diff_dir, alias=alias if diff_dir else None)

        scan_meta = _load_json(scan / "scan_meta.json", {})
        source_root = Path(str(scan_meta.get("root_path") or ""))
        library_type = str(scan_meta.get("library_type") or "unknown")
        library_name = str(scan_meta.get("library_name") or "unknown")
        version = str(scan_meta.get("release_version") or "unknown")

        manifest = {
            "schema_version": "release_manifest.v1",
            "release_id": version,
            "alias": alias,
            "release_root": str(release_root_path),
            "created_by": os.environ.get("USER") or os.environ.get("USERNAME") or "unknown",
            "source_kind": "scan",
            "scan_dir": str(scan),
            "libraries": [
                {
                    "library_type": library_type,
                    "library_name": library_name,
                    "version_id": version,
                    "version_key": f"{library_type}/{library_name}/{version}",
                    "scan_dir": str(scan),
                    "source_path": str(scan_meta.get("root_path") or ""),
                    "manual_accept": True,
                }
            ],
            "files": [],
        }
        manifest_path = out / "release_manifest.json"
        _write_json(manifest_path, manifest)
        target_version_dir = release_root_path / "releases" / version
        target_alias = release_root_path / alias
        link_mode = mode or self.policy.release_link_mode
        dir_check = self._inspect_targets(target_version_dir, target_alias)

        actions: list[dict[str, Any]] = []
        actions.append({"action": "check", "status": check.get("release_check_status")})
        actions.append(
            {
                "action": link_mode,
                "source": str(source_root),
                "target_version_dir": str(target_version_dir),
                "target_alias": str(target_alias),
                "dry_run": dry_run,
                "overwrite": overwrite,
                "release_dir_check": dir_check,
            }
        )
        if force:
            actions.append({"action": "force_override", "reason": force_reason, "release_check_status": check.get("release_check_status")})

        status = "DRY_RUN" if dry_run else "DONE"
        linked: dict[str, Any] | None = None
        blocked_by_gate = check.get("release_check_status") in {"BLOCK", "FAILED"} or check.get("allowed_to_apply") is False
        blocked_by_existing_target = bool(dir_check.get("target_exists")) and not overwrite
        if blocked_by_gate and not force:
            status = "BLOCKED"
        elif blocked_by_existing_target:
            status = "BLOCKED"
        else:
            linked = link_release_from_manifest(
                manifest_path,
                apply=not dry_run,
                mode=link_mode,
                overwrite=overwrite,
                force=force,
                force_reason=force_reason,
                release_check_path=out / "release_check.json",
            )
            status = {
                "APPLIED": "FORCED_DONE" if force else "DONE",
                "FORCED_APPLIED": "FORCED_DONE",
            }.get(str(linked.get("status")), linked.get("status", "FAILED"))

        result = {
            "schema_version": "1.0",
            "status": status,
            "scan_dir": str(scan),
            "release_root": str(release_root_path),
            "release_lock": str(_release_lock_path(release_root_path)),
            "source_root": str(source_root),
            "target_version_dir": str(target_version_dir),
            "target_alias": str(target_alias),
            "dry_run": dry_run,
            "force": force,
            "force_reason": force_reason,
            "overwrite": overwrite,
            "link_mode": link_mode,
            "release_dir_check": dir_check,
            "release_check": check,
            "block_reasons": check.get("block_reasons", []),
            "actions": actions,
            "manifest_path": str(manifest_path),
        }
        if linked is not None:
            result.update({key: value for key, value in linked.items() if key not in result})
            result["status"] = status
        if force and linked is None:
            _write_json(
                out / "release_override.json",
                {
                    "schema_version": "1.0",
                    "force": True,
                    "force_reason": force_reason,
                    "forced_at": _utc_now(),
                    "scan_dir": str(scan),
                    "release_root": str(release_root_path),
                    "target_version_dir": str(target_version_dir),
                    "target_alias": str(target_alias),
                    "release_check_status": check.get("release_check_status"),
                    "release_check_issues": check.get("issues", []),
                },
            )
        _write_json(out / "release_link.json", result)
        return result

    def _inspect_targets(self, target_version_dir: Path, target_alias: Path) -> dict[str, Any]:
        return {
            "target_version_dir": str(target_version_dir),
            "target_exists": target_version_dir.exists() or target_version_dir.is_symlink(),
            "target_is_symlink": target_version_dir.is_symlink(),
            "alias": str(target_alias),
            "alias_exists": target_alias.exists() or target_alias.is_symlink(),
            "alias_is_symlink": target_alias.is_symlink(),
        }

    def _link_symlink(self, source_root: Path, target_version_dir: Path, target_alias: Path, *, overwrite: bool = False) -> None:
        target_version_dir.parent.mkdir(parents=True, exist_ok=True)
        if target_version_dir.exists() or target_version_dir.is_symlink():
            if not overwrite:
                raise FileExistsError(f"release target already exists: {target_version_dir}")
            target_version_dir.unlink() if target_version_dir.is_symlink() else shutil.rmtree(target_version_dir)
        if not target_version_dir.exists():
            tmp_version = _tmp_sibling(target_version_dir)
            tmp_version.symlink_to(source_root)
            os.replace(tmp_version, target_version_dir)

        tmp_alias = _tmp_sibling(target_alias)
        if tmp_alias.exists() or tmp_alias.is_symlink():
            tmp_alias.unlink()
        tmp_alias.symlink_to(target_version_dir)
        os.replace(tmp_alias, target_alias)

    def _copy_tree(self, source_root: Path, target_version_dir: Path, target_alias: Path, *, overwrite: bool = False) -> None:
        target_version_dir.parent.mkdir(parents=True, exist_ok=True)
        if target_version_dir.exists():
            if not overwrite:
                raise FileExistsError(f"release target already exists: {target_version_dir}")
        tmp_version = _tmp_sibling(target_version_dir)
        if tmp_version.exists() or tmp_version.is_symlink():
            _remove_path(tmp_version)
        shutil.copytree(source_root, tmp_version, symlinks=True)
        if target_version_dir.exists() or target_version_dir.is_symlink():
            _remove_path(target_version_dir)
        os.replace(tmp_version, target_version_dir)
        tmp_alias = _tmp_sibling(target_alias)
        if tmp_alias.exists() or tmp_alias.is_symlink():
            tmp_alias.unlink() if tmp_alias.is_symlink() else shutil.rmtree(tmp_alias)
        shutil.copytree(target_version_dir, tmp_alias, symlinks=True)
        if target_alias.exists() or target_alias.is_symlink():
            target_alias.unlink() if target_alias.is_symlink() else shutil.rmtree(target_alias)
        os.replace(tmp_alias, target_alias)


def link_release_from_scan(
    scan_dir: str | Path,
    release_root: str | Path,
    alias: str = "current",
    dry_run: bool = True,
    policy_path: str | Path | None = None,
    force: bool = False,
    force_reason: str | None = None,
    overwrite: bool = False,
    diff_dir: str | Path | None = None,
) -> dict[str, Any]:
    return ReleaseLinker(ReleasePolicy.from_file(policy_path)).link(scan_dir=scan_dir, release_root=release_root, alias=alias, dry_run=dry_run, force=force, force_reason=force_reason, overwrite=overwrite, diff_dir=diff_dir)


def _remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def _tmp_sibling(path: Path) -> Path:
    return path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")


def _release_lock_path(release_root: Path) -> Path:
    return release_root / ".lib_guard_release.lock"


def _copy_or_link_source(source: Path, target: Path, *, mode: str, overwrite: bool) -> str:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() or target.is_symlink():
        if not overwrite:
            raise FileExistsError(f"release target already exists: {target}")
    tmp = _tmp_sibling(target)
    if tmp.exists() or tmp.is_symlink():
        _remove_path(tmp)
    if mode == "copy":
        if source.is_dir():
            shutil.copytree(source, tmp, symlinks=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, tmp)
        if target.exists() or target.is_symlink():
            _remove_path(target)
        os.replace(tmp, target)
        return "COPIED"
    if mode == "symlink":
        tmp.symlink_to(source, target_is_directory=source.is_dir())
        if target.exists() or target.is_symlink():
            _remove_path(target)
        os.replace(tmp, target)
        return "LINKED"
    raise ValueError(f"Unsupported release link mode: {mode}")


def _release_existing_files(release_dir: Path) -> list[Path]:
    if not release_dir.exists():
        return []
    return sorted(
        [
            item
            for item in release_dir.rglob("*")
            if (item.is_file() or item.is_symlink()) and item.name != ".lib_guard_release.lock" and not (item.name.startswith(".") and item.name.endswith(".tmp"))
        ],
        key=lambda p: p.as_posix().lower(),
    )


def _force_gate_summary(review_gate_path: str | Path | None, release_check_path: str | Path | None) -> Any:
    def _safe_load_mapping(path: str | Path | None) -> dict[str, Any]:
        if not path:
            return {}
        try:
            loaded = _load_json(Path(path), {})
        except Exception:
            return {}
        return loaded if isinstance(loaded, dict) else {}

    def _safe_int(value: Any) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    review_gate = _safe_load_mapping(review_gate_path)
    release_check = _safe_load_mapping(release_check_path)
    blocking_items = review_gate.get("blocking_items", []) if isinstance(review_gate.get("blocking_items", []), list) else []
    blocking_open = review_gate.get("blocking_open") if "blocking_open" in review_gate else len(blocking_items)
    block_reasons = release_check.get("block_reasons", [])
    if not isinstance(block_reasons, list):
        block_reasons = []
    return {
        "review_gate_status": review_gate.get("status") or "NOT_PROVIDED",
        "release_check_status": release_check.get("release_check_status") or release_check.get("status") or "NOT_PROVIDED",
        "blocking_open": _safe_int(blocking_open),
        "block_reasons": block_reasons,
    }


def _force_selected_versions(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    selected = []
    for item in manifest.get("libraries", []) or []:
        selected.append(
            {
                "library_type": item.get("library_type"),
                "library_name": item.get("library_name"),
                "version_id": item.get("version_id"),
                "version_key": item.get("version_key"),
                "source_path": item.get("source_path"),
            }
        )
    for item in manifest.get("files", []) or []:
        selected.append(
            {
                "library_type": item.get("library_type"),
                "library_name": item.get("library_name"),
                "version_id": item.get("version_id"),
                "version_key": item.get("version_key"),
                "snapshot_id": item.get("snapshot_id") or manifest.get("snapshot_id"),
                "source_path": item.get("source_path"),
                "target_relpath": item.get("target_relpath") or item.get("relative_path"),
            }
        )
    return selected


def _path_exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _rebase_link_paths(items: list[dict[str, Any]], root: Path) -> None:
    for item in items:
        relative_path = item.get("relative_path")
        if relative_path:
            item["link_path"] = str(root / str(relative_path))


def _move_to_backup(path: Path) -> Path | None:
    if not _path_exists(path):
        return None
    backup = _tmp_sibling(path)
    os.replace(path, backup)
    return backup


def _restore_backup(path: Path, backup: Path | None) -> None:
    _remove_path(path)
    if backup is not None and _path_exists(backup):
        os.replace(backup, path)


def _promotion_legacy_paths(release_root: Path, staging_dir: Path, active_alias: Path) -> list[Path]:
    if not staging_dir.exists():
        return []
    return [
        release_root / child.name
        for child in staging_dir.iterdir()
        if child.is_dir() and release_root / child.name != active_alias
    ]


def _rollback_promotion(state: dict[str, Any]) -> None:
    for path, backup in reversed(state.get("legacy_backups", [])):
        _restore_backup(path, backup)
    _restore_backup(state["active_alias"], state.get("alias_backup"))
    _restore_backup(state["immutable_dir"], state.get("immutable_backup"))


def _finalize_promotion(state: dict[str, Any]) -> None:
    for _path, backup in state.get("legacy_backups", []):
        if backup is not None:
            _remove_path(backup)
    for backup_key in ("alias_backup", "immutable_backup"):
        backup = state.get(backup_key)
        if backup is not None:
            _remove_path(backup)


def _promote_staging(
    staging_dir: Path,
    immutable_dir: Path,
    active_alias: Path,
    *,
    overwrite: bool,
    release_root: Path | None = None,
) -> dict[str, Any]:
    """Promote a verified tree while retaining rollback state until postcheck passes."""

    root = release_root or immutable_dir.parent.parent
    immutable_dir.parent.mkdir(parents=True, exist_ok=True)
    active_alias.parent.mkdir(parents=True, exist_ok=True)
    state: dict[str, Any] = {
        "immutable_dir": immutable_dir,
        "active_alias": active_alias,
        "immutable_backup": None,
        "alias_backup": None,
        "legacy_backups": [],
    }
    try:
        if _path_exists(immutable_dir):
            if not overwrite:
                raise FileExistsError(f"immutable release already exists: {immutable_dir}")
            state["immutable_backup"] = _move_to_backup(immutable_dir)
        if _path_exists(active_alias):
            state["alias_backup"] = _move_to_backup(active_alias)
        for legacy_path in _promotion_legacy_paths(root, staging_dir, active_alias):
            backup = _move_to_backup(legacy_path)
            state["legacy_backups"].append((legacy_path, backup))

        os.replace(staging_dir, immutable_dir)
        tmp_alias = _tmp_sibling(active_alias)
        try:
            tmp_alias.symlink_to(immutable_dir.resolve(strict=False), target_is_directory=True)
            os.replace(tmp_alias, active_alias)
        finally:
            _remove_path(tmp_alias)
        _publish_legacy_view_links(root, active_alias, immutable_dir)
        return state
    except Exception:
        _rollback_promotion(state)
        raise


def _publish_legacy_view_links(release_root: Path, active_alias: Path, immutable_dir: Path) -> None:
    """Keep existing root/view readers working without copying or deleting trees."""

    if not immutable_dir.exists():
        return
    for view_dir in immutable_dir.iterdir():
        if not view_dir.is_dir():
            continue
        legacy_path = release_root / view_dir.name
        if _path_exists(legacy_path) and not legacy_path.is_symlink():
            continue
        tmp_legacy = _tmp_sibling(legacy_path)
        _remove_path(tmp_legacy)
        tmp_legacy.symlink_to((active_alias / view_dir.name).absolute(), target_is_directory=True)
        os.replace(tmp_legacy, legacy_path)


def link_release_from_manifest(
    manifest_path: str | Path,
    *,
    apply: bool = False,
    mode: str = "symlink",
    overwrite: bool = False,
    release_root: str | Path | None = None,
    alias: str | None = None,
    out_dir: str | Path | None = None,
    force: bool = False,
    force_reason: str | None = None,
    force_by: str | None = None,
    review_gate_path: str | Path | None = None,
    release_check_path: str | Path | None = None,
    verify_skipped: bool = False,
    verify_skip_reason: str = "",
    render: bool = False,
) -> dict[str, Any]:
    """Link a human-approved release manifest into the release area.

    This path is intentionally not a release gate. It only performs dry-run/apply
    filesystem actions and records evidence.
    """

    if force and not force_reason:
        raise ValueError("force release requires --force-reason")
    if force:
        force_by = force_by or os.environ.get("USER") or os.environ.get("USERNAME") or "unknown"

    manifest = load_release_manifest(manifest_path, release_root=release_root, alias=alias)
    run_dir = manifest_run_dir(manifest_path, out_dir)
    dry_run = not bool(apply)
    mirror_release_root = bool(manifest.get("mirror_release_root"))
    override_path = run_dir / "release_override.json" if force else None
    created: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    verify_result: dict[str, Any] | None = None
    release_root_path = release_dir_for(manifest)
    staging_dir = release_staging_dir_for(manifest)
    immutable_dir = immutable_release_dir_for(manifest)
    active_alias = release_alias_for(manifest)
    planned = iter_release_files(manifest, target_root=staging_dir)
    final_planned = iter_release_files(manifest, target_root=immutable_dir)
    alias_exists = _path_exists(active_alias)
    alias_is_symlink = active_alias.is_symlink()
    immutable_exists = _path_exists(immutable_dir)
    migration_required = bool(apply and alias_exists and not alias_is_symlink)
    blocked_by_existing_release = bool(immutable_exists and not overwrite)

    def _status_for_failure() -> str:
        return "FORCE_FAILED" if force else "FAILED"

    if migration_required:
        status = "MIGRATION_REQUIRED"
    elif blocked_by_existing_release:
        status = "BLOCKED"
    elif dry_run:
        for plan in planned:
            source = Path(str(plan.get("source_path") or ""))
            target = Path(str(plan.get("target_path") or ""))
            item = {
                "library_type": plan.get("library_type"),
                "library_name": plan.get("library_name"),
                "version_id": plan.get("version_id"),
                "version_key": plan.get("version_key"),
                "relative_path": plan.get("relative_path"),
                "link_path": str(target),
                "target_path": str(source),
                "file_type": plan.get("file_type"),
                "view": plan.get("view"),
                "snapshot_id": plan.get("snapshot_id"),
                "source_package": plan.get("source_package"),
                "source_kind": plan.get("source_kind"),
                "mode": mode,
                "overwrite": overwrite,
            }
            try:
                if plan.get("error"):
                    raise ValueError(str(plan.get("error")))
                if not source.exists():
                    raise FileNotFoundError(f"release source does not exist: {source}")
                exists = _path_exists(target)
                item["status"] = "WOULD_REPLACE" if exists and overwrite else ("TARGET_EXISTS" if exists else "WOULD_LINK")
                if exists and not overwrite:
                    item["warning"] = "target exists; apply would fail without overwrite"
                created.append(item)
            except Exception as exc:
                failed_item = dict(item)
                failed_item["status"] = "FAILED"
                failed_item["error"] = str(exc)
                failed.append(failed_item)
        status = _status_for_failure() if failed else ("FORCE_DRY_RUN" if force else "DRY_RUN")
    else:
        with file_lock(_release_lock_path(release_root_path)):
            release_root_path.mkdir(parents=True, exist_ok=True)
            _remove_path(staging_dir)
            staging_dir.mkdir(parents=True, exist_ok=True)
            for plan in planned:
                source = Path(str(plan.get("source_path") or ""))
                target = Path(str(plan.get("target_path") or ""))
                item = {
                    "library_type": plan.get("library_type"),
                    "library_name": plan.get("library_name"),
                    "version_id": plan.get("version_id"),
                    "version_key": plan.get("version_key"),
                    "relative_path": plan.get("relative_path"),
                    "link_path": str(target),
                    "target_path": str(source),
                    "file_type": plan.get("file_type"),
                    "view": plan.get("view"),
                    "snapshot_id": plan.get("snapshot_id"),
                    "source_package": plan.get("source_package"),
                    "source_kind": plan.get("source_kind"),
                    "mode": mode,
                    "overwrite": overwrite,
                }
                try:
                    if plan.get("error"):
                        raise ValueError(str(plan.get("error")))
                    if not source.exists():
                        raise FileNotFoundError(f"release source does not exist: {source}")
                    item["status"] = _copy_or_link_source(source, target, mode=mode, overwrite=overwrite)
                    created.append(item)
                except Exception as exc:
                    failed_item = dict(item)
                    failed_item["status"] = "FAILED"
                    failed_item["error"] = str(exc)
                    failed.append(failed_item)

            if failed:
                _remove_path(staging_dir)
                status = _status_for_failure()
            else:
                from .postcheck import verify_release_manifest

                try:
                    verify_result = verify_release_manifest(
                        manifest_path,
                        link_result={"created_links": created, "failed_links": failed},
                        candidate_root=staging_dir,
                    )
                except Exception as exc:
                    verify_result = {
                        "status": "FAILED",
                        "summary": {},
                        "issues": [
                            {
                                "severity": "error",
                                "category": "verification_error",
                                "library_name": None,
                                "message": str(exc),
                            }
                        ],
                    }
                if verify_result.get("status") not in {"PASS", "PASS_WITH_WARNING"}:
                    _remove_path(staging_dir)
                    status = _status_for_failure()
                else:
                    promotion_state: dict[str, Any] | None = None
                    try:
                        promotion_state = _promote_staging(
                            staging_dir,
                            immutable_dir,
                            active_alias,
                            overwrite=overwrite,
                            release_root=release_root_path,
                        )
                        _rebase_link_paths(created, immutable_dir)
                        try:
                            post_verify = verify_release_manifest(
                                manifest_path,
                                link_result={"created_links": created, "failed_links": failed},
                                candidate_root=immutable_dir,
                            )
                        except Exception as exc:
                            post_verify = {
                                "status": "FAILED",
                                "summary": {},
                                "issues": [
                                    {
                                        "severity": "error",
                                        "category": "verification_error",
                                        "library_name": None,
                                        "message": str(exc),
                                    }
                                ],
                            }
                        verify_result = post_verify
                        if verify_result.get("status") not in {"PASS", "PASS_WITH_WARNING"}:
                            _rollback_promotion(promotion_state)
                            promotion_state = None
                            status = _status_for_failure()
                        else:
                            verify_result["release_dir"] = str(immutable_dir)
                            verify_result["candidate_root"] = str(immutable_dir)
                            if render:
                                from lib_guard.render.release_report import render_release_html

                                verify_result["html"] = render_release_html(verify_result, run_dir)
                            _finalize_promotion(promotion_state)
                            promotion_state = None
                            status = "FORCED_APPLIED" if force else "APPLIED"
                    except Exception as exc:
                        if promotion_state is not None:
                            _rollback_promotion(promotion_state)
                        verify_result = {
                            "status": "FAILED",
                            "summary": {},
                            "issues": [
                                {
                                    "severity": "error",
                                    "category": "promotion_error",
                                    "library_name": None,
                                    "message": str(exc),
                                }
                            ],
                        }
                        failed.append(
                            {
                                "status": "FAILED",
                                "error": str(exc),
                                "relative_path": None,
                                "link_path": str(immutable_dir),
                            }
                        )
                        _remove_path(staging_dir)
                        status = _status_for_failure()
    if force and override_path:
        _write_json(
            override_path,
            {
                "schema_version": "release_override.v1",
                "force": True,
                "force_reason": force_reason or "",
                "force_by": force_by or "",
                "force_at": utc_now(),
                "apply": bool(apply),
                "dry_run": dry_run,
                "release_id": manifest.get("release_id"),
                "alias": manifest.get("alias"),
                "manifest_path": str(Path(manifest_path)),
                "review_gate_path": str(review_gate_path or ""),
                "release_check_path": str(release_check_path or ""),
                "bypassed_gate_summary": _force_gate_summary(review_gate_path, release_check_path),
                "selected_versions": _force_selected_versions(manifest),
            },
        )
    result = {
        "schema_version": "1.0",
        "release_id": manifest.get("release_id"),
        "alias": manifest.get("alias"),
        "release_root": manifest.get("release_root"),
        "release_container": str(release_root_path),
        "release_dir": str(immutable_dir),
        "staging_dir": str(staging_dir),
        "immutable_release_dir": str(immutable_dir),
        "target_alias": str(active_alias),
        "release_lock": str(_release_lock_path(release_root_path)),
        "manifest_path": str(Path(manifest_path)),
        "status": status,
        "dry_run": dry_run,
        "apply": bool(apply),
        "mode": mode,
        "overwrite": overwrite,
        "mirror_release_root": mirror_release_root,
        "force": bool(force),
        "force_reason": force_reason or "",
        "force_by": force_by if force else "",
        "override_path": str(override_path) if override_path else "",
        "verify_skipped": bool(verify_skipped),
        "verify_skip_reason": verify_skip_reason,
        "created_at": utc_now(),
        "planned_files": final_planned,
        "created_links": created,
        "removed_links": removed,
        "failed_links": failed,
        "summary": {
            "planned_files": len(planned),
            "created_files": len(created),
            "removed_files": len(removed),
            "failed_files": len(failed),
        },
        "verify": verify_result,
    }
    _write_json(run_dir / "release_link_result.json", result)
    from lib_guard.release.result import release_result_from_link

    _write_json(run_dir / "release_result.json", release_result_from_link(result))
    return result
