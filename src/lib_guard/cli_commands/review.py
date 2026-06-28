"""Review gate CLI command handlers."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path
from typing import Any
import json

from .common import print_json, refresh_catalog_html


def _read_catalog(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _library_match_names(lib: dict[str, Any]) -> set[str]:
    names = {str(lib.get("library_id") or ""), str(lib.get("library_name") or ""), str(lib.get("display_name") or "")}
    names.update(str(a) for a in lib.get("aliases", []) or [] if str(a))
    return {name for name in names if name}


def _find_library(catalog: dict[str, Any], library: str) -> dict[str, Any]:
    matches = [lib for lib in catalog.get("libraries", []) or [] if library in _library_match_names(lib)]
    if not matches:
        raise ValueError(f"library not found in catalog: {library}")
    if len(matches) > 1:
        raise ValueError(f"ambiguous library alias: {library}")
    return matches[0]


def _find_version(lib: dict[str, Any], version: str) -> dict[str, Any]:
    for item in lib.get("versions", []) or []:
        if item.get("version_id") == version or item.get("version_key") == version:
            return item
    raise ValueError(f"version not found in catalog: {version}")


def _default_review_out(catalog_path: str | Path, library_name: str, version: str) -> Path:
    catalog = Path(catalog_path)
    if catalog.parent.name == "catalog":
        root = catalog.parent.parent
    else:
        root = catalog.parent
    safe_lib = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in library_name).strip("_") or "library"
    safe_ver = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in version).strip("_") or "version"
    return root / "review" / safe_lib / safe_ver


def _default_catalog_html_out(catalog_path: str | Path) -> Path:
    catalog = Path(catalog_path)
    if catalog.parent.name == "catalog":
        return catalog.parent / "html"
    return catalog.parent / "html"


def _build_gate(args: Namespace) -> tuple[dict[str, Any], Path, Path]:
    from lib_guard.review.overrides import read_review_overrides
    from lib_guard.review.state import build_review_gate_for_version, build_review_state

    catalog = _read_catalog(args.catalog)
    state = build_review_state(catalog, out_dir=_default_catalog_html_out(args.catalog))
    lib = _find_library({"libraries": state.get("libraries", []) or []}, args.library)
    version = dict(_find_version(lib, args.version))
    library_name = str(lib.get("display_name") or lib.get("library_name") or lib.get("library_id") or args.library)
    version_id = str(version.get("version_id") or args.version)

    out_dir = Path(args.out) if getattr(args, "out", None) else _default_review_out(args.catalog, library_name, version_id)
    override_file = Path(getattr(args, "overrides", None) or out_dir / "review_overrides.json")
    gate_file = Path(getattr(args, "gate_file", None) or out_dir / "review_gate.json")
    overrides = read_review_overrides(override_file)
    gate = build_review_gate_for_version(version, gate=getattr(args, "gate", "current"), overrides=overrides)
    gate["override_file"] = str(override_file)
    gate["gate_file"] = str(gate_file)
    return gate, gate_file, override_file


def run_review_build(args: Namespace) -> int:
    from lib_guard.review.io import write_json

    gate, gate_file, _override_file = _build_gate(args)
    write_json(gate_file, gate)
    if getattr(args, "catalog_html_out", None):
        refresh_catalog_html(args)
    print_json({"status": gate.get("status"), "review_gate": str(gate_file), "gate": gate})
    return 0 if gate.get("status") not in {"BLOCKED"} else 2


def run_review_check(args: Namespace) -> int:
    gate, gate_file, _override_file = _build_gate(args)
    print_json({"status": gate.get("status"), "review_gate": str(gate_file), "blocking_open": gate.get("blocking_open", 0), "attention_count": gate.get("attention_count", 0), "gate": gate})
    return 0 if gate.get("status") in {"READY", "ATTENTION"} else 2


def run_review_list(args: Namespace) -> int:
    gate, gate_file, _override_file = _build_gate(args)
    print_json({"status": "PASS", "review_gate": str(gate_file), "blocking_items": gate.get("blocking_items", []), "attention_items": gate.get("attention_items", []), "accepted_items": gate.get("accepted_items", []), "waived_items": gate.get("waived_items", [])})
    return 0


def _write_decision(args: Namespace, decision: str) -> int:
    from lib_guard.review.io import write_json
    from lib_guard.review.overrides import write_review_override

    gate, gate_file, override_file = _build_gate(args)
    write_review_override(
        override_file,
        library=args.library,
        version=args.version,
        item_id=args.item,
        decision=decision,
        by=args.by,
        reason=args.reason,
        gate=getattr(args, "gate", "current"),
    )
    refreshed, _gate_file, _override_file = _build_gate(args)
    write_json(gate_file, refreshed)
    if getattr(args, "catalog_html_out", None):
        refresh_catalog_html(args)
    print_json({"status": refreshed.get("status"), "review_gate": str(gate_file), "review_overrides": str(override_file), "blocking_open": refreshed.get("blocking_open", 0)})
    return 0 if refreshed.get("status") in {"READY", "ATTENTION"} else 2


def run_review_accept(args: Namespace) -> int:
    return _write_decision(args, "accepted")


def run_review_waive(args: Namespace) -> int:
    return _write_decision(args, "waived")
