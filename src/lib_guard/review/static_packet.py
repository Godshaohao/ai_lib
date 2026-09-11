"""Minimal, file-backed Review Packet workflow.

The packet is deliberately small.  ``packet.json``, ``review_items.tsv`` and
``responses/*.tsv`` are the source records; the gate and Markdown report are
rebuildable projections.  This module does not create an HTML entry point or
another release/effective state.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from lib_guard.atomic import atomic_write_json, atomic_write_text


PACKET_SCHEMA = "review_packet.v1"
GATE_SCHEMA = "review_gate.v1"
DECISIONS = {"PASS", "BLOCK", "QUESTION"}
DEFAULT_POLICY_PATH = Path(__file__).resolve().parents[3] / "configs" / "review_policy.yaml"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _valid_timestamp(value: str) -> bool:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _timestamp_key(value: str) -> float:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()


def _safe(value: Any) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "item")).strip("._")
    return text or "item"


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def _sha256_bytes(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _read_json(path: Path, default: Any = None) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _yaml_scalar(value: str) -> Any:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    if value.lower() in {"null", "~"}:
        return None
    try:
        return int(value)
    except ValueError:
        return value


def _read_simple_policy_yaml(path: Path) -> dict[str, Any]:
    """Read the fixed policy schema used by core installs without PyYAML.

    The core CLI has no third-party dependency contract; only ``version``,
    ``review_owner``, ``max_review_items`` and one-level ``routing`` are
    accepted here. Web-only Flask installation must not become a core runtime
    requirement.
    """

    data: dict[str, Any] = {}
    section: str | None = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        if "#" in raw:
            raw = raw.split("#", 1)[0]
        if not raw.strip():
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        line = raw.strip()
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().strip("\"'")
        value = value.strip()
        if indent == 0:
            section = key if not value else None
            if value:
                data[key] = _yaml_scalar(value)
            else:
                data.setdefault(key, {})
            continue
        if indent >= 2 and section == "routing":
            data.setdefault("routing", {})[key] = _yaml_scalar(value)
    return data


def _load_policy(path: str | Path | None) -> dict[str, Any]:
    policy_path = Path(path) if path else DEFAULT_POLICY_PATH
    if not policy_path.is_file():
        return {
            "version": "review-policy.v1",
            "review_owner": "library_owner",
            "max_review_items": 10,
            "routing": {"unknown": "Integration"},
        }
    try:
        import yaml
    except ModuleNotFoundError:
        loaded = _read_simple_policy_yaml(policy_path)
    else:
        try:
            loaded = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
        except Exception as exc:  # pragma: no cover - invalid admin config.
            raise ValueError(f"cannot read review policy: {policy_path}: {exc}") from exc
    if not isinstance(loaded, Mapping):
        raise ValueError(f"review policy must be a mapping: {policy_path}")
    result = dict(loaded)
    result.setdefault("version", result.get("schema_version") or "review-policy.v1")
    result.setdefault("review_owner", "library_owner")
    result.setdefault("max_review_items", 10)
    routing = result.get("routing")
    result["routing"] = dict(routing) if isinstance(routing, Mapping) else {"unknown": "Integration"}
    return result


def _policy_digest(policy: Mapping[str, Any]) -> str:
    """Return the content identity of the policy used to route this packet.

    The human-facing version is useful for audit, but is not sufficient to
    protect against an administrator changing routing in place.  Hashing the
    normalized policy makes that change create a new packet automatically.
    """

    return hashlib.sha256(_canonical(dict(policy))).hexdigest()


def _effective_policy_path(review_root: str | Path | None, policy_path: str | Path | None) -> Path | None:
    """Resolve the same admin policy for prepare/submit/collect.

    Reviewers should not have to repeat a policy path.  The packet still
    freezes the policy *version* in its identity, so changing this file makes
    the next prepare produce a new packet.
    """

    if policy_path:
        return Path(policy_path)
    if review_root:
        root = Path(review_root)
        for candidate in (
            root.parent / "review_policy.yaml",
            root.parent / "config" / "review_policy.yaml",
            root.parent / "configs" / "review_policy.yaml",
            root / "review_policy.yaml",
        ):
            if candidate.is_file():
                return candidate
    return None


def _library_matches(lib: Mapping[str, Any], token: str) -> bool:
    names = {
        str(lib.get("library_id") or ""),
        str(lib.get("library_name") or ""),
        str(lib.get("display_name") or ""),
        str(lib.get("formal_library_id") or ""),
        str(lib.get("typed_library_id") or ""),
    }
    names.update(str(item) for item in lib.get("aliases", []) or [])
    return token in names


def _find_subject(catalog: Mapping[str, Any], library: str, version: str) -> tuple[dict[str, Any], dict[str, Any]]:
    libraries = [item for item in catalog.get("libraries", []) or [] if isinstance(item, Mapping) and _library_matches(item, library)]
    if not libraries:
        raise ValueError(f"library not found in catalog: {library}")
    if len(libraries) > 1:
        raise ValueError(f"ambiguous library alias: {library}")
    lib = dict(libraries[0])
    versions = [item for item in lib.get("versions", []) or [] if str(item.get("version_id") or item.get("version_key") or "") == version]
    if not versions:
        raise ValueError(f"version not found in catalog: {version}")
    return lib, dict(versions[0])


def _scan_dir(version: Mapping[str, Any]) -> Path | None:
    scan = version.get("scan") if isinstance(version.get("scan"), Mapping) else {}
    value = scan.get("scan_dir") or version.get("scan_dir")
    return Path(str(value)) if value else None


def _manifest_path(version: Mapping[str, Any]) -> Path | None:
    scan = version.get("scan") if isinstance(version.get("scan"), Mapping) else {}
    explicit = scan.get("manifest") or scan.get("manifest_json") or version.get("manifest")
    if explicit:
        path = Path(str(explicit))
        if path.is_file():
            return path
    scan_dir = _scan_dir(version)
    candidate = scan_dir / "manifest.json" if scan_dir else None
    return candidate if candidate and candidate.is_file() else None


def _base_version_id(version: Mapping[str, Any], explicit: str | None) -> str:
    if explicit:
        return str(explicit)
    diff = version.get("diff") if isinstance(version.get("diff"), Mapping) else {}
    lineage = version.get("lineage") if isinstance(version.get("lineage"), Mapping) else {}
    for key in ("base_version", "base_version_id", "current_effective_version", "previous_effective_version"):
        if diff.get(key):
            return str(diff[key])
        if version.get(key):
            return str(version[key])
    for key in ("base", "base_candidate", "parent", "parent_candidate"):
        if lineage.get(key):
            return str(lineage[key])
    return ""


def _diff_dir(version: Mapping[str, Any]) -> Path | None:
    diff = version.get("diff") if isinstance(version.get("diff"), Mapping) else {}
    for key in ("compare_dir", "base_diff_dir", "current_effective_diff_dir", "diff_dir", "adjacent_diff_dir", "cumulative_diff_dir"):
        if diff.get(key):
            return Path(str(diff[key]))
    return None


def _compare_digest(version: Mapping[str, Any]) -> tuple[str, list[str]]:
    diff_dir = _diff_dir(version)
    if not diff_dir:
        return "MISSING", []
    names = [
        "compare_manifest.json",
        "diff_meta.json",
        "diff_summary.json",
        "view_diff.json",
        "type_diff.json",
        "file_diff.json",
        "release_evidence_diff.json",
        "diff_issues.json",
    ]
    payload: dict[str, Any] = {}
    sources: list[str] = []
    for name in names:
        path = diff_dir / name
        value = _read_json(path, None)
        if value is not None:
            payload[name] = value
            sources.append(str(path))
    if not payload:
        for path in sorted(diff_dir.glob("*.json")):
            value = _read_json(path, None)
            if value is not None:
                payload[path.name] = value
                sources.append(str(path))
    return (_sha256_bytes(payload) if payload else "MISSING"), sources


def _view_type(value: Any) -> str:
    text = str(value or "unknown").strip().lower().replace("system_verilog", "systemverilog")
    if "/" in text or "\\" in text:
        text = Path(text).suffix.removeprefix(".") or text
    aliases = {"lib": "liberty", "timing": "liberty", "rtl": "verilog", "sv": "systemverilog", "layout": "gds", "oas": "oas"}
    return aliases.get(text, text or "unknown")


def _view_rows(version: Mapping[str, Any]) -> list[dict[str, Any]]:
    diff_dir = _diff_dir(version)
    if not diff_dir:
        return []
    payload = _read_json(diff_dir / "view_diff.json", {}) or {}
    raw = payload.get("views") if isinstance(payload, Mapping) else []
    if isinstance(raw, Mapping):
        raw = [dict(value, view_type=key) if isinstance(value, Mapping) else {"view_type": key, "changed": value} for key, value in raw.items()]
    if not raw:
        type_payload = _read_json(diff_dir / "type_diff.json", {}) or {}
        raw = type_payload.get("by_type", []) if isinstance(type_payload, Mapping) else []
        if isinstance(raw, Mapping):
            raw = [dict(value, file_type=key) if isinstance(value, Mapping) else {"file_type": key, "changed": value} for key, value in raw.items()]
    if not raw:
        file_payload = _read_json(diff_dir / "file_diff.json", {}) or {}
        raw = file_payload.get("by_type", []) if isinstance(file_payload, Mapping) else []
        if isinstance(raw, Mapping):
            raw = [dict(value, file_type=key) if isinstance(value, Mapping) else {"file_type": key, "changed": value} for key, value in raw.items()]
    rows: list[dict[str, Any]] = []
    for item in raw or []:
        if not isinstance(item, Mapping):
            continue
        view = _view_type(item.get("view_type") or item.get("file_type") or item.get("type") or item.get("name"))
        counts = {key: int(item.get(key) or 0) for key in ("added", "removed", "changed")}
        if sum(counts.values()) <= 0 and str(item.get("status") or "").upper() not in {"CHANGED", "ADDED", "REMOVED"}:
            continue
        rows.append({"view_type": view, **counts})
    return sorted(rows, key=lambda row: (row["view_type"], row["added"], row["removed"], row["changed"]))


def _departments(view_type: str, policy: Mapping[str, Any]) -> list[str]:
    routing = policy.get("routing") if isinstance(policy.get("routing"), Mapping) else {}
    configured = routing.get(view_type)
    if configured is None:
        configured = routing.get("unknown") or "Integration"
    if isinstance(configured, (list, tuple, set)):
        values = [str(item).strip() for item in configured if str(item).strip()]
    else:
        values = [item.strip() for item in re.split(r"[,|]", str(configured)) if item.strip()]
    return values or ["Integration"]


def _review_items(version: Mapping[str, Any], policy: Mapping[str, Any]) -> list[dict[str, str]]:
    grouped: dict[str, list[str]] = {}
    for row in _view_rows(version):
        for department in _departments(row["view_type"], policy):
            if row["view_type"] not in grouped.setdefault(department, []):
                grouped[department].append(row["view_type"])
    max_items = max(1, int(policy.get("max_review_items") or 10))
    if len(grouped) > max_items:
        raise ValueError(f"review routing produced {len(grouped)} items; policy max is {max_items}; consolidate policy routing")
    items: list[dict[str, str]] = []
    for index, (department, views) in enumerate(sorted(grouped.items()), start=1):
        joined = ", ".join(views)
        item_id = f"review_{_safe(department).lower()}_{index:02d}"
        items.append(
            {
                "review_id": item_id,
                "department": department,
                "scope": f"view:{','.join(views)}",
                "question": f"请确认 {joined} 视图的变化满足当前使用场景，并记录必要限制。",
                "required": "true",
                "severity": "P1",
                "evidence_ref": f"Version Detail#view-delta-{_safe(views[0])}",
            }
        )
    return items


def _machine_blockers(lib: Mapping[str, Any], version: Mapping[str, Any], base_version: str, base: Mapping[str, Any] | None, target_manifest: Path | None, compare_sha: str) -> list[dict[str, str]]:
    blockers: list[dict[str, str]] = []
    scan = version.get("scan") if isinstance(version.get("scan"), Mapping) else {}
    package_type = str(version.get("package_type") or version.get("package_class") or "").upper()
    if package_type == "UNKNOWN_PACKAGE":
        blockers.append({"id": "machine.unknown_package", "reason": "版本包类型为 UNKNOWN_PACKAGE，不能进入人工审查放行。"})
    if target_manifest is None:
        blockers.append({"id": "machine.target_manifest_missing", "reason": "目标版本缺少 manifest.json，无法冻结审查对象。"})
    elif target_manifest.is_file():
        expected_manifest = str(scan.get("manifest_sha256") or version.get("manifest_sha256") or "").removeprefix("sha256:")
        if expected_manifest and expected_manifest != _sha256_file(target_manifest):
            blockers.append({"id": "machine.target_manifest_mismatch", "reason": "Catalog 记录的目标 manifest digest 与当前 manifest 不一致。"})
    if str(scan.get("status") or "").upper() in {"FAILED", "ERROR", "BLOCKED", "BLOCK"}:
        blockers.append({"id": "machine.scan_failed", "reason": f"目标版本扫描状态为 {scan.get('status')}。"})
    if not base_version:
        blockers.append({"id": "machine.base_missing", "reason": "当前对比没有可确认的 Base 版本。"})
    elif base is None:
        blockers.append({"id": "machine.base_version_missing", "reason": f"Base 版本 {base_version} 不在 Catalog 中。"})
    elif _manifest_path(base) is None:
        blockers.append({"id": "machine.base_manifest_missing", "reason": f"Base 版本 {base_version} 缺少 manifest.json。"})
    if compare_sha == "MISSING":
        blockers.append({"id": "machine.compare_missing", "reason": "当前版本没有可冻结的 compare evidence。"})
    required_views = scan.get("required_views") or version.get("required_views") or scan.get("required_file_types") or version.get("required_file_types") or []
    if isinstance(required_views, str):
        required_views = [item.strip() for item in re.split(r"[,\s]+", required_views) if item.strip()]
    if required_views and target_manifest:
        manifest = _read_json(target_manifest, {}) or {}
        raw_files = manifest.get("files", []) if isinstance(manifest, Mapping) else []
        names = []
        for entry in raw_files or []:
            if isinstance(entry, Mapping):
                names.append(_view_type(entry.get("file_type") or entry.get("view_type") or entry.get("type") or entry.get("path")))
            else:
                names.append(_view_type(entry))
        for required in required_views:
            required_type = _view_type(required)
            if not any(required_type == name or required_type in name for name in names):
                blockers.append({"id": f"machine.required_view_missing:{required_type}", "reason": f"目标 manifest 缺少必需 View：{required_type}。"})
    return blockers


def _packet_root(review_root: str | Path, lib: Mapping[str, Any], version: str, packet_id: str) -> Path:
    lib_id = str(lib.get("formal_library_id") or lib.get("library_id") or lib.get("library_name") or "library")
    return Path(review_root) / _safe(lib_id) / _safe(version) / packet_id


def _packet_descriptor(catalog: Mapping[str, Any], library: str, version_id: str, *, base_version: str | None, policy_path: str | Path | None) -> dict[str, Any]:
    lib, version = _find_subject(catalog, library, version_id)
    policy = _load_policy(policy_path)
    base_id = _base_version_id(version, base_version)
    all_versions = {str(item.get("version_id") or item.get("version_key") or ""): item for item in lib.get("versions", []) or [] if isinstance(item, Mapping)}
    base = all_versions.get(base_id) if base_id else None
    target_manifest = _manifest_path(version)
    base_manifest = _manifest_path(base) if base else None
    compare_sha, compare_sources = _compare_digest(version)
    machine_blockers = _machine_blockers(lib, version, base_id, base, target_manifest, compare_sha)
    identity = {
        "library_id": str(lib.get("formal_library_id") or lib.get("library_id") or lib.get("library_name") or library),
        "target_version": version_id,
        "target_manifest_sha256": _sha256_file(target_manifest) if target_manifest else "MISSING",
        "base_version": base_id,
        "base_manifest_sha256": _sha256_file(base_manifest) if base_manifest else ("MISSING" if base_id else "NONE"),
        "compare_sha256": compare_sha,
        "review_policy_version": str(policy.get("version") or "review-policy.v1"),
        "review_policy_sha256": _policy_digest(policy),
        "machine_facts_sha256": _sha256_bytes(machine_blockers),
    }
    packet_id = "rp_" + _sha256_bytes(identity)[:12]
    return {
        "lib": lib,
        "version": version,
        "policy": policy,
        "target_manifest": target_manifest,
        "base_manifest": base_manifest,
        "base": base,
        "base_version": base_id,
        "compare_sources": compare_sources,
        "identity": identity,
        "packet_id": packet_id,
        "items": _review_items(version, policy),
        "machine_blockers": machine_blockers,
    }


def _write_items(path: Path, items: list[Mapping[str, Any]]) -> None:
    atomic_write_text(path, _items_text(items), lock=True)


def _items_text(items: list[Mapping[str, Any]]) -> str:
    fields = ["review_id", "department", "scope", "question", "required", "severity", "evidence_ref"]
    rows = ["\t".join(fields)]
    for item in items:
        rows.append("\t".join(str(item.get(field) or "").replace("\t", " ").replace("\n", " ") for field in fields))
    return "\n".join(rows) + "\n"


def _items_digest(path: Path) -> str:
    return _sha256_text(path.read_text(encoding="utf-8")) if path.is_file() else "MISSING"


def _read_items(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise ValueError(f"review_items.tsv not found: {path}")
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle, delimiter="\t")]


def _read_responses(packet_dir: Path, packet_id: str, items_by_id: Mapping[str, Mapping[str, Any]]) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    valid: list[dict[str, str]] = []
    stale: list[dict[str, str]] = []
    invalid: list[dict[str, str]] = []
    for path in sorted((packet_dir / "responses").glob("*.tsv")):
        try:
            with path.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle, delimiter="\t"))
        except (OSError, csv.Error):
            invalid.append({"file": str(path), "reason": "无法读取响应文件"})
            continue
        if len(rows) != 1:
            invalid.append({"file": str(path), "reason": "响应文件必须恰好包含一条记录"})
            continue
        row = {str(key): str(value or "") for key, value in rows[0].items()}
        row["_file"] = str(path)
        if row.get("packet_id") != packet_id:
            stale.append({"file": str(path), "reason": "STALE_RESPONSE", "packet_id": row.get("packet_id", "")})
            continue
        review_id = row.get("review_id", "")
        decision = row.get("decision", "").upper()
        if review_id not in items_by_id or decision not in DECISIONS:
            invalid.append({"file": str(path), "reason": "review_id 或 decision 无效"})
            continue
        expected_department = str(items_by_id[review_id].get("department") or "")
        actual_department = str(row.get("department") or "")
        if actual_department and actual_department != expected_department:
            invalid.append({"file": str(path), "reason": f"department 与 review item 不一致：{actual_department} != {expected_department}"})
            continue
        if not row.get("reviewer", "").strip():
            invalid.append({"file": str(path), "reason": "reviewer 不能为空"})
            continue
        if not row.get("submitted_at", "").strip():
            invalid.append({"file": str(path), "reason": "submitted_at 不能为空"})
            continue
        if not _valid_timestamp(row.get("submitted_at", "")):
            invalid.append({"file": str(path), "reason": "submitted_at 必须是带时区的 ISO-8601 时间"})
            continue
        if decision in {"BLOCK", "QUESTION"} and not row.get("note", "").strip():
            invalid.append({"file": str(path), "reason": "BLOCK/QUESTION 必须有 note"})
            continue
        row["decision"] = decision
        valid.append(row)
    return valid, stale, invalid


def _stale_packet_responses(packet_dir: Path, active_packet_id: str) -> list[dict[str, str]]:
    """Report responses retained under older subject packets."""

    stale: list[dict[str, str]] = []
    for old_dir in sorted(packet_dir.parent.glob("rp_*")):
        if old_dir == packet_dir:
            continue
        old_packet = _read_json(old_dir / "packet.json", {}) or {}
        old_id = str(old_packet.get("packet_id") or old_dir.name)
        for response in sorted((old_dir / "responses").glob("*.tsv")):
            stale.append({"file": str(response), "reason": "STALE_RESPONSE", "packet_id": old_id, "active_packet_id": active_packet_id})
    return stale


def _latest_responses(rows: list[dict[str, str]]) -> dict[tuple[str, str], dict[str, str]]:
    latest: dict[tuple[str, str], dict[str, str]] = {}
    for row in rows:
        key = (row.get("review_id", ""), row.get("reviewer", ""))
        previous = latest.get(key)
        current_key = (_timestamp_key(row.get("submitted_at", "")), row.get("submitted_at", ""), row.get("_file", ""))
        previous_key = (_timestamp_key(previous.get("submitted_at", "")), previous.get("submitted_at", ""), previous.get("_file", "")) if previous else (-1.0, "", "")
        if current_key >= previous_key:
            latest[key] = row
    return latest


def _read_waivers(packet_dir: Path, item_ids: set[str] | None = None) -> tuple[dict[str, dict[str, str]], list[dict[str, str]]]:
    path = packet_dir / "waiver" / "override.json"
    data = _read_json(path, {}) or {}
    records = data.get("waivers", []) if isinstance(data, Mapping) else []
    valid: dict[str, dict[str, str]] = {}
    invalid: list[dict[str, str]] = []
    for item in records or []:
        if not isinstance(item, Mapping):
            invalid.append({"reason": "waiver record 不是对象"})
            continue
        review_id = str(item.get("review_id") or "")
        if not review_id or not str(item.get("authorized_by") or "").strip() or not str(item.get("reason") or "").strip():
            invalid.append({"review_id": review_id, "reason": "waiver 需要 review_id、authorized_by、reason"})
            continue
        if item_ids is not None and review_id not in item_ids:
            invalid.append({"review_id": review_id, "reason": "waiver review_id 不存在于当前 review_items.tsv"})
            continue
        valid[review_id] = {str(key): str(value or "") for key, value in item.items()}
    return valid, invalid


def _report(packet: Mapping[str, Any], gate: Mapping[str, Any]) -> str:
    lines = [
        "# 静态审查报告",
        "",
        f"- Packet：`{packet.get('packet_id')}`",
        f"- 库：`{packet.get('library_id')}`",
        f"- 目标版本：`{packet.get('target_version')}`",
        f"- Base：`{packet.get('base_version') or '无'}`",
        f"- 审查负责人：`{packet.get('review_owner') or '未配置'}`",
        f"- 当前 Gate：**{gate.get('status')}**",
        "",
        "## 机器事实",
        "",
    ]
    blockers = gate.get("machine_blockers", []) or []
    lines.extend([f"- BLOCK：{item.get('reason')}" for item in blockers] or ["- 无机器阻塞。"])
    lines.extend(["", "## 部门审查", ""])
    for item in gate.get("items", []) or []:
        lines.append(f"### {item.get('department')} / `{item.get('review_id')}`")
        lines.append(f"- 问题：{item.get('question')}")
        lines.append(f"- 当前决策：**{item.get('decision') or 'WAITING'}**")
        if item.get("reviewer"):
            lines.append(f"- Reviewer：`{item.get('reviewer')}`；提交时间：`{item.get('submitted_at')}`")
        if item.get("note"):
            lines.append(f"- 备注：{item.get('note')}")
        if item.get("waiver"):
            waiver = item["waiver"]
            lines.append(f"- 豁免：授权人 `{waiver.get('authorized_by')}`；理由：{waiver.get('reason')}")
        lines.append(f"- 证据：`{item.get('evidence_ref')}`")
        lines.append("")
    if gate.get("stale_responses"):
        lines.extend(["## 过期反馈", "", *[f"- {item.get('file')}：{item.get('reason')}" for item in gate["stale_responses"]]])
    if gate.get("invalid_responses"):
        lines.extend(["", "## 无效反馈", "", *[f"- {item.get('file')}：{item.get('reason')}" for item in gate["invalid_responses"]]])
    lines.extend(["", "## 状态说明", "", "- Evidence 负责证明，Report 负责解释，Response 负责表态。", "- 当前 Gate 是派生结果；删除 gate/report 后可由 `lg review collect` 重建。"])
    return "\n".join(lines) + "\n"


def prepare_review_packet(
    catalog: Mapping[str, Any],
    library: str,
    version: str,
    *,
    review_root: str | Path,
    policy_path: str | Path | None = None,
    base_version: str | None = None,
    review_owner: str | None = None,
) -> dict[str, Any]:
    policy_path = _effective_policy_path(review_root, policy_path)
    descriptor = _packet_descriptor(catalog, library, version, base_version=base_version, policy_path=policy_path)
    identity = descriptor["identity"]
    packet_dir = _packet_root(review_root, descriptor["lib"], version, descriptor["packet_id"])
    packet = {
        "schema_version": PACKET_SCHEMA,
        "packet_id": descriptor["packet_id"],
        **identity,
        "review_owner": review_owner or descriptor["policy"].get("review_owner") or "library_owner",
        "required_departments": sorted({item["department"] for item in descriptor["items"]}),
        "machine_blockers": descriptor["machine_blockers"],
        "compare_sources": descriptor["compare_sources"],
        "review_items_sha256": _sha256_text(_items_text(descriptor["items"])),
        "created_at": utc_now(),
    }
    packet_path = packet_dir / "packet.json"
    existing = _read_json(packet_path, None)
    if existing is not None:
        existing_identity = {key: existing.get(key) for key in identity}
        if existing_identity != identity:
            raise ValueError("packet identity changed in place; create a new packet")
        packet = dict(existing)
    else:
        packet_dir.mkdir(parents=True, exist_ok=True)
        (packet_dir / "responses").mkdir(parents=True, exist_ok=True)
        atomic_write_json(packet_path, packet, lock=True)
        _write_items(packet_dir / "review_items.tsv", descriptor["items"])
    if not (packet_dir / "review_items.tsv").is_file():
        _write_items(packet_dir / "review_items.tsv", descriptor["items"])
    elif packet.get("review_items_sha256") and _items_digest(packet_dir / "review_items.tsv") != packet.get("review_items_sha256"):
        raise ValueError("review_items.tsv is immutable for a packet; create a new packet instead")
    return {
        "status": "PASS",
        "packet_id": packet["packet_id"],
        "packet_dir": str(packet_dir),
        "packet": packet,
        "target_manifest_sha256": packet.get("target_manifest_sha256"),
        "base_manifest_sha256": packet.get("base_manifest_sha256"),
        "compare_sha256": packet.get("compare_sha256"),
        "review_items": descriptor["items"],
    }


def _active_packet(
    catalog: Mapping[str, Any],
    library: str,
    version: str,
    *,
    review_root: str | Path,
    policy_path: str | Path | None = None,
) -> tuple[dict[str, Any], Path]:
    policy_path = _effective_policy_path(review_root, policy_path)
    descriptor = _packet_descriptor(catalog, library, version, base_version=None, policy_path=policy_path)
    expected_id = descriptor["packet_id"]
    lib_key = _safe(descriptor["lib"].get("formal_library_id") or descriptor["lib"].get("library_id") or library)
    version_dir = Path(review_root) / lib_key / _safe(version)
    packet_dir = version_dir / expected_id
    packet = _read_json(packet_dir / "packet.json", None)
    if isinstance(packet, Mapping) and packet.get("packet_id") == expected_id:
        return dict(packet), packet_dir

    # A prepare may have used an explicit Base.  Reviewers should not repeat
    # that internal routing detail on every submit, so find a unique packet
    # with the same current Target/Compare/Policy identity.  If two different
    # Bases are simultaneously active, fail loudly instead of guessing.
    matches: list[tuple[dict[str, Any], Path]] = []
    for candidate_dir in sorted(version_dir.glob("rp_*")):
        candidate = _read_json(candidate_dir / "packet.json", None)
        if not isinstance(candidate, Mapping):
            continue
        if all(candidate.get(key) == descriptor["identity"].get(key) for key in ("library_id", "target_version", "target_manifest_sha256", "compare_sha256", "review_policy_version", "review_policy_sha256", "machine_facts_sha256")):
            matches.append((dict(candidate), candidate_dir))
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ValueError("当前 Target 存在多个不同 Base 的 Review Packet；请在 prepare 时固定唯一 Base 后清理歧义。")
    raise ValueError("没有当前 Review Packet；请先运行 lg review prepare。若 Target/Base/Compare 已变化，旧反馈不会复用。")


def submit_review_response(
    catalog: Mapping[str, Any],
    library: str,
    version: str,
    *,
    review_root: str | Path,
    review_id: str,
    decision: str,
    note: str = "",
    reviewer: str | None = None,
    policy_path: str | Path | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    packet, packet_dir = _active_packet(catalog, library, version, review_root=review_root, policy_path=policy_path)
    items = {item["review_id"]: item for item in _read_items(packet_dir / "review_items.tsv")}
    if review_id not in items:
        raise ValueError(f"review item not found in current packet: {review_id}")
    normalized = str(decision or "").strip().upper()
    if normalized not in DECISIONS:
        raise ValueError("decision must be PASS, BLOCK, or QUESTION")
    if normalized in {"BLOCK", "QUESTION"} and not str(note or "").strip():
        raise ValueError("BLOCK/QUESTION 必须填写 note")
    identity = str(reviewer or os.environ.get("LIB_GUARD_REVIEWER") or os.environ.get("USER") or "unknown").strip()
    if not identity:
        raise ValueError("无法确定 reviewer；请设置 LIB_GUARD_REVIEWER")
    submitted_at = now or utc_now()
    if not _valid_timestamp(str(submitted_at)):
        raise ValueError("now/submitted_at 必须是带时区的 ISO-8601 时间")
    row = {
        "schema_version": "review_response.v1",
        "packet_id": packet["packet_id"],
        "review_id": review_id,
        "department": items[review_id].get("department", ""),
        "decision": normalized,
        "note": str(note or "").strip(),
        "reviewer": identity,
        "submitted_at": submitted_at,
        "response_id": uuid.uuid4().hex,
    }
    response_dir = packet_dir / "responses"
    response_dir.mkdir(parents=True, exist_ok=True)
    response_path = response_dir / f"response_{_safe(submitted_at)}_{uuid.uuid4().hex[:8]}.tsv"
    fields = list(row)
    # Exclusive creation protects append-only semantics if two reviewers submit concurrently.
    with response_path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerow(row)
    return {"status": "PASS", "packet_id": packet["packet_id"], "response": str(response_path), "review_id": review_id, "decision": normalized}


def collect_review_packet(
    catalog: Mapping[str, Any],
    library: str,
    version: str,
    *,
    review_root: str | Path,
    policy_path: str | Path | None = None,
) -> dict[str, Any]:
    packet, packet_dir = _active_packet(catalog, library, version, review_root=review_root, policy_path=policy_path)
    items = _read_items(packet_dir / "review_items.tsv")
    items_by_id = {item.get("review_id", ""): item for item in items}
    valid, stale, invalid = _read_responses(packet_dir, str(packet["packet_id"]), items_by_id)
    stale.extend(_stale_packet_responses(packet_dir, str(packet["packet_id"])))
    latest = _latest_responses(valid)
    waivers, invalid_waivers = _read_waivers(packet_dir, set(items_by_id))
    current_by_item: dict[str, list[dict[str, str]]] = {}
    for row in latest.values():
        current_by_item.setdefault(row.get("review_id", ""), []).append(row)
    gate_items: list[dict[str, Any]] = []
    blocking: list[dict[str, Any]] = []
    waiting = False
    for item in items:
        review_id = item.get("review_id", "")
        responses = sorted(current_by_item.get(review_id, []), key=lambda row: (_timestamp_key(row.get("submitted_at", "")), row.get("reviewer", ""), row.get("_file", "")))
        decisions = [row.get("decision") for row in responses]
        has_block = "BLOCK" in decisions
        waived = has_block and review_id in waivers and bool(waivers[review_id].get("authorized_by"))
        decision = "WAIVED" if waived else ("BLOCK" if "BLOCK" in decisions else "QUESTION" if "QUESTION" in decisions else "PASS" if decisions and all(value == "PASS" for value in decisions) else "WAITING")
        row: dict[str, Any] = {**item, "decision": decision, "responses": len(responses)}
        if responses:
            latest_row = responses[-1]
            row.update({key: latest_row.get(key, "") for key in ("reviewer", "submitted_at", "note")})
            row["decisions"] = [
                {key: response.get(key, "") for key in ("reviewer", "submitted_at", "decision", "note")}
                for response in responses
            ]
        if waived:
            row["waiver"] = dict(waivers[review_id])
        if decision == "BLOCK" and not waived:
            block_response = next((response for response in responses if response.get("decision") == "BLOCK"), {})
            blocking.append({"id": review_id, "category": "human_review", "severity": item.get("severity", "P1"), "department": item.get("department", ""), "message": block_response.get("note") or row.get("question")})
        elif decision == "QUESTION":
            waiting = True
        elif decision == "WAITING" and str(item.get("required", "true")).lower() == "true":
            waiting = True
        gate_items.append(row)
    machine_blockers = list(packet.get("machine_blockers", []) or [])
    expected_item_digest = str(packet.get("review_items_sha256") or "")
    if expected_item_digest and _items_digest(packet_dir / "review_items.tsv") != expected_item_digest:
        machine_blockers.append({"id": "machine.review_items_tampered", "reason": "review_items.tsv 与 Packet 冻结摘要不一致。"})
    blocking.extend({"id": item.get("id"), "category": "machine", "severity": "P0", "message": item.get("reason")} for item in machine_blockers)
    if machine_blockers or blocking:
        status = "BLOCKED"
    elif waiting:
        status = "WAITING"
    else:
        status = "APPROVED"
    gate: dict[str, Any] = {
        "schema_version": GATE_SCHEMA,
        "packet_id": packet["packet_id"],
        "library_id": packet.get("library_id"),
        "target_version": packet.get("target_version"),
        "base_version": packet.get("base_version"),
        "review_owner": packet.get("review_owner"),
        "status": status,
        "blocking_open": len(blocking),
        "attention_count": sum(1 for item in gate_items if item.get("decision") in {"QUESTION", "WAITING"}),
        "blocking_items": blocking,
        "machine_blockers": machine_blockers,
        "items": gate_items,
        "waived_items": [{"id": key, **value} for key, value in waivers.items()],
        "stale_responses": stale,
        "stale_response_count": len(stale),
        "invalid_responses": invalid + invalid_waivers,
        "source_records": ["packet.json", "review_items.tsv", "responses/*.tsv"],
        "packet_dir": str(packet_dir),
        "gate_file": str(packet_dir / "review_gate.json"),
        "review_report": str(packet_dir / "review_report.md"),
    }
    atomic_write_json(packet_dir / "review_gate.json", gate, lock=True)
    atomic_write_text(packet_dir / "review_report.md", _report(packet, gate), lock=True)
    return {"status": status, "packet_id": packet["packet_id"], "packet_dir": str(packet_dir), **gate}


def find_static_gate(
    catalog: Mapping[str, Any],
    library: str,
    version: str,
    *,
    review_root: str | Path,
    policy_path: str | Path | None = None,
) -> dict[str, Any] | None:
    try:
        packet, packet_dir = _active_packet(catalog, library, version, review_root=review_root, policy_path=policy_path)
    except ValueError:
        return None
    gate = _read_json(packet_dir / "review_gate.json", None)
    if isinstance(gate, Mapping):
        return dict(gate)
    # prepare creates source records only.  Until collect runs, expose a
    # read-only WAITING projection so Version Detail cannot show a misleading
    # legacy READY gate.  No derived file is written here.
    blockers = list(packet.get("machine_blockers", []) or [])
    return {
        "schema_version": GATE_SCHEMA,
        "packet_id": packet.get("packet_id"),
        "library_id": packet.get("library_id"),
        "target_version": packet.get("target_version"),
        "base_version": packet.get("base_version"),
        "review_owner": packet.get("review_owner"),
        "status": "BLOCKED" if blockers else "WAITING",
        "blocking_open": len(blockers),
        "attention_count": 0 if blockers else len(_read_items(packet_dir / "review_items.tsv")),
        "blocking_items": [{"id": item.get("id"), "category": "machine", "severity": "P0", "message": item.get("reason")} for item in blockers],
        "machine_blockers": blockers,
        "items": _read_items(packet_dir / "review_items.tsv"),
        "packet_dir": str(packet_dir),
        "gate_file": str(packet_dir / "review_gate.json"),
        "review_report": str(packet_dir / "review_report.md"),
    }
