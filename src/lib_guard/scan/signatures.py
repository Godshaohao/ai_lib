from __future__ import annotations

from typing import Any, Mapping


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(key, default)
    return getattr(obj, key, default)


class SignatureBuilder:
    def __init__(self, config: Any = None) -> None:
        self.config = config

    def build(self, records: list[Any], summaries: dict[str, Any], parser_results: dict[str, Any], context: Any) -> dict[str, Any]:
        file_signatures = [
            {"path": _get(r, "path"), "file_type": _get(r, "file_type"), "hash": _get(r, "hash")}
            for r in records
            if _get(r, "hash")
        ]
        return {
            "schema_version": getattr(context, "schema_version", "1.0"),
            "status": "PASS",
            "file_signatures": file_signatures,
            "summary_names": sorted(summaries),
            "parser_result_count": len(parser_results),
        }
