"""Build the current, source-aware RAW file set used by automatic review."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from .effective_file_tracker import _view_for_path, _view_relative_key, build_candidate_filemap
from .file_version_projection import resolve_version_order
from .lef_liberty_check import _corner_axes


def _inventory_records(versions: list[dict[str, Any]],
                       inventories: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    roots = {str(item.get("id") or ""): Path(str(item.get("path") or "")).expanduser().resolve()
             for item in versions}
    for inventory in inventories:
        version = str(inventory.get("version_id") or "")
        root = roots.get(version)
        files = []
        for raw_path in inventory.get("files") or []:
            path = Path(str(raw_path)).expanduser().resolve()
            if root is None:
                continue
            try:
                relative = path.relative_to(root).as_posix()
            except ValueError:
                continue
            view = _view_for_path(Path(relative))
            if view == "other":
                continue
            files.append({"view": view, "relative_path": relative, "source_path": str(path)})
        records[version] = {"status": str(inventory.get("status") or "UNKNOWN"), "files": files}
    return records


def _active_chain(versions: list[dict[str, Any]], candidate: str) -> list[str] | None:
    by_id = {str(item.get("id") or ""): item for item in versions}
    chain: list[str] = []
    seen: set[str] = set()
    current = candidate
    overlays = {"PARTIAL_UPDATE", "HOTFIX", "DOC_UPDATE", "DOC_ONLY"}
    while current:
        if current in seen or current not in by_id:
            return None
        seen.add(current)
        item = by_id[current]
        kind = str(item.get("package_type") or "").upper()
        chain.append(current)
        if kind == "FULL_PACKAGE":
            return list(reversed(chain))
        if kind not in overlays:
            return None
        current = str(item.get("previous_effective_version") or "").strip()
        if not current:
            return None
    return None


def _file_id(item: dict[str, Any]) -> tuple[str, tuple[str, ...]]:
    return _view_relative_key(str(item.get("relative_path") or ""), str(item.get("view") or ""))


def _identity_path(key: tuple[str, tuple[str, ...]]) -> str:
    return "/".join((key[0], *key[1]))


def _projected_files(records: dict[str, dict[str, Any]], versions: list[str], *,
                     start_at: int = 0) -> tuple[list[dict[str, Any]], set[tuple[str, tuple[str, ...]]]]:
    selected: dict[tuple[str, tuple[str, ...]], dict[str, Any]] = {}
    for version in versions[start_at:]:
        for item in records.get(version, {}).get("files") or []:
            key = _file_id(item)
            selected[key] = {**item, "source_version": version,
                              "identity_path": _identity_path(key)}
    return sorted(selected.values(), key=lambda item: item["identity_path"]), set(selected)


def build_current_file_set(versions: list[dict[str, Any]],
                           inventories: list[dict[str, Any]]) -> dict[str, Any]:
    """Resolve the current file set without guessing FULL/PATCH semantics.

    Explicit Catalog package ancestry uses the existing cumulative file map.
    A single delivery is directly observable. For multiple deliveries without
    package metadata, only the latest delivery's observed files are candidates;
    older-only paths are recorded as unresolved instead of silently inherited.
    """
    order = resolve_version_order(versions)
    records = _inventory_records(versions, inventories)
    ordered = [str(item) for item in order.get("ordered_ids") or []]
    if order.get("status") != "KNOWN" or not ordered:
        return {"schema_version": "current_file_set.v1", "status": "UNKNOWN_ORDER",
                "basis": order.get("basis"), "candidate_version": "", "files": [],
                "unresolved": [{"reason": "DELIVERY_ORDER_UNCONFIRMED"}],
                "warnings": order.get("warnings") or []}

    candidate = ordered[-1]
    raw_library = {"inventories": records}
    package_metadata = {
        str(item.get("id") or ""): {key: item.get(key) for key in (
            "package_type", "previous_effective_version", "base_full_version") if item.get(key) is not None}
        for item in versions if item.get("package_type")
    }
    if len(ordered) == 1:
        files = [dict(item, source_version=candidate,
                      identity_path=_identity_path(_file_id(item)))
                 for item in records.get(candidate, {}).get("files") or []]
        status = "COMPLETE" if records.get(candidate, {}).get("status") == "COMPLETE" else "PARTIAL"
        return {"schema_version": "current_file_set.v1", "status": status,
                "basis": "SINGLE_DELIVERY", "candidate_version": candidate,
                "files": sorted(files, key=lambda item: item["identity_path"]),
                "unresolved": [] if status == "COMPLETE" else [
                    {"reason": "ACTIVE_CHAIN_SCAN_INCOMPLETE"}], "warnings": []}

    chain = _active_chain(versions, candidate) if len(package_metadata) == len(versions) else None
    if chain:
        raw_library = {"inventories": {key: records.get(key, {"status": "UNKNOWN", "files": []})
                                        for key in chain}}
        metadata = {key: package_metadata[key] for key in chain}
        filemap = build_candidate_filemap(raw_library, metadata, candidate)
        if filemap.get("status") == "COMPLETE":
            files = [{key: item.get(key) for key in
                      ("view", "relative_path", "source_path", "source_version", "identity_path", "operation", "replaces")}
                     for item in filemap.get("files") or []]
            return {"schema_version": "current_file_set.v1", "status": "COMPLETE",
                    "basis": "CONFIRMED_FULL_PATCH_CHAIN", "candidate_version": candidate,
                    "chain": chain, "files": files, "unresolved": [], "warnings": []}

        incomplete_indices = [index for index, version in enumerate(chain)
                              if records.get(version, {}).get("status") != "COMPLETE"]
        if incomplete_indices:
            start_at = max(incomplete_indices)
            files, selected_ids = _projected_files(records, chain, start_at=start_at)
            unresolved_ids = {_file_id(item) for version in chain[:start_at]
                              for item in records.get(version, {}).get("files") or []} - selected_ids
            unresolved = [{"identity_path": _identity_path(key), "reason": "ACTIVE_CHAIN_SCAN_INCOMPLETE"}
                          for key in sorted(unresolved_ids)]
            unresolved.append({"reason": "ACTIVE_CHAIN_SCAN_INCOMPLETE"})
            return {"schema_version": "current_file_set.v1", "status": "PARTIAL",
                    "basis": "CONFIRMED_CHAIN_WITH_PARTIAL_INVENTORY", "candidate_version": candidate,
                    "chain": chain, "files": files, "unresolved": unresolved,
                    "warnings": [filemap.get("message") or "活动叠加链含不完整盘点"]}

    # No reliable FULL/PATCH ancestry: do not carry older-only paths forward.
    files = [dict(item, source_version=candidate,
                  identity_path=_identity_path(_file_id(item)))
             for item in records.get(candidate, {}).get("files") or []]
    selected_ids = {_file_id(item) for item in records.get(candidate, {}).get("files") or []}
    historical_ids = {_file_id(item) for version in ordered[:-1]
                      for item in records.get(version, {}).get("files") or []}
    unresolved = [{"identity_path": _identity_path(key), "reason": "PACKAGE_SEMANTICS_UNCONFIRMED"}
                  for key in sorted(historical_ids - selected_ids)]
    unresolved.append({"reason": "PACKAGE_SEMANTICS_UNCONFIRMED"})
    if records.get(candidate, {}).get("status") != "COMPLETE":
        unresolved.append({"reason": "ACTIVE_CHAIN_SCAN_INCOMPLETE"})
    return {"schema_version": "current_file_set.v1", "status": "PARTIAL",
            "basis": "LATEST_DELIVERY_ONLY_UNCONFIRMED_PACKAGE_SEMANTICS",
            "candidate_version": candidate, "files": sorted(files, key=lambda item: item["identity_path"]),
            "unresolved": unresolved,
            "warnings": ["多次交付缺少已确认的 FULL/PATCH 包语义"]}


def _fact_state(fact: dict[str, Any]) -> str:
    status = str(fact.get("parse_status") or fact.get("status") or "").upper()
    return str((fact.get("parser") or {}).get("status") or "").upper() if status == "AVAILABLE" else status


def _condition_identity(conditions: Any) -> tuple[tuple[str, tuple[tuple[str, str], ...]], ...]:
    if not isinstance(conditions, dict) or not conditions:
        return (("UNSPECIFIED", ()),)
    result = []
    for name, values in sorted(conditions.items()):
        attrs = tuple(sorted((str(key), str(value)) for key, value in (values or {}).items())) \
            if isinstance(values, dict) else ()
        result.append((str(name), attrs))
    return tuple(result)


def _has_complete_pvt(identity: tuple[tuple[str, tuple[tuple[str, str], ...]], ...]) -> bool:
    required = {"process", "voltage", "temperature"}
    return bool(identity) and all(name != "UNSPECIFIED" and required.issubset(dict(attrs))
                                  for name, attrs in identity)


def build_interface_groups(file_set: dict[str, Any],
                           parser_facts: list[dict[str, Any]]) -> dict[str, Any]:
    """Associate current LEF and Liberty files by parsed Macro/Cell objects.

    Repeated objects in distinct current Liberty paths remain ambiguous unless
    their exact Corner and operating-condition identity proves they are
    complementary. Version order alone never removes a candidate.
    """
    facts_by_path: dict[str, dict[str, Any]] = {}
    for fact in parser_facts:
        identity = fact.get("file_identity") if isinstance(fact.get("file_identity"), dict) else {}
        source = str(identity.get("source_path") or fact.get("abs_path") or fact.get("source_path") or "")
        if source:
            facts_by_path[str(Path(source).expanduser().resolve())] = fact

    files = [item for item in file_set.get("files") or [] if isinstance(item, dict)]
    incomplete = str(file_set.get("status") or "") != "COMPLETE"
    unresolved: list[dict[str, Any]] = []
    lef_records: list[dict[str, Any]] = []
    observed_liberties: list[dict[str, Any]] = []
    liberty_objects: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    library_views: dict[str, dict[str, Any]] = {}

    for item in files:
        view = str(item.get("view") or "").lower()
        if view not in {"lef", "liberty"}:
            continue
        path = str(Path(str(item.get("source_path") or "")).expanduser().resolve())
        fact = facts_by_path.get(path)
        fact_state = _fact_state(fact) if fact else ""
        if not fact or not fact_state.startswith("PASS"):
            unresolved.append({"view": view, "source_path": path,
                               "source_version": item.get("source_version"),
                               "reason": "PARSER_FACT_MISSING_OR_FAILED"})
            incomplete = True
            continue
        if fact_state != "PASS":
            incomplete = True
        data = fact.get("data") if isinstance(fact.get("data"), dict) else {}
        if view == "lef":
            macros = data.get("macros") if isinstance(data.get("macros"), dict) else {}
            lef_records.append({"source_path": path, "source_version": item.get("source_version"),
                                "macro_names": sorted(str(name) for name in macros)})
            continue

        libraries = data.get("libraries") if isinstance(data.get("libraries"), dict) else {}
        conditions_by_library = {str(name): library.get("operating_conditions") or {}
                                 for name, library in libraries.items() if isinstance(library, dict)}
        condition_names = [str(name) for conditions in conditions_by_library.values()
                           for name in conditions]
        axes = _corner_axes(Path(path), sorted(str(name) for name in libraries), condition_names)
        cell_names = sorted({str(cell) for library in libraries.values() if isinstance(library, dict)
                             for cell in (library.get("cells") or {})})
        observed_liberties.append({"source_path": path, "source_version": item.get("source_version"),
                                   "corner_axes": axes, "library_names": sorted(str(name) for name in libraries),
                                   "operating_conditions": conditions_by_library,
                                   "liberty_inventory": {"cell_count": len(cell_names), "cell_names": cell_names}})
        if axes.get("conflict"):
            unresolved.append({"view": view, "source_path": path,
                               "source_version": item.get("source_version"),
                               "reason": "CORNER_LABEL_CONFLICT"})
            incomplete = True
        for library_name, library in libraries.items():
            if not isinstance(library, dict):
                continue
            cells = library.get("cells") if isinstance(library.get("cells"), dict) else {}
            conditions = library.get("operating_conditions") or {}
            condition_id = _condition_identity(conditions)
            context = (axes.get("process_corner"), axes.get("rc_corner"), condition_id)
            for cell_name in cells:
                key = (str(cell_name), *context)
                record = {"macro": str(cell_name), "source_path": path,
                          "source_version": item.get("source_version"),
                          "library": str(library_name),
                          "process_corner": axes.get("process_corner"),
                          "rc_corner": axes.get("rc_corner"),
                          "conditions": condition_id}
                liberty_objects[key].append(record)
                library_views.setdefault(path, item)

    lef_owners: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in lef_records:
        for macro in record["macro_names"]:
            lef_owners[macro].append(record)

    ambiguous_objects = []
    blocked_keys: set[tuple[Any, ...]] = set()
    same_corner: dict[tuple[Any, ...], list[tuple[tuple[Any, ...], list[dict[str, Any]]]]] = defaultdict(list)
    for key, candidates in liberty_objects.items():
        same_corner[(key[0], key[1], key[2])].append((key, candidates))
    for corner_key, variants in same_corner.items():
        candidate_paths = {item["source_path"] for _key, candidates in variants for item in candidates}
        if len(candidate_paths) <= 1:
            continue
        identities = [key[3] for key, _candidates in variants]
        if len(set(identities)) > 1 and not all(_has_complete_pvt(identity) for identity in identities):
            blocked_keys.update(key for key, _candidates in variants)
            ambiguous_objects.append({"macro": corner_key[0], "process_corner": corner_key[1],
                                      "rc_corner": corner_key[2],
                                      "sources": sorted(candidate_paths),
                                      "reason": "OPERATING_CONDITION_IDENTITY_INCOMPLETE"})
    unique_objects: list[dict[str, Any]] = []
    for key, candidates in sorted(liberty_objects.items(), key=lambda pair: tuple(map(str, pair[0]))):
        paths = sorted({item["source_path"] for item in candidates})
        context = {"macro": key[0], "process_corner": key[1], "rc_corner": key[2],
                   "conditions": key[3]}
        if key in blocked_keys:
            continue
        if len(paths) > 1:
            ambiguous_objects.append({**context, "sources": paths,
                                      "reason": "MULTIPLE_CURRENT_LIBERTY_CANDIDATES"})
            incomplete = True
        else:
            unique_objects.append(candidates[0])

    groups_by_lef: dict[str, dict[str, Any]] = {}
    ambiguous_lef_macros = {macro for macro, owners in lef_owners.items() if len(owners) > 1}
    for macro in sorted(ambiguous_lef_macros):
        ambiguous_objects.append({"macro": macro,
                                  "sources": sorted(owner["source_path"] for owner in lef_owners[macro]),
                                  "reason": "MACRO_PRESENT_IN_MULTIPLE_CURRENT_LEFS"})
        incomplete = True
    for item in unique_objects:
        macro = item["macro"]
        owners = lef_owners.get(macro) or []
        if macro in ambiguous_lef_macros or len(owners) != 1:
            continue
        lef_path = owners[0]["source_path"]
        group = groups_by_lef.setdefault(lef_path, {
            "lef_file": lef_path, "source_versions": {"lef": owners[0]["source_version"], "liberties": {}},
            "macro_names": set(), "liberty_files": set(), "objects": [],
        })
        group["macro_names"].add(macro)
        group["liberty_files"].add(item["source_path"])
        group["source_versions"]["liberties"][item["source_path"]] = item["source_version"]
        group["objects"].append({key: value for key, value in item.items()
                                  if key not in {"source_path", "source_version"}} | {
                                      "liberty_file": item["source_path"],
                                      "source_version": item["source_version"]})

    groups = []
    for group in groups_by_lef.values():
        group["macro_names"] = sorted(group["macro_names"])
        group["liberty_files"] = sorted(group["liberty_files"])
        group["objects"] = sorted(group["objects"], key=lambda item: (
            item["macro"], str(item.get("process_corner") or ""),
            str(item.get("rc_corner") or ""), item["liberty_file"]))
        groups.append(group)

    return {"schema_version": "lef_liberty_object_groups.v1",
            "status": "PARTIAL" if incomplete or ambiguous_objects else "COMPLETE",
            "candidate_set_status": file_set.get("status"),
            "groups": sorted(groups, key=lambda item: item["lef_file"]),
            "observed_liberties": observed_liberties,
            "ambiguous_objects": ambiguous_objects, "unresolved": unresolved}
