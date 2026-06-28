from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any


FILE_TYPE_TO_VIEW = {
    "verilog": "rtl",
    "lef": "lef",
    "liberty": "lib",
    "db": "db",
    "gds": "gds",
    "oas": "oas",
    "cdl": "cdl",
    "sdc": "sdc",
    "upf": "upf",
    "cpf": "cpf",
    "spef": "spef",
    "sdf": "sdf",
    "doc": "doc",
    "waiver": "waiver",
    "package": "doc",
    "flow_config": "flow",
    "tech_config": "tech",
}

FULL_PACKAGE_REQUIRED_VIEWS = {
    "ip": {"rtl", "lef", "lib"},
    "std": {"lef", "lib"},
    "stdcell": {"lef", "lib"},
    "ram": {"lef", "lib"},
    "memory": {"lef", "lib"},
}

DOC_VIEWS = {"doc", "waiver"}
CORE_VIEWS = {"rtl", "lef", "lib", "db", "gds", "oas", "cdl", "sdc", "upf", "cpf", "flow", "tech"}


def file_type_to_view(file_type: str) -> str:
    return FILE_TYPE_TO_VIEW.get(str(file_type or "unknown"), str(file_type or "unknown"))


def _classify_file(root: Path, file_path: Path) -> dict[str, Any]:
    from lib_guard.scan.file_classifier import FileClassifier

    rel = file_path.relative_to(root).as_posix()
    record = FileClassifier().classify({"path": rel, "name": file_path.name})
    file_type = str(record.get("file_type") or "unknown")
    view = file_type_to_view(file_type)
    return {"path": rel, "file_type": file_type, "view": view, "role": record.get("role")}


def classify_package(root: str | Path, *, library_type: str = "ip", limit: int = 200000) -> dict[str, Any]:
    path = Path(root)
    files: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    view_counts: Counter[str] = Counter()
    if path.exists():
        total = 0
        for item in sorted(path.rglob("*"), key=lambda p: p.as_posix().lower()):
            if not item.is_file():
                continue
            rec = _classify_file(path, item)
            files.append(rec)
            counts[rec["file_type"]] += 1
            view_counts[rec["view"]] += 1
            total += 1
            if total >= limit:
                break

    views = {view for view in view_counts if view != "unknown"}
    core_views = views & CORE_VIEWS
    doc_only = bool(views) and views <= DOC_VIEWS
    required = FULL_PACKAGE_REQUIRED_VIEWS.get(str(library_type or "ip").lower(), {"lef", "lib"})

    risks: list[str] = []
    package_type = "UNKNOWN_PACKAGE"
    standalone = False
    base_required = False
    confidence = 0.25
    if doc_only:
        package_type = "DOC_UPDATE"
        base_required = True
        confidence = 0.82
    elif required <= views or len(core_views) >= 4:
        package_type = "FULL_PACKAGE"
        standalone = True
        confidence = 0.9
    elif core_views:
        package_type = "PARTIAL_UPDATE"
        base_required = True
        confidence = 0.78
    else:
        risks.append("no_library_view_files")
        confidence = 0.35 if counts else 0.1

    if package_type == "PARTIAL_UPDATE":
        missing = sorted(required - views)
        if missing:
            risks.append("base_version_not_bound")
    else:
        missing = []

    view_order = ["rtl", "lef", "lib", "db", "gds", "oas", "cdl", "sdc", "upf", "cpf", "spef", "flow", "tech", "doc", "waiver"]
    scope = sorted(views, key=lambda v: view_order.index(v) if v in view_order else 99)
    return {
        "schema_version": "1.0",
        "root": str(path),
        "package_type": package_type,
        "update_scope": scope,
        "standalone": standalone,
        "base_required": base_required,
        "classification_confidence": confidence,
        "classification_evidence": {
            "file_type_counts": dict(sorted(counts.items())),
            "view_counts": dict(sorted(view_counts.items())),
            "missing_expected_views": missing,
        },
        "classification_risks": risks,
        "files": files,
    }
