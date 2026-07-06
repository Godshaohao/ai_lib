from __future__ import annotations

from dataclasses import dataclass, field
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path
from typing import Any, Mapping
import hashlib
import json
import os
import tempfile
import time
import traceback


DOC_REVIEW_FILE_TYPES = {
    "doc",
    "readme",
    "release_note",
    "update_note",
    "changelog",
    "known_issue",
    "integration_guide",
    "delivery_note",
    "version_note",
    "waiver",
}


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _set(obj: Any, key: str, value: Any) -> None:
    if isinstance(obj, dict):
        obj[key] = value
    else:
        setattr(obj, key, value)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _input_fingerprint(records: list[dict[str, Any]]) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for record in records:
        path = str(record.get("path") or record.get("file") or record.get("rel_path") or "")
        size = record.get("size_bytes")
        mtime_ns = None
        abs_path = record.get("abs_path")
        if abs_path:
            try:
                stat = Path(str(abs_path)).stat()
                mtime_ns = stat.st_mtime_ns
                size = stat.st_size
            except OSError:
                mtime_ns = int(float(record.get("mtime") or 0) * 1_000_000_000) if record.get("mtime") is not None else None
        elif record.get("mtime") is not None:
            mtime_ns = int(float(record.get("mtime") or 0) * 1_000_000_000)
        entries.append(
            {
                "path": path,
                "size_bytes": size,
                "mtime_ns": mtime_ns,
                "file_type": str(record.get("file_type") or "unknown"),
            }
        )
    entries = sorted(
        entries,
        key=lambda item: (
            str(item.get("path") or ""),
            str(item.get("file_type") or ""),
            str(item.get("size_bytes") or ""),
            str(item.get("mtime_ns") or ""),
        ),
    )
    raw = json.dumps(entries, sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":"))
    return {
        "schema_version": "version_input_fingerprint.v1",
        "mode": "scan_inventory",
        "hash": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        "entry_count": len(entries),
        "truncated": False,
    }


def _record_path(record: Any) -> str:
    return str(_get(record, "path", ""))


def _safe_type(value: Any) -> str:
    text = str(value or "unknown").strip().lower()
    return "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in text) or "unknown"


def _is_doc_review_type(value: Any) -> bool:
    return str(value or "").strip().lower() in DOC_REVIEW_FILE_TYPES


@dataclass
class ScanContext:
    config: Any
    scan_id: str
    scan_mode: str
    root_path: Path
    out_dir: Path
    library_type: str
    library_name: str
    version: str
    tool_version: str
    schema_version: str
    started_at_ms: int = field(default_factory=_now_ms)
    policy: Any = None
    state_delta: dict[str, list[str]] = field(default_factory=dict)

    @property
    def library_id(self) -> str:
        return f"{self.library_type}/{self.library_name}/{self.version}"


@dataclass
class ScanRunResult:
    status: str
    scan_id: str
    out_dir: str
    stats: dict[str, Any]
    bundle: Any = None


@dataclass
class ScanBundle:
    scan_meta: dict[str, Any]
    manifest: dict[str, Any]
    file_inventory: dict[str, Any]
    parser_task_list: dict[str, Any]
    parser_manifest: dict[str, Any]
    parser_results: dict[str, Any]
    summaries: dict[str, Any]
    signatures: dict[str, Any]
    integrity: dict[str, Any]
    issues: dict[str, Any]
    parser_quality: dict[str, Any]
    state_delta: dict[str, Any]
    logs: dict[str, Any] = field(default_factory=dict)


@dataclass
class ScannerServices:
    file_walker: Any
    file_classifier: Any
    policy: Any
    state_store: Any
    cache: Any
    hash_manager: Any
    selector: Any
    parser_registry: Any
    signature_builder: Any
    integrity_builder: Any
    report_writer: Any


