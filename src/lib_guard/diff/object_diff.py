from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping
import json


def _read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default
    return default


def _parser_data(scan: Path, file_type: str) -> list[dict[str, Any]]:
    root = scan / "parser_results" / file_type
    if not root.exists():
        return []
    out = []
    for path in sorted(root.glob("*.json")):
        result = _read_json(path, {})
        if result.get("result_type") != "parser_result":
            continue
        data = result.get("data")
        if isinstance(data, Mapping):
            out.append(dict(data))
    return out


def _merge_named(items: list[dict[str, Any]], key: str) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for item in items:
        for name, value in (item.get(key) or {}).items():
            merged[str(name)] = value
    return merged


def _sev_issue(severity: str, title: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"severity": severity, "category": "object_diff", "title": title, "message": message, **extra}


def diff_lef_objects(old_scan: Path, new_scan: Path) -> dict[str, Any]:
    old_macros = _merge_named(_parser_data(old_scan, "lef"), "macros")
    new_macros = _merge_named(_parser_data(new_scan, "lef"), "macros")
    macro_changes = []
    pin_changes = []
    issues = []
    for name in sorted(set(new_macros) - set(old_macros)):
        macro_changes.append({"macro": name, "change_type": "added", "severity": "warning"})
    for name in sorted(set(old_macros) - set(new_macros)):
        macro_changes.append({"macro": name, "change_type": "removed", "severity": "blocker"})
        issues.append(_sev_issue("blocker", "LEF macro removed", f"macro removed: {name}", object_type="lef_macro", object_name=name))
    for name in sorted(set(old_macros) & set(new_macros)):
        old = old_macros[name]
        new = new_macros[name]
        for field in ["size", "class", "origin"]:
            if old.get(field) != new.get(field):
                severity = "error" if field == "size" else "warning"
                macro_changes.append({"macro": name, "change_type": f"{field}_changed", "old": old.get(field), "new": new.get(field), "severity": severity})
                if field == "size":
                    issues.append(_sev_issue("error", "LEF macro size changed", f"macro size changed: {name}", object_type="lef_macro", object_name=name))
        old_pins = old.get("pins") or {}
        new_pins = new.get("pins") or {}
        for pin in sorted(set(new_pins) - set(old_pins)):
            pin_changes.append({"macro": name, "pin": pin, "change_type": "added", "severity": "warning"})
        for pin in sorted(set(old_pins) - set(new_pins)):
            pin_changes.append({"macro": name, "pin": pin, "change_type": "removed", "severity": "blocker"})
            issues.append(_sev_issue("blocker", "LEF pin removed", f"pin removed: {name}.{pin}", object_type="lef_pin", object_name=f"{name}.{pin}"))
        for pin in sorted(set(old_pins) & set(new_pins)):
            old_pin = old_pins[pin]
            new_pin = new_pins[pin]
            for field in ["direction", "use", "layers"]:
                old_value = sorted(old_pin.get(field) or []) if field == "layers" else old_pin.get(field)
                new_value = sorted(new_pin.get(field) or []) if field == "layers" else new_pin.get(field)
                if old_value != new_value:
                    severity = "blocker" if field == "direction" else "warning"
                    pin_changes.append({"macro": name, "pin": pin, "change_type": f"{field}_changed", "old": old_value, "new": new_value, "severity": severity})
                    if severity == "blocker":
                        issues.append(_sev_issue("blocker", "LEF pin direction changed", f"pin direction changed: {name}.{pin}", object_type="lef_pin", object_name=f"{name}.{pin}"))
    return {
        "schema_version": "1.0",
        "diff_type": "lef_object_diff",
        "diff_confidence": "high" if old_macros or new_macros else "low",
        "confidence_reasons": [] if old_macros or new_macros else ["missing LEF parser_results"],
        "summary": {
            "added_macros": len(set(new_macros) - set(old_macros)),
            "removed_macros": len(set(old_macros) - set(new_macros)),
            "changed_macros": len({item["macro"] for item in macro_changes if item["change_type"] not in {"added", "removed"}}),
            "added_pins": len([x for x in pin_changes if x["change_type"] == "added"]),
            "removed_pins": len([x for x in pin_changes if x["change_type"] == "removed"]),
            "changed_pins": len([x for x in pin_changes if x["change_type"] not in {"added", "removed"}]),
        },
        "macro_changes": macro_changes,
        "pin_changes": pin_changes,
        "issues": issues,
    }


