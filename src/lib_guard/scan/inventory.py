from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator, Mapping
import hashlib
import os
import re


KEY_FILE_TYPES = {
    "lef",
    "liberty",
    "verilog",
    "cdl",
    "sdc",
    "upf",
    "cpf",
    "sdf",
    "spef",
    "db",
    "ibis",
    "pwl",
    "snp",
    "touchstone",
    "cpm",
    "waiver",
    "gds",
    "oas",
    "flow_config",
    "tech_config",
}

DEFAULT_SCAN_IGNORE_DIRS = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    "catalog",
    "diff",
    "index",
    "pages",
    "release_area",
    "reports",
    "scan_out",
    "source_package",
    "work",
    "tmp",
    "temp",
}

_CORNER_PROCESS_RE = re.compile(r"(?<![a-z0-9])(ss|ff|tt|sf|fs)(?![a-z0-9])", re.IGNORECASE)
_CORNER_VOLTAGE_RE = re.compile(r"(?<![a-z0-9])(\d+p\d+|\d+\.\d+)v(?![a-z0-9])", re.IGNORECASE)
_CORNER_TEMP_RE = re.compile(r"(?<![a-z0-9])([m-]?\d+)c(?![a-z0-9])", re.IGNORECASE)


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _split_name_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        raw_items = value.replace(";", ",").split(",")
    elif isinstance(value, (list, tuple, set)):
        raw_items = list(value)
    else:
        raw_items = [value]
    return [str(item).strip().lower() for item in raw_items if str(item).strip()]


def _scan_ignore_dirs(config: Any = None, context: Any = None) -> set[str]:
    """Return directory names that inventory scan should never recurse into."""

    names = set(DEFAULT_SCAN_IGNORE_DIRS)
    for obj in (config, context):
        if obj is None:
            continue
        names.update(_split_name_list(_get(obj, "ignore_dirs", None)))
        names.update(_split_name_list(_get(obj, "scan_ignore_dirs", None)))
    return names


def extract_filename_corner(path: str) -> dict[str, Any] | None:
    """Extract lightweight PVT corner hints from a file path without reading content."""

    text = str(path or "").replace("\\", "/").lower()
    process = None
    voltage = None
    temperature = None
    m = _CORNER_PROCESS_RE.search(text)
    if m:
        process = m.group(1).lower()
    m = _CORNER_VOLTAGE_RE.search(text)
    if m:
        voltage = m.group(1).lower().replace("p", ".") + "v"
    m = _CORNER_TEMP_RE.search(text)
    if m:
        temperature = m.group(1).lower().replace("m", "-") + "c"
    if not any([process, voltage, temperature]):
        return None
    return {"process": process, "voltage": voltage, "temperature": temperature}


def corner_filename_summary(records: list[Mapping[str, Any]]) -> dict[str, Any]:
    process_counts: dict[str, int] = {}
    voltage_counts: dict[str, int] = {}
    temperature_counts: dict[str, int] = {}
    examples: list[dict[str, Any]] = []
    total = 0
    for record in records:
        corner = record.get("corner") if isinstance(record, Mapping) else None
        if not isinstance(corner, Mapping) or not any(corner.values()):
            continue
        total += 1
        process = corner.get("process")
        voltage = corner.get("voltage")
        temperature = corner.get("temperature")
        if process:
            process_counts[str(process)] = process_counts.get(str(process), 0) + 1
        if voltage:
            voltage_counts[str(voltage)] = voltage_counts.get(str(voltage), 0) + 1
        if temperature:
            temperature_counts[str(temperature)] = temperature_counts.get(str(temperature), 0) + 1
        if len(examples) < 20:
            examples.append({"file": record.get("path"), "file_type": record.get("file_type"), "corner": dict(corner)})
    return {
        "total_corner_files": total,
        "process_counts": dict(sorted(process_counts.items())),
        "voltage_counts": dict(sorted(voltage_counts.items())),
        "temperature_counts": dict(sorted(temperature_counts.items())),
        "examples": examples,
    }


class FileWalker:
    def __init__(self, config: Any = None) -> None:
        self.config = config

    def walk(self, root_path: str | Path, context: Any = None) -> Iterator[dict[str, Any]]:
        root = Path(root_path).resolve()
        ignore_dirs = _scan_ignore_dirs(self.config, context)
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(d for d in dirnames if d.lower() not in ignore_dirs)
            for name in sorted(filenames):
                abs_path = Path(dirpath) / name
                try:
                    stat = abs_path.stat()
                except OSError:
                    continue
                logical_path = abs_path.relative_to(root).as_posix()
                yield {
                    "path": logical_path,
                    "abs_path": str(abs_path.resolve()),
                    "name": name,
                    "extension": abs_path.suffix.lower(),
                    "size_bytes": stat.st_size,
                    "mtime": stat.st_mtime,
                    "is_symlink": abs_path.is_symlink(),
                    "symlink_target": os.readlink(abs_path) if abs_path.is_symlink() else None,
                }


