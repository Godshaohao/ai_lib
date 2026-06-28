"""Release pre-check based on scan output."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping
from collections import Counter
import json

from .config import ReleasePolicy
from lib_guard.summary.readiness import build_release_readiness


LEVEL_ORDER = {"L0": 0, "L1": 1, "L2": 2}


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
        try:
            from lib_guard.review.release_result import release_result_from_check

            _write_json(out / "release_result.json", release_result_from_check(result))
        except Exception:
            pass
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
