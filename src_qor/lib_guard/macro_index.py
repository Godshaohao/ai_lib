"""Build a provenance-aware Macro-to-View index from a selected file map."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


VIEWS = ("lef", "liberty", "gds", "cdl", "db", "verilog")
_VIEW_ALIASES = {
    "lib": "liberty", "liberty": "liberty", "lef": "lef", "gds": "gds",
    "cdl": "cdl", "db": "db", "verilog": "verilog", "rtl": "verilog",
    "systemverilog": "verilog", "sv": "verilog", "v": "verilog",
}


def _view(value: Any) -> str:
    text = str(value or "").strip().lower()
    return _VIEW_ALIASES.get(text, text)


def _fact_items(parser_facts: Any) -> Iterable[dict[str, Any]]:
    if isinstance(parser_facts, dict):
        values = parser_facts.values()
    elif isinstance(parser_facts, list):
        values = parser_facts
    else:
        return ()
    return (item for item in values if isinstance(item, dict))


def _fact_identity(fact: dict[str, Any]) -> tuple[str, str, str, str]:
    view = _view(fact.get("view") or fact.get("file_type"))
    identity = fact.get("file_identity") if isinstance(fact.get("file_identity"), dict) else {}
    data = fact.get("data") if isinstance(fact.get("data"), dict) else {}
    path = (identity.get("source_path") or identity.get("path") or fact.get("abs_path")
            or fact.get("source_path") or fact.get("file") or data.get("source") or "")
    relative = (identity.get("effective_relpath") or identity.get("source_relpath")
                or fact.get("relative_path") or fact.get("file") or "")
    version = identity.get("source_version") or fact.get("source_version") or ""
    return view, str(path), str(relative), str(version)


def _selected_identity(item: dict[str, Any]) -> tuple[str, str, str, str]:
    return (_view(item.get("view") or item.get("file_type")),
            str(item.get("source_path") or item.get("absolute_path") or ""),
            str(item.get("relative_path") or item.get("source_relpath") or ""),
            str(item.get("source_version") or ""))


def _same_source(selected: tuple[str, str, str, str], fact: tuple[str, str, str, str]) -> bool:
    sv, spath, srel, sversion = selected
    fv, fpath, frel, fversion = fact
    if sv != fv:
        return False
    if spath and fpath:
        return Path(spath).as_posix() == Path(fpath).as_posix() and (not fversion or not sversion or fversion == sversion)
    return bool(srel and frel and srel == frel and sversion and fversion == sversion)


def _fact_status(fact: dict[str, Any]) -> str:
    status = str(fact.get("parse_status") or fact.get("status") or "").upper()
    if status == "PASS":
        return "PASS"
    if status == "AVAILABLE":
        return str((fact.get("parser") or {}).get("status") or "").upper()
    return status


def _objects(fact: dict[str, Any], view: str) -> list[dict[str, Any]]:
    """Read object names from existing semantic facts or parser envelopes."""
    if fact.get("schema_version") == "semantic_file_fact.v1":
        return [dict(item) for item in fact.get("objects", []) if isinstance(item, dict) and item.get("name")]
    data = fact.get("data") if isinstance(fact.get("data"), dict) else {}
    if view == "lef":
        return [{"name": name} for name in sorted((data.get("macros") or {}).keys())]
    if view == "liberty":
        return [{"name": name, "library": library}
                for library, record in sorted((data.get("libraries") or {}).items())
                for name in sorted((record.get("cells") or {}).keys())]
    if view == "verilog":
        return [{"name": name} for name in sorted((data.get("modules") or {}).keys())]
    if view == "cdl":
        return [{"name": name} for name in sorted((data.get("subckts") or {}).keys())]
    return []


def _confirmed_corner(fact: dict[str, Any]) -> str | None:
    if fact.get("schema_version") == "semantic_file_fact.v1":
        return str(fact.get("corner")) if fact.get("corner_status") == "CONFIRMED" and fact.get("corner") else None
    context = fact.get("semantic_context") or {}
    if context.get("confirmed") is True and context.get("basis") and context.get("corner"):
        return str(context["corner"])
    return None


def _file_entry(item: dict[str, Any], view: str, *, evidence: str, matched_name: str | None = None,
                match_basis: str | None = None, corner: str | None = None) -> dict[str, Any]:
    entry = {
        "view": view,
        "file": str(item.get("relative_path") or item.get("source_relpath") or ""),
        "source_path": str(item.get("source_path") or item.get("absolute_path") or ""),
        "source_version": str(item.get("source_version") or ""),
        "evidence": evidence,
    }
    if matched_name:
        entry["matched_name"] = matched_name
    if match_basis:
        entry["match_basis"] = match_basis
    if corner:
        entry["corner"] = corner
    return entry


def _metadata_macro_name(item: dict[str, Any]) -> str:
    path = str(item.get("relative_path") or item.get("source_path") or "")
    name = Path(path).name
    lower = name.lower()
    for suffix in (".gds.gz", ".oas.gz", ".db.gz", ".gds", ".oas", ".oasis", ".db"):
        if lower.endswith(suffix):
            return name[:-len(suffix)]
    return ""


def build_parser_facts(selected_filemap: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse supported selected files and return facts owned by this run.

    This workflow uses parser copies in ``macro_index_parsers`` and does not
    load results from a scan workspace. GDS and DB remain filename-only facts.
    """
    from .macro_index_parsers import PARSER_BY_VIEW

    facts = []
    for item in selected_filemap.get("files", []):
        if not isinstance(item, dict):
            continue
        view = _view(item.get("view") or item.get("file_type"))
        parser = PARSER_BY_VIEW.get(view)
        if parser is None:
            continue
        source_path = str(item.get("source_path") or item.get("absolute_path") or "")
        relative_path = str(item.get("relative_path") or item.get("source_relpath") or "")
        source_version = str(item.get("source_version") or "")
        identity = {
            "source_path": str(Path(source_path).resolve()) if source_path else "",
            "effective_relpath": relative_path,
            "source_version": source_version,
        }
        try:
            if not source_path:
                raise ValueError("FileMap entry has no source_path")
            fact = parser(source_path)
            fact["source_version"] = source_version
            fact["file_identity"] = identity
        except Exception as exc:
            fact = {
                "result_type": "parser_result",
                "file_type": view,
                "file": relative_path,
                "abs_path": str(Path(source_path).resolve()) if source_path else "",
                "source_version": source_version,
                "file_identity": identity,
                "status": "FAILED",
                "data": {},
                "error": str(exc),
            }
        facts.append(fact)
    return facts


