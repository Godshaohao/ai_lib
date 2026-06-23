from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator, Mapping
import hashlib
import os


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
    "gds",
    "oas",
}


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(key, default)
    return getattr(obj, key, default)


class FileWalker:
    def __init__(self, config: Any = None) -> None:
        self.config = config

    def walk(self, root_path: str | Path, context: Any = None) -> Iterator[dict[str, Any]]:
        root = Path(root_path).resolve()
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in {".git", "__pycache__", ".pytest_cache"}]
            for name in sorted(filenames):
                abs_path = Path(dirpath) / name
                try:
                    stat = abs_path.stat()
                except OSError:
                    continue
                yield {
                    "path": str(abs_path.resolve().relative_to(root)),
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
            return "touchstone"
        if name.endswith(".pwl"):
            return "pwl"
        if name.endswith((".pkg", ".package", ".json", ".yaml", ".yml")):
            return "package"
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
        if file_type in {"sdc", "upf", "cpf", "spef"}:
            return "constraint"
        if file_type in {"doc", "package", "waiver"}:
            return "documentation"
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
