from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping
import time


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(key, default)
    return getattr(obj, key, default)


@dataclass
class ParserTask:
    parser_name: str
    parser_version: str
    reason: str = "selected_by_file_type"


@dataclass
class ParserExecution:
    entry: dict[str, Any]
    result: dict[str, Any] | None = None
    cache_event: dict[str, Any] | None = None
    parser_error: dict[str, Any] | None = None
    cache_hit: bool = False
    parsed: bool = False
    failed: bool = False


class ParserRegistry:
    def __init__(self, parsers: dict[str, Any]) -> None:
        self.parsers = parsers

    @classmethod
    def default(cls, config: Any = None) -> "ParserRegistry":
        from .parsers import (
            CdlParser,
            CpfParser,
            DbParser,
            FilelistParser,
            LefParser,
            LibertyParser,
            PackageParser,
            SdcParser,
            SpefParser,
            UpfParser,
            VerilogParser,
            WaiverParser,
        )

        instances = [
            LefParser(config),
            LibertyParser(config),
            VerilogParser(config),
            CdlParser(config),
            SdcParser(config),
            UpfParser(config),
            CpfParser(config),
            SpefParser(config),
            DbParser(config),
            FilelistParser(config),
            PackageParser(config),
            WaiverParser(config),
        ]
        return cls({p.parser_name: p for p in instances})

    def get(self, parser_name: str) -> Any:
        return self.parsers[parser_name]

    def all(self) -> list[Any]:
        return list(self.parsers.values())


class ParserSelector:
    def __init__(self, config: Any = None) -> None:
        self.config = config

    def select(self, record: Any, context: Any, registry: Any, cache: Any = None) -> list[ParserTask]:
        policy = getattr(context, "policy", None)
        if policy is not None and hasattr(policy, "should_parse") and not policy.should_parse(record, context):
            return []
        tasks: list[ParserTask] = []
        for parser in registry.all():
            if parser.can_parse(record, context):
                tasks.append(ParserTask(parser_name=parser.parser_name, parser_version="2.0"))
        return tasks


class ParserExecutor:
    """Parser worker adapter.

    Workers parse only. The scan runner owns cache/result/manifest commits.
    """

    def __init__(self, registry: Any, cache: Any) -> None:
        self.registry = registry
        self.cache = cache

    def execute(self, plan: dict[str, Any], record: Any, context: Any) -> ParserExecution:
        started = time.time()
        parser_name = str(plan["parser_name"])
        entry = {
            "task_id": plan["task_id"],
            "parser_name": parser_name,
            "parser_version": plan["parser_version"],
            "parser_schema_version": plan["parser_schema_version"],
            "reason": plan["reason"],
            "status": "UNKNOWN",
            "result_status": "UNKNOWN",
            "result_path": plan["result_path"],
            "cache_status": "MISS",
            "cache_used": False,
            "cache_key": plan["cache_key"],
            "cache_invalid_reason": None,
            "elapsed_ms": 0,
        }
        result: dict[str, Any] | None = None
        parser_error = None
        try:
            parser = self.registry.get(parser_name)
            result = parser.parse(record, context)
            result_status = str(result.get("status", "PASS"))
            entry.update({"status": result_status, "result_status": result_status})
            parsed = True
            failed = False
        except Exception as exc:
            entry.update({"status": "FAILED", "result_status": "FAILED", "result_path": None, "error": {"type": type(exc).__name__, "message": str(exc)}})
            parser_error = {"file": _get(record, "path"), "file_type": _get(record, "file_type"), "parser_name": parser_name, "error": str(exc)}
            parsed = False
            failed = True

        entry["elapsed_ms"] = max(0, int((time.time() - started) * 1000))
        return ParserExecution(entry=entry, result=result, cache_event=None, parser_error=parser_error, cache_hit=False, parsed=parsed, failed=failed)