def diff_verilog_objects(old_scan: Path, new_scan: Path) -> dict[str, Any]:
    old_modules = _merge_named(_parser_data(old_scan, "verilog"), "modules")
    new_modules = _merge_named(_parser_data(new_scan, "verilog"), "modules")
    module_changes = []
    port_changes = []
    issues = []
    for name in sorted(set(new_modules) - set(old_modules)):
        module_changes.append({"module": name, "change_type": "added", "severity": "warning"})
    for name in sorted(set(old_modules) - set(new_modules)):
        module_changes.append({"module": name, "change_type": "removed", "severity": "blocker"})
        issues.append(_sev_issue("blocker", "Verilog module removed", f"module removed: {name}", object_type="verilog_module", object_name=name))
    for name in sorted(set(old_modules) & set(new_modules)):
        old_ports = old_modules[name].get("ports") or {}
        new_ports = new_modules[name].get("ports") or {}
        for port in sorted(set(new_ports) - set(old_ports)):
            port_changes.append({"module": name, "port": port, "change_type": "added", "severity": "warning"})
        for port in sorted(set(old_ports) - set(new_ports)):
            port_changes.append({"module": name, "port": port, "change_type": "removed", "severity": "blocker"})
            issues.append(_sev_issue("blocker", "Verilog port removed", f"port removed: {name}.{port}", object_type="verilog_port", object_name=f"{name}.{port}"))
        for port in sorted(set(old_ports) & set(new_ports)):
            old_port = old_ports[port]
            new_port = new_ports[port]
            for field in ["direction", "width"]:
                if old_port.get(field) != new_port.get(field):
                    change_type = "width_changed" if field == "width" else "direction_changed"
                    port_changes.append({"module": name, "port": port, "change_type": change_type, f"old_{field}": old_port.get(field), f"new_{field}": new_port.get(field), "severity": "blocker"})
                    issues.append(_sev_issue("blocker", f"Verilog port {field} changed", f"port {field} changed: {name}.{port}", object_type="verilog_port", object_name=f"{name}.{port}"))
    return {
        "schema_version": "1.0",
        "diff_type": "verilog_object_diff",
        "diff_confidence": "high" if old_modules or new_modules else "low",
        "confidence_reasons": [] if old_modules or new_modules else ["missing Verilog parser_results"],
        "summary": {
            "added_modules": len(set(new_modules) - set(old_modules)),
            "removed_modules": len(set(old_modules) - set(new_modules)),
            "changed_modules": len({item["module"] for item in port_changes}),
            "added_ports": len([x for x in port_changes if x["change_type"] == "added"]),
            "removed_ports": len([x for x in port_changes if x["change_type"] == "removed"]),
            "width_changed_ports": len([x for x in port_changes if x["change_type"] == "width_changed"]),
        },
        "module_changes": module_changes,
        "port_changes": port_changes,
        "issues": issues,
    }


def _lib_cells(libraries: dict[str, Any]) -> dict[str, dict[str, Any]]:
    cells = {}
    for lib_name, lib in libraries.items():
        for cell_name, cell in (lib.get("cells") or {}).items():
            cells[f"{lib_name}/{cell_name}"] = {"library": lib_name, **cell}
    return cells


def diff_liberty_objects(old_scan: Path, new_scan: Path) -> dict[str, Any]:
    old_libs = _merge_named(_parser_data(old_scan, "liberty"), "libraries")
    new_libs = _merge_named(_parser_data(new_scan, "liberty"), "libraries")
    old_cells = _lib_cells(old_libs)
    new_cells = _lib_cells(new_libs)
    cell_changes = []
    corner_changes = []
    issues = []
    for cell in sorted(set(new_cells) - set(old_cells)):
        cell_changes.append({"cell": cell, "change_type": "added", "severity": "warning"})
    for cell in sorted(set(old_cells) - set(new_cells)):
        cell_changes.append({"cell": cell, "change_type": "removed", "severity": "blocker"})
        issues.append(_sev_issue("blocker", "Liberty cell removed", f"cell removed: {cell}", object_type="liberty_cell", object_name=cell))
    for cell in sorted(set(old_cells) & set(new_cells)):
        old_pins = old_cells[cell].get("pins") or {}
        new_pins = new_cells[cell].get("pins") or {}
        removed_pins = sorted(set(old_pins) - set(new_pins))
        if removed_pins:
            cell_changes.append({"cell": cell, "change_type": "pins_removed", "removed_pins": removed_pins, "severity": "blocker"})
            for pin in removed_pins:
                issues.append(_sev_issue("blocker", "Liberty pin removed", f"pin removed: {cell}/{pin}", object_type="liberty_pin", object_name=f"{cell}/{pin}"))
    for lib in sorted(set(old_libs) & set(new_libs)):
        old_corners = set((old_libs[lib].get("operating_conditions") or {}).keys())
        new_corners = set((new_libs[lib].get("operating_conditions") or {}).keys())
        for corner in sorted(old_corners - new_corners):
            corner_changes.append({"library": lib, "corner": corner, "change_type": "removed", "severity": "blocker"})
            issues.append(_sev_issue("blocker", "Liberty corner removed", f"corner removed: {lib}/{corner}", object_type="liberty_corner", object_name=f"{lib}/{corner}"))
    return {
        "schema_version": "1.0",
        "diff_type": "liberty_object_diff",
        "diff_confidence": "high" if old_libs or new_libs else "low",
        "confidence_reasons": [] if old_libs or new_libs else ["missing Liberty parser_results"],
        "summary": {
            "added_libraries": len(set(new_libs) - set(old_libs)),
            "removed_libraries": len(set(old_libs) - set(new_libs)),
            "added_cells": len(set(new_cells) - set(old_cells)),
            "removed_cells": len(set(old_cells) - set(new_cells)),
            "changed_cells": len([x for x in cell_changes if x["change_type"] not in {"added", "removed"}]),
            "removed_corners": len(corner_changes),
        },
        "cell_changes": cell_changes,
        "corner_changes": corner_changes,
        "issues": issues,
    }


def build_object_diffs(old_scan: str | Path, new_scan: str | Path) -> dict[str, dict[str, Any]]:
    old = Path(old_scan)
    new = Path(new_scan)
    return {
        "lef": diff_lef_objects(old, new),
        "verilog": diff_verilog_objects(old, new),
        "liberty": diff_liberty_objects(old, new),
    }


def object_diff_issue_list(object_diffs: Mapping[str, dict[str, Any]]) -> list[dict[str, Any]]:
    issues = []
    for file_type, payload in object_diffs.items():
        for issue in payload.get("issues", []) or []:
            item = dict(issue)
            item.setdefault("file_type", file_type)
            issues.append(item)
    return issues


def object_change_count(object_diffs: Mapping[str, dict[str, Any]]) -> int:
    total = 0
    for payload in object_diffs.values():
        for value in (payload.get("summary") or {}).values():
            if isinstance(value, int):
                total += value
    return total
