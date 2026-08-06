"""Release pre-check based on scan output."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping
from collections import Counter
import json

from .config import ReleasePolicy
from lib_guard.atomic import atomic_write_json
from lib_guard.summary.readiness import build_release_readiness


LEVEL_ORDER = {"L0": 0, "L1": 1, "L2": 2}


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: Any) -> None:
    atomic_write_json(path, data, lock=True)


def _issue(severity: str, category: str, title: str, message: str, files: list[str] | None = None) -> dict[str, Any]:
    return {"severity": severity, "category": category, "title": title, "message": message, "files": files or []}


class ReleaseChecker:
    def __init__(self, policy: ReleasePolicy | None = None) -> None:
        self.policy = policy or ReleasePolicy()

    def check(
        self,
        scan_dir: str | Path,
        out_dir: str | Path | None = None,
        diff_dir: str | Path | None = None,
        alias: str | None = None,
        review_gate: Mapping[str, Any] | None = None,
        review_gate_path: str | Path | None = None,
    ) -> dict[str, Any]:
        scan = Path(scan_dir)
        out = Path(out_dir) if out_dir else scan / "release"

        scan_meta = _load_json(scan / "scan_meta.json", {})
        manifest = _load_json(scan / "manifest.json", {})
        inventory = _load_json(scan / "file_inventory.json", {"files": []})
        parser_manifest = _load_json(scan / "parser_manifest.json", {"files": []})
        scan_issues = _load_json(scan / "scan_issues.json", {"issues": []})
        release_readiness = _load_json(scan / "summary" / "release_readiness.json", {})
        if not release_readiness:
            release_readiness = build_release_readiness(scan, policy_path=self.policy.to_dict())
            _write_json(scan / "summary" / "release_readiness.json", release_readiness)

        files = inventory.get("files", []) or []
        file_type_counts = Counter(str(f.get("file_type", "unknown")) for f in files)
        lib_type = str(scan_meta.get("library_type") or "unknown")
        scan_status = str(scan_meta.get("status") or "UNKNOWN")
        scan_mode = str(scan_meta.get("scan_mode") or "unknown")

        issues: list[dict[str, Any]] = []

        if release_readiness.get("bundle_status") == "BLOCK":
            issues.append(_issue("blocker", "release_readiness", "Release readiness is blocked", "One or more required component views are blocked."))
        elif release_readiness.get("bundle_status") in {"FAILED", "PASS_WITH_WARNING"}:
            issues.append(_issue("warning", "release_readiness", "Release readiness needs review", f"bundle_status={release_readiness.get('bundle_status')}"))

        if scan_status not in self.policy.allowed_scan_status:
            issues.append(_issue("blocker", "scan_status", "Scan status not allowed for release", f"scan status={scan_status}"))

        if scan_mode not in self.policy.allowed_scan_modes:
            issues.append(_issue("warning", "scan_mode", "Scan mode is not preferred for release", f"scan mode={scan_mode}"))

        required_types = self.policy.required_file_types.get(lib_type, [])
        for ft in required_types:
            if file_type_counts.get(ft, 0) <= 0:
                issues.append(_issue("blocker", "completeness", f"Missing required file type: {ft}", f"library_type={lib_type} requires {ft}"))

        parser_failed = []
        for f in parser_manifest.get("files", []) or []:
            for task in f.get("parser_tasks", []) or []:
                if str(task.get("result_status", task.get("status", ""))).upper() == "FAILED":
                    parser_failed.append(f.get("file"))
        if parser_failed and self.policy.block_on_parser_failed:
            issues.append(_issue("blocker", "parser", "Parser failures exist", f"parser failed files={len(parser_failed)}", parser_failed[:20]))

        error_issues = [i for i in scan_issues.get("issues", []) or [] if str(i.get("severity", "")).lower() in {"error", "blocker"}]
        if error_issues and self.policy.block_on_error_issue:
            issues.append(_issue("blocker", "scan_issue", "Scan has error/blocker issues", f"error/blocker issue count={len(error_issues)}"))

        signatures_dir = scan / "signatures"
        if self.policy.require_signatures and not any(signatures_dir.glob("*.json")):
            issues.append(_issue("warning", "signature", "No signature json found", "signatures/*.json not found"))

        doc_files = [f for f in files if str(f.get("file_type", "")) == "doc" or bool(f.get("is_key_doc", False))]
        doc_roles = {str(f.get("doc_type") or f.get("role") or "") for f in doc_files}
        for doc_type in self.policy.require_doc_types:
            if doc_type not in doc_roles:
                sev = "warning" if self.policy.allow_missing_docs_as_warning else "blocker"
                issues.append(_issue(sev, "doc", f"Missing recommended document: {doc_type}", f"doc_type={doc_type} not found"))

        diff_gate = self._check_diff_gate(diff_dir)
        issues.extend(diff_gate.get("issues", []))
        review_gate_data = self._load_review_gate(review_gate=review_gate, review_gate_path=review_gate_path)
        alias_gate = self._check_alias_gate(alias, release_readiness, diff_gate, review_gate_data)
        for reason in alias_gate.get("block_reasons", []):
            issues.append(_issue("blocker", "alias_gate", reason, f"alias={alias}"))

        counts = Counter(str(i.get("severity", "info")) for i in issues)
        status = "PASS"
        if counts.get("blocker", 0) > 0:
            status = "BLOCK"
        elif counts.get("error", 0) > 0:
            status = "FAILED"
        elif counts.get("warning", 0) > 0:
            status = "PASS_WITH_WARNING"

        result = {
            "schema_version": "1.0",
            "release_check_status": status,
            "scan_dir": str(scan),
            "scan_id": scan_meta.get("scan_id"),
            "library_id": scan_meta.get("library_id"),
            "library_type": lib_type,
            "library_name": scan_meta.get("library_name"),
            "version": scan_meta.get("release_version"),
            "root_path": scan_meta.get("root_path"),
            "policy": self.policy.to_dict(),
            "summary": {
                "total_files": len(files),
                "required_file_types": required_types,
                "parser_failed_files": len(parser_failed),
                "issue_counts": dict(counts),
            },
            "release_readiness": release_readiness,
            "diff_gate": diff_gate,
            "review_gate": review_gate_data,
            **alias_gate,
            "issues": issues,
        }
        out.mkdir(parents=True, exist_ok=True)
        _write_json(out / "release_check.json", result)
        from lib_guard.release.result import release_result_from_check

        _write_json(out / "release_result.json", release_result_from_check(result))
        return result

    def _load_review_gate(
        self,
        *,
        review_gate: Mapping[str, Any] | None = None,
        review_gate_path: str | Path | None = None,
    ) -> dict[str, Any]:
        if review_gate is not None:
            return dict(review_gate)
        if review_gate_path:
            loaded = _load_json(Path(review_gate_path), {})
            if isinstance(loaded, dict):
                loaded.setdefault("gate_file", str(review_gate_path))
                return loaded
        return {
            "schema_version": "review_gate.v1",
            "status": "NOT_PROVIDED",
            "blocking_open": 0,
            "attention_count": 0,
            "blocking_items": [],
            "attention_items": [],
        }

    def _check_alias_gate(
        self,
        alias: str | None,
        release_readiness: Mapping[str, Any],
        diff_gate: Mapping[str, Any],
        review_gate: Mapping[str, Any],
    ) -> dict[str, Any]:
        diff_summary = diff_gate.get("summary") if isinstance(diff_gate, Mapping) else {}
        diff_summary = diff_summary if isinstance(diff_summary, Mapping) else {}
        diff_level = str(diff_summary.get("diff_level") or release_readiness.get("diff_level") or "NONE")
        deep_diff_completed = bool(diff_summary.get("deep_diff_completed") or release_readiness.get("deep_diff_completed"))
        base_level = str(release_readiness.get("release_level_candidate") or "L0")
        actual_level = self._effective_release_level(base_level, diff_level, deep_diff_completed)

        if not alias:
            return {
                "alias": None,
                "required_release_level": None,
                "actual_release_level": actual_level,
                "diff_level": diff_level,
                "allowed_to_apply": True,
                "block_reasons": [],
            }

        gate = (self.policy.alias_gate or {}).get(alias, {})
        required_level = str(gate.get("required_release_level") or {"stage": "L0", "current": "L1", "approved": "L2"}.get(alias, "L1"))
        block_reasons: list[str] = []
        if LEVEL_ORDER.get(actual_level, 0) < LEVEL_ORDER.get(required_level, 0):
            block_reasons.append(f"{alias} requires {required_level} release level")
        if gate.get("require_diff") and diff_gate.get("status") == "NOT_PROVIDED":
            block_reasons.append(f"{alias} requires release diff")
        if gate.get("require_p2_deep_diff") and not (diff_level == "P2" and deep_diff_completed):
            block_reasons.append(f"{alias} requires P2 deep diff")
        if gate.get("require_manual_review_closed") and release_readiness.get("manual_review_items"):
            block_reasons.append(f"{alias} requires manual review closed")
        if gate.get("require_review_gate_closed") and int(review_gate.get("blocking_open", 0) or 0) > 0:
            block_reasons.append(f"{alias} requires review gate closed")
        if gate.get("require_pairwise_done"):
            for item in review_gate.get("attention_items", []) or []:
                item_id = str((item or {}).get("id") or "")
                if item_id.startswith("pairwise."):
                    block_reasons.append(f"{alias} requires pairwise file diff complete")
                    break
        if not gate.get("allow_warning", True) and release_readiness.get("bundle_status") == "PASS_WITH_WARNING":
            block_reasons.append(f"{alias} does not allow release warnings")

        return {
            "alias": alias,
            "required_release_level": required_level,
            "actual_release_level": actual_level,
            "diff_level": diff_level,
            "allowed_to_apply": not block_reasons,
            "block_reasons": block_reasons,
        }

    def _effective_release_level(self, base_level: str, diff_level: str, deep_diff_completed: bool) -> str:
        if diff_level == "P2" and deep_diff_completed and LEVEL_ORDER.get(base_level, 0) >= LEVEL_ORDER["L1"]:
            return "L2"
        return base_level

    def _check_diff_gate(self, diff_dir: str | Path | None) -> dict[str, Any]:
        if not diff_dir:
            return {"status": "NOT_PROVIDED", "issues": []}
        diff = Path(diff_dir)
        summary = _load_json(diff / "diff_summary.json", {})
        diff_issues = _load_json(diff / "diff_issues.json", {"issues": []})
        issues: list[dict[str, Any]] = []
        status = str(summary.get("status") or "UNKNOWN")
        if status == "BLOCK":
            issues.append(_issue("blocker", "diff", "Diff gate is blocked", "diff_summary.status=BLOCK"))
        elif status == "FAILED":
            issues.append(_issue("blocker", "diff", "Diff gate failed", "diff_summary.status=FAILED"))
        for item in diff_issues.get("issues", []) or []:
            severity = str(item.get("severity", "info")).lower()
            if severity in {"blocker", "error"}:
                issues.append(_issue("blocker", "diff", item.get("title", "Blocking diff issue"), item.get("message", "Diff issue requires release review")))
            elif severity == "warning" and str(item.get("category")) == "file" and "metadata" in str(item.get("title", "")).lower():
                issues.append(_issue("warning", "diff", item.get("title", "Metadata-only diff issue"), item.get("message", "Metadata-only change requires manual review")))
        return {"status": status, "diff_dir": str(diff), "summary": summary, "issue_count": len(diff_issues.get("issues", []) or []), "issues": issues}


def check_release_scan(
    scan_dir: str | Path,
    out_dir: str | Path | None = None,
    policy_path: str | Path | None = None,
    diff_dir: str | Path | None = None,
    alias: str | None = None,
    review_gate_path: str | Path | None = None,
    review_gate: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return ReleaseChecker(ReleasePolicy.from_file(policy_path)).check(
        scan_dir,
        out_dir,
        diff_dir=diff_dir,
        alias=alias,
        review_gate=review_gate,
        review_gate_path=review_gate_path,
    )


def check_effective_release(
    effective_manifest_path: str | Path,
    release_manifest_path: str | Path,
    out_dir: str | Path,
    *,
    policy_path: str | Path | None = None,
) -> dict[str, Any]:
    from lib_guard.effective.pointer import (
        default_pointer_path_for_effective,
        effective_identity_for_manifest,
        inspect_current_pointer,
        safe_name,
        sha256_file,
    )

    effective_path = Path(effective_manifest_path)
    release_path = Path(release_manifest_path)
    out = Path(out_dir)
    effective = _load_json(effective_path, {})
    issues: list[dict[str, Any]] = []
    component_checks: list[dict[str, Any]] = []

    identity = effective_identity_for_manifest(effective_path, effective)
    if not identity.get("valid"):
        issues.append(
            _issue(
                "blocker",
                "effective_identity",
                "有效组合身份校验失败",
                f"integrity_status={identity.get('integrity_status') or 'MISSING'}",
            )
        )

    conflicts = list(effective.get("conflicts", []) or [])
    if conflicts:
        issues.append(
            _issue(
                "blocker",
                "effective_conflict",
                "有效组合仍有未解决冲突",
                f"conflict_count={len(conflicts)}",
            )
        )

    pointer_path = default_pointer_path_for_effective(effective_path)
    pointer = inspect_current_pointer(pointer_path)
    if not pointer:
        issues.append(_issue("blocker", "effective_pointer", "缺少当前有效版确认记录", f"pointer={pointer_path}"))
    else:
        manifest_ref = Path(str(pointer.get("manifest") or ""))
        if not manifest_ref.is_absolute():
            manifest_ref = pointer_path.parent / manifest_ref
        pointer_checks = {
            "status": str(pointer.get("status") or ""),
            "effective_id": str(pointer.get("current_effective_id") or ""),
            "manifest_match": manifest_ref.resolve(strict=False) == effective_path.resolve(strict=False),
            "identity_status": str(pointer.get("effective_integrity_status") or ""),
            "approval_status": str(pointer.get("approval_integrity_status") or ""),
        }
        expected_id = str(effective.get("effective_id") or effective_path.parent.name)
        if pointer_checks["status"].lower() != "accepted":
            issues.append(_issue("blocker", "effective_pointer", "当前有效版尚未确认", f"status={pointer_checks['status'] or 'MISSING'}"))
        if pointer_checks["effective_id"] != expected_id:
            issues.append(
                _issue(
                    "blocker",
                    "effective_pointer",
                    "当前有效版编号与发布对象不一致",
                    f"pointer={pointer_checks['effective_id'] or 'MISSING'}, manifest={expected_id}",
                )
            )
        if not pointer_checks["manifest_match"]:
            issues.append(_issue("blocker", "effective_pointer", "当前有效版指针未指向本次发布对象", f"pointer={manifest_ref}"))
        if pointer_checks["identity_status"] != "MATCH":
            issues.append(
                _issue(
                    "blocker",
                    "effective_pointer",
                    "当前有效版指针完整性校验失败",
                    f"integrity_status={pointer_checks['identity_status'] or 'MISSING'}",
                )
            )
        if pointer_checks["approval_status"] != "MATCH":
            issues.append(
                _issue(
                    "blocker",
                    "effective_approval",
                    "当前有效版审批证据校验失败",
                    f"approval_integrity_status={pointer_checks['approval_status'] or 'MISSING'}",
                )
            )

    evidence = effective.get("version_evidence", {}) if isinstance(effective.get("version_evidence"), Mapping) else {}
    components = list(evidence.get("components", []) or [])
    effective_components = list(effective.get("components", []) or [])
    if not components:
        issues.append(_issue("blocker", "component_scan", "有效组合缺少版本扫描证据", "version_evidence.components is empty"))
    if len(components) != len(effective_components):
        issues.append(
            _issue(
                "blocker",
                "component_identity",
                "有效组合与扫描证据的组件数量不一致",
                f"effective={len(effective_components)}, evidence={len(components)}",
            )
        )
    for index, component in enumerate(components):
        if not isinstance(component, Mapping):
            issues.append(_issue("blocker", "component_scan", "版本扫描证据格式错误", f"component_index={index}"))
            continue
        version_id = str(component.get("version_id") or f"component_{index}")
        if index >= len(effective_components) or not isinstance(effective_components[index], Mapping):
            issues.append(_issue("blocker", "component_identity", "扫描证据没有对应的有效组件", f"version={version_id}"))
            continue
        expected = effective_components[index]
        expected_version = str(expected.get("version_id") or "")
        expected_role = str(expected.get("role") or "")
        if version_id != expected_version or str(component.get("role") or "") != expected_role:
            issues.append(
                _issue(
                    "blocker",
                    "component_identity",
                    "扫描证据与有效组件不一致",
                    f"index={index}, expected={expected_role}:{expected_version}, evidence={component.get('role')}:{version_id}",
                )
            )
            continue
        scan_dir = Path(str(component.get("scan_dir") or ""))
        if not str(component.get("scan_dir") or "") or not scan_dir.is_dir():
            issues.append(_issue("blocker", "component_scan", "版本扫描目录不存在", f"version={version_id}, scan_dir={scan_dir}"))
            continue
        scan_meta = _load_json(scan_dir / "scan_meta.json", {})
        expected_library_id = str(effective.get("library_id") or "")
        expected_library_name = str(effective.get("library_name") or "")
        expected_scan_library_id = f"{expected_library_id}/{expected_version}" if expected_library_id else ""
        identity_source = str(expected.get("identity_source") or "")
        if identity_source == "legacy_input_fingerprint":
            actual_snapshot = str((scan_meta.get("input_fingerprint") or {}).get("hash") or "")
        else:
            actual_snapshot = str((scan_meta.get("snapshot_identity") or {}).get("digest") or "")
        identity_mismatches = []
        if str(scan_meta.get("release_version") or "") != expected_version:
            identity_mismatches.append(f"version={scan_meta.get('release_version') or 'MISSING'}")
        if expected_scan_library_id and str(scan_meta.get("library_id") or "") != expected_scan_library_id:
            identity_mismatches.append(f"library_id={scan_meta.get('library_id') or 'MISSING'}")
        if expected_library_name and str(scan_meta.get("library_name") or "") != expected_library_name:
            identity_mismatches.append(f"library_name={scan_meta.get('library_name') or 'MISSING'}")
        if not expected.get("snapshot_digest") or actual_snapshot != str(expected.get("snapshot_digest") or ""):
            identity_mismatches.append(f"snapshot_digest={actual_snapshot or 'MISSING'}")
        if identity_mismatches:
            issues.append(
                _issue(
                    "blocker",
                    "component_identity",
                    "扫描目录身份与有效组件不一致",
                    f"expected={expected_version}; " + ", ".join(identity_mismatches),
                )
            )
            continue
        component_out = out / "components" / f"{index:03d}_{safe_name(version_id)}"
        check = check_release_scan(
            scan_dir,
            component_out,
            policy_path=policy_path,
        )
        component_status = str(check.get("release_check_status") or "")
        component_checks.append(
            {
                "version_id": version_id,
                "role": component.get("role"),
                "scan_dir": str(scan_dir),
                "release_check_status": component_status,
                "release_check": str(component_out / "release_check.json"),
            }
        )
        if component_status == "PASS_WITH_WARNING":
            issues.append(
                _issue(
                    "warning",
                    "component_scan",
                    "版本扫描通过但有警告",
                    f"version={version_id}",
                )
            )
        elif component_status != "PASS":
            issues.append(
                _issue(
                    "blocker",
                    "component_scan",
                    "版本扫描未通过发布检查",
                    f"version={version_id}, status={component_status or 'UNKNOWN'}",
                )
            )

    counts = Counter(str(item.get("severity") or "info") for item in issues)
    status = "BLOCK" if counts.get("blocker", 0) else ("PASS_WITH_WARNING" if counts.get("warning", 0) else "PASS")
    result = {
        "schema_version": "effective_release_check.v1",
        "release_check_status": status,
        "library_id": effective.get("library_id"),
        "library_name": effective.get("library_name"),
        "version": effective.get("effective_id"),
        "effective_manifest": str(effective_path),
        "effective_manifest_sha256": sha256_file(effective_path) if effective_path.is_file() else "",
        "effective_digest": identity.get("digest") or "",
        "effective_integrity_status": identity.get("integrity_status") or "MISSING",
        "current_pointer": str(pointer_path),
        "pointer_status": pointer.get("status") if pointer else "MISSING",
        "approval_integrity_status": pointer.get("approval_integrity_status") if pointer else "MISSING",
        "release_manifest": str(release_path),
        "release_manifest_sha256": sha256_file(release_path) if release_path.is_file() else "",
        "summary": {
            "component_count": len(components),
            "checked_components": len(component_checks),
            "conflict_count": len(conflicts),
            "issue_counts": dict(counts),
        },
        "component_checks": component_checks,
        "issues": issues,
    }
    out.mkdir(parents=True, exist_ok=True)
    _write_json(out / "release_check.json", result)
    from lib_guard.release.result import release_result_from_check

    release_result = release_result_from_check(result)
    release_result.update(
        {
            "manifest": str(release_path),
            "release_check": str(out / "release_check.json"),
            "effective_manifest": str(effective_path),
            "effective_digest": result["effective_digest"],
        }
    )
    _write_json(out / "release_result.json", release_result)
    return result