class FileClassifier:
    def __init__(self, config: Any = None) -> None:
        self.config = config

    def classify(self, record: dict[str, Any], context: Any = None) -> dict[str, Any]:
        name = str(_get(record, "name", Path(str(_get(record, "path", ""))).name)).lower()
        path = str(_get(record, "path", "")).lower()
        ext = Path(name).suffix.lower()
        combined_ext = self._combined_extension(name)
        file_type = self._file_type(name, ext)
        role = self._role(name, path, file_type)
        record.update(
            {
                "extension": ext,
                "combined_extension": combined_ext,
                "compression": "gzip" if ext == ".gz" else None,
                "file_type": file_type,
                "domain": self._domain(file_type),
                "role": role,
                "is_key_file": file_type in KEY_FILE_TYPES,
                "is_key_doc": file_type == "doc" and role in {"readme", "release_note", "integration_guide", "update_note"},
                "doc_type": role if file_type == "doc" else None,
                "corner": extract_filename_corner(str(_get(record, "path", name))),
            }
        )
        return record

    def _file_type(self, name: str, ext: str) -> str:
        if name.endswith((".lef", ".lef.gz", ".tlef", ".tlef.gz")):
            return "lef"
        if name.endswith((".lib", ".lib.gz")):
            return "liberty"
        if name.endswith((".v", ".v.gz", ".sv", ".sv.gz", ".vg", ".vg.gz", ".vp", ".vp.gz", ".vh", ".vh.gz", ".svh", ".svh.gz")):
            return "verilog"
        if name.endswith((".cdl", ".cdl.gz", ".sp", ".sp.gz", ".spi", ".spi.gz", ".spice", ".spice.gz")):
            return "cdl"
        if name.endswith((".sdc", ".sdc.gz")):
            return "sdc"
        if name.endswith((".upf", ".upf.gz")):
            return "upf"
        if name.endswith((".cpf", ".cpf.gz")):
            return "cpf"
        if name.endswith((".sdf", ".sdf.gz")):
            return "sdf"
        if name.endswith((".spef", ".spef.gz")):
            return "spef"
        if name.endswith((".db", ".db.gz", ".ndm", ".ndm.gz")):
            return "db"
        if name.endswith((".gds", ".gds.gz", ".gdsii", ".gdsii.gz")):
            return "gds"
        if name.endswith((".oas", ".oas.gz", ".oasis", ".oasis.gz")):
            return "oas"
        if name.endswith((".ibs", ".ibis")):
            return "ibis"
        if name.endswith((".s1p", ".s2p", ".s4p", ".s6p", ".s8p", ".snp")):
            return "snp"
        if name.endswith(".pwl"):
            return "pwl"
        if name.endswith(".cpm"):
            return "cpm"
        if name.endswith((".pkg", ".package", ".json", ".yaml", ".yml")):
            return "package"
        if name.endswith((".lyp", ".lyt", ".lydrc", ".rules")):
            return "tech_config"
        if name.endswith((".tcl", ".cfg", ".mk", ".cells")):
            return "flow_config"
        if "waiver" in name:
            return "waiver"
        if ext in {".md", ".txt", ".pdf", ".doc", ".docx"} or "readme" in name or "release" in name:
            return "doc"
        return "unknown"

    def _combined_extension(self, name: str) -> str:
        path = Path(name)
        if path.suffix.lower() != ".gz":
            return path.suffix.lower()
        stem_suffix = Path(name[:-3]).suffix.lower()
        return f"{stem_suffix}.gz" if stem_suffix else ".gz"

    def _domain(self, file_type: str) -> str:
        if file_type in {"lef", "liberty", "db", "verilog", "cdl"}:
            return "implementation"
        if file_type in {"sdc", "upf", "cpf", "spef", "ibis", "pwl", "snp", "touchstone", "cpm"}:
            return "constraint"
        if file_type in {"doc", "package", "waiver"}:
            return "documentation"
        if file_type == "flow_config":
            return "flow_setup"
        if file_type == "tech_config":
            return "technology_setup"
        return "unknown"

    def _role(self, name: str, path: str, file_type: str) -> str:
        text = f"{path}/{name}"
        if file_type == "doc":
            if "readme" in text:
                return "readme"
            if "release" in text:
                return "release_note"
            if "change" in text or "update" in text:
                return "update_note"
            if "integration" in text or "guide" in text:
                return "integration_guide"
        if file_type == "verilog" and (name.endswith((".vg", ".vg.gz")) or "gate" in text):
            return "gate_netlist"
        if file_type == "lef" and name.endswith((".tlef", ".tlef.gz")):
            return "tech_lef"
        if file_type == "flow_config":
            if name.endswith(".tcl"):
                return "flow_script"
            if name.endswith(".mk"):
                return "flow_setup"
            if name.endswith(".cfg"):
                return "flow_config"
            if name.endswith(".cells"):
                return "cell_list"
        if file_type == "tech_config":
            if name.endswith(".lydrc"):
                return "drc_rule"
            if name.endswith((".lyp", ".lyt")):
                return "klayout"
            if name.endswith(".rules"):
                return "tech_rule"
        return file_type


class HashManager:
    def __init__(self, config: Any = None) -> None:
        self.config = config

    def compute(self, record: Any, context: Any = None) -> str:
        path = Path(str(_get(record, "abs_path", _get(record, "path", ""))))
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return "sha256:" + h.hexdigest()
