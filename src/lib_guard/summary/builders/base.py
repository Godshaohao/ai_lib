from __future__ import annotations

from typing import Any, Mapping


def get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(key, default)
    return getattr(obj, key, default)


def result_data(result: Any) -> dict[str, Any]:
    if isinstance(result, Mapping):
        data = result.get("data")
        return dict(data) if isinstance(data, Mapping) else dict(result)
    return {}


def result_file(result: Any) -> str:
    return str(get(result, "file", get(result, "path", "")))


def parser_matches(result: Any, *names: str) -> bool:
    parser = str(get(result, "parser_name", "")).lower()
    return any(name.lower() in parser for name in names)


def make_summary(name: str, context: Any, summary: dict[str, Any], **data: Any) -> dict[str, Any]:
    return {
        "schema_version": str(get(context, "schema_version", "1.0")),
        "scan_id": get(context, "scan_id"),
        "summary_name": name,
        "status": "PASS",
        "summary": summary,
        **data,
        "issues": [],
    }


class FormatSummaryBuilder:
    file_type = "unknown"
    parser_terms: tuple[str, ...] = ()
    object_keys: tuple[str, ...] = ()

    def __init__(self, config: Any = None) -> None:
        self.config = config

    @property
    def name(self) -> str:
        return f"{self.file_type}_summary"

    def build(self, records: list[Any], parser_results: dict[str, Any], context: Any) -> dict[str, Any]:
        files: list[dict[str, Any]] = []
        object_count = 0
        for result in (parser_results or {}).values():
            if self.parser_terms and not parser_matches(result, *self.parser_terms):
                continue
            data = result_data(result)
            count = self._object_count(data)
            object_count += count
            files.append({"file": result_file(result), "object_count": count, "status": get(result, "status", "PASS")})
        return make_summary(
            self.name,
            context,
            {"file_count": len(files), "object_count": object_count},
            files=sorted(files, key=lambda x: str(x.get("file", ""))),
        )

    def extract(self, records: list[Any], parser_results: dict[str, Any], context: Any) -> dict[str, Any]:
        return self.build(records=records, parser_results=parser_results, context=context)

    def _object_count(self, data: Mapping[str, Any]) -> int:
        stats = data.get("stats")
        if isinstance(stats, Mapping):
            counts = [v for k, v in stats.items() if str(k).endswith("_count") and isinstance(v, int)]
            if counts:
                return sum(counts)
        for key in self.object_keys:
            value = data.get(key)
            if isinstance(value, Mapping):
                return len(value)
            if isinstance(value, list):
                return len(value)
        return 0


class LefSummaryBuilder(FormatSummaryBuilder):
    file_type = "lef"
    parser_terms = ("lef",)
    object_keys = ("macros",)


class LibertySummaryBuilder(FormatSummaryBuilder):
    file_type = "liberty"
    parser_terms = ("liberty",)
    object_keys = ("cells", "libraries")


class VerilogSummaryBuilder(FormatSummaryBuilder):
    file_type = "verilog"
    parser_terms = ("verilog", "systemverilog")
    object_keys = ("modules",)


class CdlSummaryBuilder(FormatSummaryBuilder):
    file_type = "cdl"
    parser_terms = ("cdl",)
    object_keys = ("subckts", "circuits")


class SdcSummaryBuilder(FormatSummaryBuilder):
    file_type = "sdc"
    parser_terms = ("sdc",)
    object_keys = ("constraints", "clocks")


class UpfSummaryBuilder(FormatSummaryBuilder):
    file_type = "upf"
    parser_terms = ("upf",)
    object_keys = ("commands", "power_domains")


class CpfSummaryBuilder(FormatSummaryBuilder):
    file_type = "cpf"
    parser_terms = ("cpf",)
    object_keys = ("commands", "power_domains")


class SpefSummaryBuilder(FormatSummaryBuilder):
    file_type = "spef"
    parser_terms = ("spef",)
    object_keys = ("nets",)


class PackageSummaryBuilder(FormatSummaryBuilder):
    file_type = "package"
    parser_terms = ("package", "filelist")
    object_keys = ("entries", "files")


class WaiverSummaryBuilder(FormatSummaryBuilder):
    file_type = "waiver"
    parser_terms = ("waiver",)
    object_keys = ("waivers",)


class MacroSummaryBuilder(FormatSummaryBuilder):
    file_type = "macro"
    parser_terms = ("lef", "liberty")
    object_keys = ("macros", "cells")

    @property
    def name(self) -> str:
        return "macro_summary"


class PortSummaryBuilder(FormatSummaryBuilder):
    file_type = "port"
    parser_terms = ("lef", "liberty", "verilog", "cdl")
    object_keys = ("ports", "modules", "macros", "cells", "subckts")

    @property
    def name(self) -> str:
        return "port_summary"
