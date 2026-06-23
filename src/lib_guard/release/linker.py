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

from .checker import ReleaseChecker
from .config import ReleasePolicy
from .bundle import iter_release_files, load_release_manifest, manifest_run_dir, release_dir_for, utc_now


def _load_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default
    return default


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


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

        target_version_dir = release_root_path / library_type / library_name / version
        target_alias = release_root_path / library_type / library_name / alias
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
        blocked_by_gate = check.get("release_check_status") in {"BLOCK", "FAILED"} or check.get("allowed_to_apply") is False
        blocked_by_existing_target = bool(dir_check.get("target_exists")) and not overwrite
        if blocked_by_gate and not force:
            status = "BLOCKED"
        elif blocked_by_existing_target:
            status = "BLOCKED"
        elif not dry_run:
            if link_mode == "symlink":
                self._link_symlink(source_root, target_version_dir, target_alias, overwrite=overwrite)
            elif link_mode == "copy":
                self._copy_tree(source_root, target_version_dir, target_alias, overwrite=overwrite)
            else:
                raise ValueError(f"Unsupported release link mode: {link_mode}")
            if blocked_by_gate and force:
                status = "FORCED_DONE"

        result = {
            "schema_version": "1.0",
            "status": status,
            "scan_dir": str(scan),
            "release_root": str(release_root_path),
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
        }
        if force:
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
            target_version_dir.symlink_to(source_root)

        tmp_alias = target_alias.with_name(target_alias.name + ".tmp")
        if tmp_alias.exists() or tmp_alias.is_symlink():
            tmp_alias.unlink()
        tmp_alias.symlink_to(target_version_dir)
        os.replace(tmp_alias, target_alias)

    def _copy_tree(self, source_root: Path, target_version_dir: Path, target_alias: Path, *, overwrite: bool = False) -> None:
        target_version_dir.parent.mkdir(parents=True, exist_ok=True)
        if target_version_dir.exists():
            if not overwrite:
                raise FileExistsError(f"release target already exists: {target_version_dir}")
            shutil.rmtree(target_version_dir)
        shutil.copytree(source_root, target_version_dir, symlinks=True)
        tmp_alias = target_alias.with_name(target_alias.name + ".tmp")
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


def _copy_or_link_source(source: Path, target: Path, *, mode: str, overwrite: bool) -> str:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() or target.is_symlink():
        if not overwrite:
            raise FileExistsError(f"release target already exists: {target}")
        _remove_path(target)
    if mode == "copy":
        if source.is_dir():
            shutil.copytree(source, target, symlinks=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        return "COPIED"
    if mode == "symlink":
        target.symlink_to(source, target_is_directory=source.is_dir())
        return "LINKED"
    raise ValueError(f"Unsupported release link mode: {mode}")


def _release_existing_files(release_dir: Path) -> list[Path]:
    if not release_dir.exists():
        return []
    return sorted([item for item in release_dir.rglob("*") if item.is_file() or item.is_symlink()], key=lambda p: p.as_posix().lower())


def link_release_from_manifest(
    manifest_path: str | Path,
    *,
    apply: bool = False,
    mode: str = "symlink",
    overwrite: bool = False,
    release_root: str | Path | None = None,
    alias: str | None = None,
    out_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Link a human-approved release manifest into the release area.

    This path is intentionally not a release gate. It only performs dry-run/apply
    filesystem actions and records evidence.
    """

    manifest = load_release_manifest(manifest_path, release_root=release_root, alias=alias)
    run_dir = manifest_run_dir(manifest_path, out_dir)
    dry_run = not bool(apply)
    created: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    release_dir = release_dir_for(manifest)
    release_dir.mkdir(parents=True, exist_ok=True) if apply else None
    planned = iter_release_files(manifest)
    expected_targets = {Path(str(item["target_path"])) for item in planned if item.get("target_path") and not item.get("error")}

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
            if dry_run:
                exists = target.exists() or target.is_symlink()
                item["status"] = "WOULD_REPLACE" if exists and overwrite else ("TARGET_EXISTS" if exists else "WOULD_LINK")
                if exists and not overwrite:
                    item["warning"] = "target exists; apply would fail without overwrite"
                created.append(item)
                continue
            item["status"] = _copy_or_link_source(source, target, mode=mode, overwrite=overwrite)
            created.append(item)
        except Exception as exc:
            failed_item = dict(item)
            failed_item["status"] = "FAILED"
            failed_item["error"] = str(exc)
            failed.append(failed_item)

    if apply and overwrite and not failed:
        for existing in _release_existing_files(release_dir):
            if existing in expected_targets:
                continue
            removed.append({"relative_path": existing.relative_to(release_dir).as_posix(), "path": str(existing), "status": "REMOVED"})
            _remove_path(existing)

    status = "DRY_RUN" if dry_run else ("FAILED" if failed else "APPLIED")
    result = {
        "schema_version": "1.0",
        "release_id": manifest.get("release_id"),
        "alias": manifest.get("alias"),
        "release_root": manifest.get("release_root"),
        "release_dir": str(release_dir),
        "manifest_path": str(Path(manifest_path)),
        "status": status,
        "dry_run": dry_run,
        "apply": bool(apply),
        "mode": mode,
        "overwrite": overwrite,
        "created_at": utc_now(),
        "planned_files": planned,
        "created_links": created,
        "removed_links": removed,
        "failed_links": failed,
        "summary": {
            "planned_files": len(planned),
            "created_files": len(created),
            "removed_files": len(removed),
            "failed_files": len(failed),
        },
    }
    _write_json(run_dir / "release_link_result.json", result)
    return result