class ScanRunner:
    def __init__(self, config: Any, services: ScannerServices | None = None) -> None:
        self.config = config
        self.services = services or self._build_default_services(config)
        self.stats: dict[str, int] = {
            "total_files": 0,
            "classified_files": 0,
            "hashed_files": 0,
            "parser_tasks": 0,
            "parsed_files": 0,
            "parser_cache_hits": 0,
            "parser_failed_files": 0,
            "issues_count": 0,
            "warning_count": 0,
            "error_count": 0,
            "blocker_count": 0,
        }
        self.parser_errors: list[dict[str, Any]] = []
        self.cache_events: list[dict[str, Any]] = []
        self.progress: Any = None

    def _build_default_services(self, config: Any) -> ScannerServices:
        from .artifacts import IntegrityBuilder, ScanStateStore, SignatureBuilder
        from .cache import ScanCache
        from .inventory import FileClassifier, FileWalker, HashManager
        from .parser_engine import ParserRegistry, ParserSelector
        from .policy import ScanPolicy
        from .report import ScanReportWriter

        return ScannerServices(
            file_walker=FileWalker(config),
            file_classifier=FileClassifier(config),
            policy=ScanPolicy.from_config(config),
            state_store=ScanStateStore(config),
            cache=ScanCache(config),
            hash_manager=HashManager(config),
            selector=ParserSelector(config),
            parser_registry=ParserRegistry.default(config),
            signature_builder=SignatureBuilder(config),
            integrity_builder=IntegrityBuilder(config),
            report_writer=ScanReportWriter(config),
        )

    def run(self) -> ScanRunResult:
        context = self._context()
        context.policy = self.services.policy
        try:
            context.out_dir.mkdir(parents=True, exist_ok=True)
            from .progress import ProgressReporter

            self.progress = ProgressReporter(self.config, context)
            self.progress.event("start", "start", "scan started", total=0, done=0, active_workers=[], by_type={}, summary={})
            self.progress.stage("1/7 walk", "walking files")
            records = list(self.services.file_walker.walk(context.root_path, context=context))
            self.stats["total_files"] = len(records)
            self.progress.step("1/7 walk", len(records), len(records), "walk finished", force=True, active_workers=[], by_type={}, summary={"completed": len(records)})
            self.progress.stage("2/7 classify", "classifying files")
            records = [self.services.file_classifier.classify(r, context) for r in records]
            self.stats["classified_files"] = len(records)
            context.state_delta = self._state_delta(records, self.services.state_store.load_latest(context))
            self._annotate_delta(records, context.state_delta)
            self.progress.step("2/7 classify", len(records), len(records), "classify finished", force=True, active_workers=[], by_type={}, summary={"completed": len(records)})
            self.progress.stage("3/7 hash", "hashing files")
            self._hash_records(records, context)
            self.progress.step("3/7 hash", self.stats["hashed_files"], len(records), "hash finished", force=True, active_workers=[], by_type={}, summary={"completed": self.stats["hashed_files"]})
            self.progress.stage("4/7 parse", "planning and running parser tasks")
            parser_results, parser_manifest, parser_task_list = self._parse_records(records, context)
            summaries: dict[str, Any] = {}
            parser_quality = self._build_parser_quality(parser_manifest, parser_results, context)
            self.progress.stage("5/7 signatures", "building signatures")
            signatures = self.services.signature_builder.build(records, summaries, parser_results, context)
            self.progress.stage("6/7 integrity", "building integrity")
            integrity = self.services.integrity_builder.build(records, summaries, signatures, context)
            issues = self._issues(integrity, parser_quality, context)
            status = self._status(issues, integrity)
            self.progress.stage("7/7 write", "writing scan outputs")
            bundle = self._bundle(records, parser_task_list, parser_manifest, parser_results, summaries, signatures, integrity, issues, parser_quality, context, status)
            self.services.report_writer.write_bundle(bundle, context)
            self._build_derived_outputs(context)
            self.services.state_store.save(records, bundle, context)
            self.progress.finish(status=status, active_workers=[], by_type=self._progress_by_type_from_manifest(parser_manifest), summary=self._progress_summary_from_manifest(parser_manifest))
            return ScanRunResult(status=status, scan_id=context.scan_id, out_dir=str(context.out_dir), stats=self.stats, bundle=bundle)
        except Exception as exc:
            error = {"type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc(limit=8)}
            issues = {"schema_version": context.schema_version, "issues": [{"severity": "blocker", "category": "fatal", "title": "Scan failed", "message": str(exc)}]}
            bundle = self._bundle([], {"schema_version": context.schema_version, "scan_id": context.scan_id, "task_count": 0, "tasks": []}, {"schema_version": context.schema_version, "files": []}, {}, {}, {}, {"status": "FAILED", "issues": []}, issues, {"schema_version": context.schema_version, "status": "FAILED", "parsers": []}, context, "FAILED")
            bundle.scan_meta["error"] = error
            self.services.report_writer.write_bundle(bundle, context)
            self._build_derived_outputs(context)
            if self.progress is not None:
                self.progress.finish(status="FAILED", active_workers=[], by_type={}, summary={"failed": 1}, error=error)
            return ScanRunResult(status="FAILED", scan_id=context.scan_id, out_dir=str(context.out_dir), stats=self.stats, bundle=bundle)

    def _build_derived_outputs(self, context: ScanContext) -> None:
        from .derived import build_scan_derived_outputs

        build_scan_derived_outputs(context.out_dir)

    def _context(self) -> ScanContext:
        scan_id = str(_get(self.config, "scan_id", time.strftime("%Y%m%d_%H%M%S")))
        return ScanContext(
            config=self.config,
            scan_id=scan_id,
            scan_mode=str(_get(self.config, "scan_mode", _get(self.config, "mode", "inventory"))),
            root_path=Path(str(_get(self.config, "root_path", _get(self.config, "root", ".")))).resolve(),
            out_dir=Path(str(_get(self.config, "out_dir", _get(self.config, "out", "scan_output")))).resolve(),
            library_type=str(_get(self.config, "library_type", _get(self.config, "profile", "unknown"))),
            library_name=str(_get(self.config, "library_name", _get(self.config, "name", "unknown"))),
            version=str(_get(self.config, "version", _get(self.config, "release_version", "unknown"))),
            tool_version=str(_get(self.config, "tool_version", "0.5.0")),
            schema_version=str(_get(self.config, "schema_version", "1.0")),
        )

    def _state_delta(self, records: list[Any], previous: Any) -> dict[str, list[str]]:
        previous_files = (previous or {}).get("files", []) if isinstance(previous, Mapping) else []
        old = {str(_get(r, "path")): r for r in previous_files}
        new = {str(_get(r, "path")): r for r in records}
        added = sorted(set(new) - set(old))
        deleted = sorted(set(old) - set(new))
        changed: list[str] = []
        unchanged: list[str] = []
        for path in sorted(set(new) & set(old)):
            old_fp = (_get(old[path], "size_bytes"), _get(old[path], "mtime"))
            new_fp = (_get(new[path], "size_bytes"), _get(new[path], "mtime"))
            (unchanged if old_fp == new_fp else changed).append(path)
        return {"added": added, "deleted": deleted, "changed": changed, "unchanged": unchanged}

    def _annotate_delta(self, records: list[Any], delta: dict[str, list[str]]) -> None:
        status = {p: k for k in ("added", "changed", "unchanged") for p in delta.get(k, [])}
        for record in records:
            _set(record, "change_status", status.get(_record_path(record), "unknown"))

    def _hash_records(self, records: list[Any], context: ScanContext) -> None:
        for record in records:
            decision = self.services.policy.hash_decision(record, context)
            _set(record, "hash_policy", decision.get("policy"))
            _set(record, "hash_reason", decision.get("reason"))
            if not decision.get("should_hash"):
                _set(record, "hash", None)
                _set(record, "sha256", None)
                _set(record, "hash_status", decision.get("hash_status", "NOT_REQUIRED"))
                _set(record, "is_large_hash_skipped", decision.get("hash_status") == "SKIPPED_BY_SMART_POLICY")
                continue
            hash_value = self.services.hash_manager.compute(record, context)
            _set(record, "hash", hash_value)
            _set(record, "sha256", hash_value.replace("sha256:", "", 1) if isinstance(hash_value, str) else hash_value)
            _set(record, "hash_status", decision.get("hash_status", "CALCULATED"))
            _set(record, "is_large_hash_skipped", False)
            self.stats["hashed_files"] += 1

    def _parse_records(self, records: list[Any], context: ScanContext) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        from .parser_engine import ParserExecutor

        executor = ParserExecutor(self.services.parser_registry, self.services.cache)
        parser_results: dict[str, Any] = {}
        manifest = {"schema_version": context.schema_version, "scan_id": context.scan_id, "files": []}
        parser_task_list, planned_by_file = self._build_parser_task_list(records, context)
        self._write_incremental_json(context.out_dir / "parser_task_list.json", parser_task_list)
        progress_state = self._new_parse_progress_state(parser_task_list)
        self._emit_parse_progress("stage_start", "parser task list frozen", progress_state, force=True)
        parse_jobs = max(1, min(int(parser_task_list.get("parse_jobs", 1) or 1), 16))
        outcomes = self._execute_parser_plans(records, planned_by_file, context, executor, progress_state, parse_jobs)
        for record in records:
            file_entry = {"file": _record_path(record), "file_type": _get(record, "file_type"), "parser_tasks": []}
            plans = planned_by_file.get(_record_path(record), [])
            for plan in plans:
                execution = outcomes[str(plan["task_id"])]
                entry = execution.entry
                if execution.result is not None and entry.get("result_path"):
                    parser_results[str(entry["result_path"])] = execution.result
                file_entry["parser_tasks"].append(entry)
            if not plans:
                file_entry["parser_tasks"].append({"parser_name": None, "status": "SKIPPED", "result_status": "SKIPPED", "result_path": None, "cache_status": "NOT_APPLICABLE", "cache_used": False, "elapsed_ms": 0})
            manifest["files"].append(file_entry)
        self._write_incremental_json(context.out_dir / "parser_manifest.json", manifest)
        self._emit_parse_progress("stage_finish", "parser stage finished", progress_state, force=True)
        return parser_results, manifest, parser_task_list

    def _execute_parser_plans(
        self,
        records: list[Any],
        planned_by_file: dict[str, list[dict[str, Any]]],
        context: ScanContext,
        executor: Any,
        progress_state: dict[str, Any],
        parse_jobs: int,
    ) -> dict[str, Any]:
        record_by_file = {_record_path(record): record for record in records}
        all_plans = [plan for record in records for plan in planned_by_file.get(_record_path(record), [])]
        outcomes: dict[str, Any] = {}
        misses: list[tuple[dict[str, Any], Any]] = []

        for index, plan in enumerate(all_plans, start=1):
            self.stats["parser_tasks"] += 1
            record = record_by_file[str(plan["file"])]
            cached = self.services.cache.get_parser_result(str(plan["cache_key"]), task=plan, record=record, context=context)
            if cached is not None:
                self._parse_progress_task_start(plan, progress_state, worker_id=f"parser-cache-{index}")
                execution = self._cached_execution(plan, record, cached)
                outcomes[str(plan["task_id"])] = execution
                self._commit_execution(plan, record, execution, context)
                self._emit_parse_progress("task_cache_hit", "parser cache hit", progress_state, task=plan, force=True)
                self._parse_progress_task_finish(plan, execution.entry, progress_state)
            else:
                misses.append((plan, record))

        if not misses:
            return outcomes

        if parse_jobs <= 1 or len(misses) == 1:
            for index, (plan, record) in enumerate(misses, start=1):
                self._parse_progress_task_start(plan, progress_state, worker_id=f"parser-{index}")
                execution = executor.execute(plan, record, context)
                outcomes[str(plan["task_id"])] = execution
                self._commit_execution(plan, record, execution, context)
                self._parse_progress_task_finish(plan, execution.entry, progress_state)
            return outcomes

        max_workers = min(parse_jobs, len(misses))
        future_to_plan: dict[Any, tuple[dict[str, Any], Any]] = {}
        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="lib_guard_parser") as pool:
            pending = iter(enumerate(misses, start=1))

            def submit_next() -> bool:
                try:
                    index, (plan, record) = next(pending)
                except StopIteration:
                    return False
                worker_id = f"parser-{((len(future_to_plan)) % max_workers) + 1}"
                self._parse_progress_task_start(plan, progress_state, worker_id=worker_id)
                future = pool.submit(executor.execute, plan, record, context)
                future_to_plan[future] = (plan, record)
                return True

            for _ in range(max_workers):
                if not submit_next():
                    break

            while future_to_plan:
                done, _pending = wait(future_to_plan, return_when=FIRST_COMPLETED)
                for future in done:
                    plan, record = future_to_plan.pop(future)
                    try:
                        execution = future.result()
                    except Exception as exc:
                        execution = self._failed_execution(plan, record, exc)
                    outcomes[str(plan["task_id"])] = execution
                    self._commit_execution(plan, record, execution, context)
                    self._parse_progress_task_finish(plan, execution.entry, progress_state)
                    submit_next()
        return outcomes

    def _cached_execution(self, plan: dict[str, Any], record: Any, cached: dict[str, Any]) -> Any:
        from .parser_engine import ParserExecution

        result_status = str(cached.get("status", "PASS") if isinstance(cached, Mapping) else "PASS")
        entry = {
            "task_id": plan["task_id"],
            "parser_name": plan["parser_name"],
            "parser_version": plan["parser_version"],
            "parser_schema_version": plan["parser_schema_version"],
            "reason": plan["reason"],
            "status": result_status,
            "result_status": result_status,
            "result_path": plan["result_path"],
            "cache_status": "HIT",
            "cache_used": True,
            "cache_key": plan["cache_key"],
            "cache_invalid_reason": None,
            "elapsed_ms": 0,
        }
        return ParserExecution(entry=entry, result=cached, cache_event={"event": "hit", "file": _record_path(record), "parser_name": plan["parser_name"]}, cache_hit=True)

    def _failed_execution(self, plan: dict[str, Any], record: Any, exc: Exception) -> Any:
        from .parser_engine import ParserExecution

        entry = {
            "task_id": plan["task_id"],
            "parser_name": plan["parser_name"],
            "parser_version": plan["parser_version"],
            "parser_schema_version": plan["parser_schema_version"],
            "reason": plan["reason"],
            "status": "FAILED",
            "result_status": "FAILED",
            "result_path": None,
            "cache_status": "MISS",
            "cache_used": False,
            "cache_key": plan["cache_key"],
            "cache_invalid_reason": None,
            "elapsed_ms": 0,
            "error": {"type": type(exc).__name__, "message": str(exc)},
        }
        return ParserExecution(
            entry=entry,
            parser_error={"file": _record_path(record), "file_type": _get(record, "file_type"), "parser_name": plan["parser_name"], "error": str(exc)},
            failed=True,
        )

    def _commit_execution(self, plan: dict[str, Any], record: Any, execution: Any, context: ScanContext) -> None:
        if execution.result is not None and execution.entry.get("result_path"):
            self._write_incremental_json(context.out_dir / str(execution.entry["result_path"]), execution.result)
        if execution.cache_hit:
            self.stats["parser_cache_hits"] += 1
            if execution.cache_event:
                self.cache_events.append(execution.cache_event)
            return
        if execution.parsed:
            self.stats["parsed_files"] += 1
            if execution.result is not None:
                self.services.cache.put_parser_result(str(plan["cache_key"]), execution.result, task=plan, record=record, context=context)
        if execution.failed:
            if execution.parser_error:
                self.parser_errors.append(execution.parser_error)
            self.stats["parser_failed_files"] += 1

    def _write_incremental_json(self, path: str | Path, data: Any) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=p.name, suffix=".tmp", dir=str(p.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2, ensure_ascii=False, default=str)
                fh.write("\n")
            os.replace(tmp_name, p)
        finally:
            try:
                if os.path.exists(tmp_name):
                    os.remove(tmp_name)
            except OSError:
                pass

    def _build_parser_task_list(self, records: list[Any], context: ScanContext) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
        tasks: list[dict[str, Any]] = []
        by_file: dict[str, list[dict[str, Any]]] = {}
        parser_schema_version = "1.0"
        parse_jobs = int(_get(self.config, "parse_jobs", 1) or 1)
        for record in records:
            selected = self.services.selector.select(record, context, self.services.parser_registry, self.services.cache)
            for task in selected:
                result_path = self._parser_result_path(record, task)
                cache_key = self._parser_cache_key(record, task, parser_schema_version, context)
                plan = {
                    "task_id": self._parser_task_id(record, task),
                    "file": _record_path(record),
                    "abs_path": _get(record, "abs_path"),
                    "file_type": _get(record, "file_type"),
                    "parser_name": task.parser_name,
                    "parser_version": task.parser_version,
                    "parser_schema_version": parser_schema_version,
                    "cache_key": cache_key,
                    "cache_status_planned": "PENDING",
                    "reason": task.reason,
                    "priority": self._parser_task_priority(record),
                    "estimated_cost": self._parser_task_estimated_cost(record),
                    "result_path": result_path,
                }
                tasks.append(plan)
                by_file.setdefault(_record_path(record), []).append(plan)
        by_type: dict[str, int] = {}
        for task in tasks:
            ft = str(task.get("file_type", "unknown"))
            by_type[ft] = by_type.get(ft, 0) + 1
        return (
            {
                "schema_version": context.schema_version,
                "scan_id": context.scan_id,
                "parse_jobs": parse_jobs,
                "task_count": len(tasks),
                "by_type": dict(sorted(by_type.items())),
                "tasks": tasks,
            },
            by_file,
        )

    def _parser_task_id(self, record: Any, task: Any) -> str:
        digest = hashlib.sha256(f"{_record_path(record)}::{task.parser_name}".encode("utf-8")).hexdigest()[:16]
        return f"PT-{digest}"

    def _parser_task_priority(self, record: Any) -> int:
        file_type = str(_get(record, "file_type", "unknown"))
        if file_type in {"lef", "liberty", "verilog"}:
            return 10
        if file_type in {"cdl", "sdc", "upf", "cpf"}:
            return 30
        if file_type in {"spef", "sdf"}:
            return 70
        return 50

    def _parser_task_estimated_cost(self, record: Any) -> str:
        size = int(_get(record, "size_bytes", 0) or 0)
        if size > 100 * 1024 * 1024:
            return "high"
        if size > 10 * 1024 * 1024:
            return "medium"
        return "low"

    def _parser_result_path(self, record: Any, task: Any) -> str:
        file_type = _safe_type(_get(record, "file_type", "unknown"))
        digest_payload = f"{_record_path(record)}::{task.parser_name}"
        digest = hashlib.sha256(digest_payload.encode("utf-8")).hexdigest()[:16]
        return f"parser_results/{file_type}/{digest}.json"

    def _parser_cache_key(self, record: Any, task: Any, parser_schema_version: str, context: ScanContext) -> str:
        parser_config_hash = self._parser_config_hash(context)
        parts = {
            "cache_namespace": "parser_v2",
            "parser_name": task.parser_name,
            "parser_version": task.parser_version,
            "parser_schema_version": parser_schema_version,
            "parser_config_hash": parser_config_hash,
            "file_hash": _get(record, "hash", _record_path(record)),
            "mtime": _get(record, "mtime"),
        }
        return "|".join(f"{key}={parts[key]}" for key in sorted(parts))

    def _parser_config_hash(self, context: ScanContext) -> str:
        payload = {
            "scan_mode": context.scan_mode,
            "schema_version": context.schema_version,
            "tool_version": context.tool_version,
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def _new_parse_progress_state(self, parser_task_list: dict[str, Any]) -> dict[str, Any]:
        by_type = {
            str(file_type): {"done": 0, "total": int(total), "failed": 0, "pass_empty": 0, "cache_hit": 0}
            for file_type, total in (parser_task_list.get("by_type") or {}).items()
        }
        total = int(parser_task_list.get("task_count", 0) or 0)
        return {
            "total": total,
            "done": 0,
            "running": 0,
            "failed": 0,
            "pass_empty": 0,
            "cache_hit": 0,
            "active_workers": [],
            "slowest_files": [],
            "by_type": by_type,
        }

    def _parse_progress_task_start(self, task: dict[str, Any], state: dict[str, Any], *, worker_id: str = "parser-1") -> None:
        state["running"] = int(state.get("running", 0)) + 1
        active = [worker for worker in state.get("active_workers", []) if worker.get("task_id") != task.get("task_id")]
        active.append(
            {
                "worker_id": worker_id,
                "task_id": task.get("task_id"),
                "parser_name": task.get("parser_name"),
                "file": task.get("file"),
                "file_type": task.get("file_type"),
                "start_time": _now_ms(),
                "elapsed_seconds": 0,
                "cache_status": task.get("cache_status_planned", "MISS"),
            }
        )
        state["active_workers"] = active
        self._emit_parse_progress("task_start", "parser task started", state, task=task, force=True)

    def _parse_progress_task_finish(self, task: dict[str, Any], entry: dict[str, Any], state: dict[str, Any]) -> None:
        file_type = str(task.get("file_type", "unknown"))
        by_type = state.setdefault("by_type", {})
        typed = by_type.setdefault(file_type, {"done": 0, "total": 0, "failed": 0, "pass_empty": 0, "cache_hit": 0})
        status = str(entry.get("result_status", entry.get("status", "UNKNOWN"))).upper()
        state["done"] = int(state.get("done", 0)) + 1
        state["running"] = max(0, int(state.get("running", 0)) - 1)
        typed["done"] = int(typed.get("done", 0)) + 1
        if status == "FAILED":
            state["failed"] = int(state.get("failed", 0)) + 1
            typed["failed"] = int(typed.get("failed", 0)) + 1
            event_type = "task_failed"
        else:
            event_type = "task_finish"
        if status == "PASS_EMPTY":
            state["pass_empty"] = int(state.get("pass_empty", 0)) + 1
            typed["pass_empty"] = int(typed.get("pass_empty", 0)) + 1
        if entry.get("cache_status") == "HIT":
            state["cache_hit"] = int(state.get("cache_hit", 0)) + 1
            typed["cache_hit"] = int(typed.get("cache_hit", 0)) + 1
        state["active_workers"] = [worker for worker in state.get("active_workers", []) if worker.get("task_id") != task.get("task_id")]
        slow = {
            "file": task.get("file"),
            "file_type": file_type,
            "parser_name": task.get("parser_name"),
            "elapsed_ms": int(entry.get("elapsed_ms", 0) or 0),
            "status": status,
        }
        slowest = list(state.get("slowest_files", [])) + [slow]
        state["slowest_files"] = sorted(slowest, key=lambda x: int(x.get("elapsed_ms", 0)), reverse=True)[:10]
        self._emit_parse_progress(event_type, "parser task finished", state, task=task, result_status=status, force=True)

    def _emit_parse_progress(self, event_type: str, message: str, state: dict[str, Any], *, task: dict[str, Any] | None = None, result_status: str | None = None, force: bool = False) -> None:
        if self.progress is None:
            return
        total = int(state.get("total", 0) or 0)
        done = int(state.get("done", 0) or 0)
        summary = {
            "queued": max(0, total - done - int(state.get("running", 0) or 0)),
            "running": int(state.get("running", 0) or 0),
            "completed": done,
            "failed": int(state.get("failed", 0) or 0),
            "pass_empty": int(state.get("pass_empty", 0) or 0),
            "cache_hit": int(state.get("cache_hit", 0) or 0),
        }
        percent = round(done * 100.0 / total, 2) if total else 100.0
        self.progress.event(
            event_type,
            "4/7 parse",
            message,
            done=done,
            total=total,
            percent=percent,
            active_workers=list(state.get("active_workers", [])),
            by_type=state.get("by_type", {}),
            summary=summary,
            slowest_files=state.get("slowest_files", []),
            task=task,
            result_status=result_status,
        )

    def _progress_by_type_from_manifest(self, parser_manifest: dict[str, Any]) -> dict[str, Any]:
        by_type: dict[str, dict[str, int]] = {}
        for file_entry in parser_manifest.get("files", []) or []:
            file_type = str(file_entry.get("file_type", "unknown"))
            for task in file_entry.get("parser_tasks", []) or []:
                if not task.get("parser_name"):
                    continue
                item = by_type.setdefault(file_type, {"done": 0, "total": 0, "failed": 0, "pass_empty": 0, "cache_hit": 0})
                item["total"] += 1
                item["done"] += 1
                status = str(task.get("result_status", task.get("status", ""))).upper()
                if status == "FAILED":
                    item["failed"] += 1
                if status == "PASS_EMPTY":
                    item["pass_empty"] += 1
                if task.get("cache_status") == "HIT":
                    item["cache_hit"] += 1
        return dict(sorted(by_type.items()))

    def _progress_summary_from_manifest(self, parser_manifest: dict[str, Any]) -> dict[str, int]:
        by_type = self._progress_by_type_from_manifest(parser_manifest)
        completed = sum(item["done"] for item in by_type.values())
        return {
            "queued": 0,
            "running": 0,
            "completed": completed,
            "failed": sum(item["failed"] for item in by_type.values()),
            "pass_empty": sum(item["pass_empty"] for item in by_type.values()),
            "cache_hit": sum(item["cache_hit"] for item in by_type.values()),
        }

    def _build_parser_quality(self, parser_manifest: dict[str, Any], parser_results: dict[str, Any], context: ScanContext) -> dict[str, Any]:
        by_parser: dict[str, dict[str, Any]] = {}
        for file_entry in parser_manifest.get("files", []) or []:
            file_type = str(file_entry.get("file_type", "unknown"))
            for task in file_entry.get("parser_tasks", []) or []:
                if not task.get("parser_name"):
                    continue
                parser_name = task.get("parser_name")
                item = by_parser.setdefault(
                    parser_name,
                    {
                        "file_type": file_type,
                        "file_types": [],
                        "parser_name": parser_name,
                        "parser_version": task.get("parser_version"),
                        "file_count": 0,
                        "parsed_count": 0,
                        "cache_hit_count": 0,
                        "failed_count": 0,
                        "pass_empty_count": 0,
                        "object_count": 0,
                        "issues": [],
                        "examples": [],
                    },
                )
                if file_type not in item["file_types"]:
                    item["file_types"].append(file_type)
                item["file_count"] += 1
                if task.get("cache_status") == "HIT":
                    item["cache_hit_count"] += 1
                status = str(task.get("result_status", task.get("status", "UNKNOWN"))).upper()
                if status == "FAILED":
                    item["failed_count"] += 1
                    item["issues"].append({"severity": "error", "message": "Parser failed", "file": file_entry.get("file")})
                elif status == "PASS_EMPTY":
                    item["parsed_count"] += 1
                    item["pass_empty_count"] += 1
                    item["issues"].append({"severity": "warning", "message": "Parser returned PASS_EMPTY", "file": file_entry.get("file")})
                elif status in {"PASS", "METADATA_ONLY"}:
                    item["parsed_count"] += 1
                result = parser_results.get(task.get("result_path")) if task.get("result_path") else None
                if isinstance(result, Mapping):
                    item["object_count"] += int(((result.get("stats") or {}).get("object_count") or 0))
                if len(item["examples"]) < 5:
                    item["examples"].append(file_entry.get("file"))

        parsers: list[dict[str, Any]] = []
        for item in by_parser.values():
            total = max(int(item["file_count"]), 1)
            penalty = int(item["failed_count"]) * 50 + int(item["pass_empty_count"]) * 25
            item["quality_score"] = max(0, 100 - int(penalty / total))
            if item["failed_count"]:
                item["status"] = "FAILED"
                item["recommended_action"] = "Inspect parser errors and rerun scan with cache skipped."
            elif item["pass_empty_count"]:
                item["status"] = "PASS_WITH_WARNING"
                item["recommended_action"] = "Review PASS_EMPTY files and confirm whether parser coverage is expected."
            else:
                item["status"] = "PASS" if item["parsed_count"] else "SKIPPED"
                item["recommended_action"] = None
            parsers.append(item)
        overall = "FAILED" if any(p["status"] == "FAILED" for p in parsers) else "PASS_WITH_WARNING" if any(p["pass_empty_count"] for p in parsers) else "PASS"
        return {"schema_version": context.schema_version, "scan_id": context.scan_id, "status": overall, "parsers": sorted(parsers, key=lambda x: str(x.get("parser_name")))}

    def _issues(self, integrity: dict[str, Any], parser_quality: dict[str, Any], context: ScanContext) -> dict[str, Any]:
        issues = list(integrity.get("issues", [])) if isinstance(integrity, dict) else []
        for err in self.parser_errors:
            if _is_doc_review_type(err.get("file_type")):
                issues.append({"severity": "error" if context.scan_mode == "release" else "warning", "category": "parser", "title": "Document parser failed", "message": err["error"], "files": [err["file"]]})
        for parser in parser_quality.get("parsers", []) or []:
            file_types = parser.get("file_types", []) or [parser.get("file_type")]
            if int(parser.get("pass_empty_count") or 0) and any(_is_doc_review_type(t) for t in file_types):
                issues.append({"severity": "warning", "category": "parser_quality", "title": "Document parser returned PASS_EMPTY", "message": f"{parser.get('parser_name')} produced empty document parser results", "files": parser.get("examples", [])})
        counts = {"info": 0, "warning": 0, "error": 0, "blocker": 0}
        for issue in issues:
            sev = str(issue.get("severity", "info")).lower()
            counts[sev] = counts.get(sev, 0) + 1
        self.stats["issues_count"] = len(issues)
        self.stats["warning_count"] = counts.get("warning", 0)
        self.stats["error_count"] = counts.get("error", 0)
        self.stats["blocker_count"] = counts.get("blocker", 0)
        return {"schema_version": context.schema_version, "scan_id": context.scan_id, "issues": issues, "summary": counts}

    def _status(self, issues: dict[str, Any], integrity: dict[str, Any]) -> str:
        counts = issues.get("summary", {})
        if counts.get("blocker", 0):
            return "BLOCK"
        if counts.get("error", 0):
            return "FAILED"
        if counts.get("warning", 0):
            return "PASS_WITH_WARNING"
        if str(integrity.get("status", "")).upper() in {"BLOCK", "FAILED"}:
            return str(integrity.get("status")).upper()
        return "PASS"

    def _bundle(
        self,
        records: list[Any],
        parser_task_list: dict[str, Any],
        parser_manifest: dict[str, Any],
        parser_results: dict[str, Any],
        summaries: dict[str, Any],
        signatures: dict[str, Any],
        integrity: dict[str, Any],
        issues: dict[str, Any],
        parser_quality: dict[str, Any],
        context: ScanContext,
        status: str,
    ) -> ScanBundle:
        inventory_files = [dict(r) if isinstance(r, dict) else dict(r.__dict__) for r in records]
        from .inventory import corner_filename_summary

        corner_summary = corner_filename_summary(inventory_files)
        fingerprint = _input_fingerprint(inventory_files)
        meta = {
            "schema_version": context.schema_version,
            "tool": "lib_guard",
            "tool_version": context.tool_version,
            "stage": "scan",
            "scan_id": context.scan_id,
            "scan_mode": context.scan_mode,
            "library_id": context.library_id,
            "library_type": context.library_type,
            "library_name": context.library_name,
            "release_version": context.version,
            "root_path": str(context.root_path),
            "out_dir": str(context.out_dir),
            "status": status,
            "package_type": _get(context.config, "package_type", None),
            "update_scope": _get(context.config, "update_scope", None),
            "standalone": _get(context.config, "standalone", None),
            "base_required": _get(context.config, "base_required", None),
            "base_version": _get(context.config, "base_version", None),
            "version_kind": self._version_kind(inventory_files, context),
            "base_version_source": "CONFIG" if _get(context.config, "base_version", None) else "AUTO_CATALOG_OR_UNSET",
            "input_fingerprint": fingerprint,
            "hash_policy": self._hash_policy(inventory_files),
            "started_at_ms": context.started_at_ms,
            "finished_at_ms": _now_ms(),
            "stats": self.stats,
        }
        manifest = {
            "schema_version": context.schema_version,
            "scan_id": context.scan_id,
            "library_id": context.library_id,
            "scan_mode": context.scan_mode,
            "status": status,
            "summary": {
                "total_files": len(inventory_files),
                "parser_tasks": self.stats["parser_tasks"],
                "parsed_files": self.stats["parsed_files"],
                "parser_cache_hits": self.stats["parser_cache_hits"],
                "issues_count": self.stats["issues_count"],
            },
            "file_type_counts": self._counts(inventory_files, "file_type"),
            "corner_filename_summary": corner_summary,
            "hash_policy": meta["hash_policy"],
            "version_profile": {
                "version_kind": meta["version_kind"],
                "base_version": meta["base_version"],
                "base_version_source": meta["base_version_source"],
            },
        }
        return ScanBundle(
            scan_meta=meta,
            manifest=manifest,
            file_inventory={"schema_version": context.schema_version, "scan_id": context.scan_id, "root_path": str(context.root_path), "files": inventory_files, "corner_filename_summary": corner_summary, "input_fingerprint": fingerprint},
            parser_task_list=parser_task_list,
            parser_manifest=parser_manifest,
            parser_results=parser_results,
            summaries=summaries,
            signatures=signatures,
            integrity=integrity,
            issues=issues,
            parser_quality=parser_quality,
            state_delta={"schema_version": context.schema_version, "scan_id": context.scan_id, **context.state_delta},
            logs={"parser_errors": self.parser_errors, "cache_events": self.cache_events},
        )

    def _counts(self, items: list[dict[str, Any]], key: str) -> dict[str, int]:
        out: dict[str, int] = {}
        for item in items:
            value = str(item.get(key, "unknown"))
            out[value] = out.get(value, 0) + 1
        return dict(sorted(out.items()))

    def _hash_policy(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        statuses = self._counts(records, "hash_status")
        skipped_types = sorted({str(item.get("file_type")) for item in records if item.get("hash_status") == "SKIPPED_BY_SMART_POLICY"})
        policies = sorted({str(item.get("hash_policy") or "unknown") for item in records})
        return {
            "policy": "smart" if "smart" in policies else (policies[0] if policies else "unknown"),
            "statuses": statuses,
            "skipped_file_types": skipped_types,
            "small_file_sha256": statuses.get("CALCULATED", 0),
            "skipped_content_hash": statuses.get("SKIPPED_BY_SMART_POLICY", 0),
        }

    def _version_kind(self, records: list[dict[str, Any]], context: ScanContext) -> str:
        explicit = _get(context.config, "version_kind", None) or _get(context.config, "package_type", None)
        if explicit:
            text = str(explicit).lower()
            if "doc" in text:
                return "doc_only"
            if "patch" in text:
                return "overlay_patch"
            if "partial" in text:
                return "partial"
            if "full" in text:
                return "full"
        counts = self._counts(records, "file_type")
        if counts.get("doc", 0) and sum(v for k, v in counts.items() if k not in {"doc", "waiver", "package"}) == 0:
            return "doc_only"
        has_impl = any(counts.get(t, 0) for t in ["verilog", "lef", "liberty", "db", "gds", "cdl"])
        has_release_doc = any(item.get("is_key_doc") or item.get("file_type") == "waiver" for item in records)
        if has_impl and has_release_doc:
            return "full"
        if has_impl:
            return "partial"
        return "unknown"


def run_scan(config: Any) -> ScanRunResult:
    return ScanRunner(config).run()