def build_macro_index_from_filemap(
    selected_filemap: dict[str, Any],
    parser_facts: Any,
    explicit_aliases: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Build an index from a FileMap and its already-generated Parser Facts."""
    return build_macro_index(selected_filemap, parser_facts, explicit_aliases=explicit_aliases)


def build_macro_index(
    selected_filemap: dict[str, Any], parser_facts: Any, explicit_aliases: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Index selected files only; parsed object names are evidence, filenames are candidates.

    ``selected_filemap`` is a complete Formal or Candidate file map. ``parser_facts``
    may be the existing semantic facts list or parser-result mapping. This function
    does not open source files, run parsers, compute hashes, or make release decisions.
    """
    context = dict(selected_filemap.get("context") or {})
    context.setdefault("type", "FORMAL" if selected_filemap.get("formal_stage") else "CANDIDATE")
    files = [item for item in selected_filemap.get("files", []) if isinstance(item, dict)]
    selected = [(item, _selected_identity(item)) for item in files]
    facts = list(_fact_items(parser_facts))
    associations: dict[int, list[dict[str, Any]]] = defaultdict(list)
    unmatched_files: list[dict[str, Any]] = []
    unmatched_objects: dict[str, list[dict[str, Any]]] = {view: [] for view in VIEWS}
    parsed_by_file: dict[int, tuple[dict[str, Any], str]] = {}

    for index, (item, identity) in enumerate(selected):
        view = identity[0]
        if view not in VIEWS:
            continue
        if view in {"gds", "db"}:
            continue
        matches = [fact for fact in facts if _same_source(identity, _fact_identity(fact))]
        if len(matches) != 1:
            related = [fact for fact in facts if _fact_identity(fact)[0] == view
                       and identity[2] and _fact_identity(fact)[2] == identity[2]]
            reason = "PARSER_FACT_SOURCE_MISMATCH" if related else "PARSER_FACT_MISSING"
            unmatched_files.append({"view": view, "file": identity[2], "source_version": identity[3], "reason": reason})
            continue
        fact = matches[0]
        status = _fact_status(fact)
        if status != "PASS":
            unmatched_files.append({"view": view, "file": identity[2], "source_version": identity[3], "reason": "PARSER_NOT_PASS"})
            continue
        objects = _objects(fact, view)
        parsed_by_file[index] = (fact, view)
        for obj in objects:
            if obj.get("name"):
                associations[index].append(dict(obj))

    lef_files = [index for index, (_, identity) in enumerate(selected) if identity[0] == "lef"]
    lef_indexed = [index for index in lef_files if index in parsed_by_file]
    if not lef_files:
        baseline_status = "LEF_MISSING"
    elif lef_indexed:
        baseline_status = "LEF_PARSED"
    else:
        baseline_status = "LEF_FACTS_MISSING"
    macro_names = {obj["name"] for index in lef_indexed for obj in associations.get(index, [])}
    if baseline_status == "LEF_MISSING":
        macro_names = {obj["name"] for index, objects in associations.items() for obj in objects}
    macros = {name: {view: [] for view in VIEWS} for name in sorted(macro_names)}
    aliases = {_view(view): dict(mapping) for view, mapping in (explicit_aliases or {}).items()}

    for index, objects in associations.items():
        item, identity = selected[index]
        view = identity[0]
        fact, _ = parsed_by_file[index]
        corner = _confirmed_corner(fact)
        for obj in objects:
            object_name = str(obj["name"])
            macro_name = aliases.get(view, {}).get(object_name, object_name)
            if macro_name not in macros:
                unmatched_objects[view].append({"name": object_name, "file": identity[2],
                                                "source_version": identity[3]})
                continue
            macros[macro_name][view].append(_file_entry(
                item, view, evidence="PARSED_OBJECT", matched_name=object_name,
                match_basis="EXPLICIT_ALIAS" if macro_name != object_name else "EXACT_OBJECT_NAME",
                corner=corner if view == "liberty" else None,
            ))

    for item, identity in selected:
        view = identity[0]
        if view not in {"gds", "db"}:
            continue
        name = _metadata_macro_name(item)
        if name in macros:
            macros[name][view].append(_file_entry(
                item, view, evidence="NAME_CANDIDATE", matched_name=name, match_basis="EXACT_BASENAME",
            ))
        else:
            unmatched_files.append({"view": view, "file": identity[2],
                                    "source_version": identity[3], "reason": "NO_MACRO_NAME_MATCH"})

    for macro in macros.values():
        for view in VIEWS:
            macro[view].sort(key=lambda row: (row.get("corner", ""), row["source_version"], row["file"]))
    for view in VIEWS:
        unmatched_objects[view].sort(key=lambda row: (row["name"], row["source_version"], row["file"]))
    return {
        "schema_version": "macro_index.v1",
        "library_id": selected_filemap.get("library_id"),
        "context": context,
        "baseline": {"view": "lef", "status": baseline_status,
                     "macro_count": len(macros),
                     "basis": "解析成功的所选 LEF Macro 集合" if baseline_status == "LEF_PARSED"
                              else "所选解析对象集合；缺少 LEF 基准，不能作为 LEF 覆盖结论"
                              if baseline_status == "LEF_MISSING" else "所选 LEF 尚无可用解析事实"},
        "macros": macros,
        "unmatched_objects": unmatched_objects,
        "unmatched_files": sorted(unmatched_files, key=lambda row: (row["view"], row["file"], row["reason"])),
        "evidence_note": "PARSED_OBJECT 仅表示现有解析结果中提取到该对象；NAME_CANDIDATE 仅表示 GDS/DB 文件名与 Macro 名相同，不证明文件内部含有该对象。未列出的 View 不代表必需或缺失。",
    }
