from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping
import json


DEFAULT_REQUIRED_TYPES = {
    "stdcell": ["liberty", "db", "lef", "gds", "verilog", "cdl"],
    "sram": ["liberty", "db", "lef", "gds", "verilog", "cdl"],
    "ip": ["verilog"],
    "hard_ip": ["liberty", "lef", "gds", "verilog", "cdl"],
    "soft_ip": ["verilog", "filelist"],
    "phy": ["liberty", "lef", "gds", "verilog", "cdl"],
    "io": ["liberty", "lef", "gds", "verilog", "cdl"],
    "pad": ["liberty", "lef", "gds", "verilog", "cdl"],
}


@dataclass
class ReleasePolicy:
    allowed_scan_status: list[str] = field(default_factory=lambda: ["PASS", "PASS_WITH_WARNING"])
    allowed_scan_modes: list[str] = field(default_factory=lambda: ["scan", "candidate", "release", "signature", "full"])
    required_file_types: dict[str, list[str]] = field(default_factory=lambda: dict(DEFAULT_REQUIRED_TYPES))
    require_doc_types: list[str] = field(default_factory=lambda: ["readme", "release_note"])
    block_on_error_issue: bool = True
    block_on_parser_failed: bool = True
    require_signatures: bool = True
    require_summaries: bool = False
    allow_missing_docs_as_warning: bool = True
    release_link_mode: str = "symlink"  # symlink/copy/dry_run
    alias_gate: dict[str, dict[str, Any]] = field(default_factory=lambda: {
        "stage": {"required_release_level": "L0", "allow_warning": True, "require_diff": False, "require_review_gate_closed": False},
        "current": {"required_release_level": "L1", "allow_warning": True, "require_diff": True, "require_review_gate_closed": True, "require_pairwise_done": False},
        "approved": {"required_release_level": "L2", "allow_warning": False, "require_p2_deep_diff": True, "require_manual_review_closed": True, "require_review_gate_closed": True, "require_pairwise_done": True},
    })
    doc_policy: dict[str, Any] = field(default_factory=lambda: {
        "always_parse": True,
        "l0_missing_doc_severity": "warning",
        "l1_missing_release_note_severity": "error",
        "l2_missing_release_note_severity": "blocker",
        "require_hotfix_release_note": True,
    })

    @classmethod
    def from_file(cls, path: str | Path | None) -> "ReleasePolicy":
        if not path:
            return cls()
        p = Path(path)
        data = json.loads(p.read_text(encoding="utf-8"))
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ReleasePolicy":
        base = cls()
        for key, value in data.items():
            if key == "required_views":
                base.required_file_types = dict(value)
                continue
            if hasattr(base, key):
                setattr(base, key, value)
        return base

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed_scan_status": self.allowed_scan_status,
            "allowed_scan_modes": self.allowed_scan_modes,
            "required_file_types": self.required_file_types,
            "required_views": self.required_file_types,
            "require_doc_types": self.require_doc_types,
            "block_on_error_issue": self.block_on_error_issue,
            "block_on_parser_failed": self.block_on_parser_failed,
            "require_signatures": self.require_signatures,
            "require_summaries": self.require_summaries,
            "allow_missing_docs_as_warning": self.allow_missing_docs_as_warning,
            "release_link_mode": self.release_link_mode,
            "alias_gate": self.alias_gate,
            "doc_policy": self.doc_policy,
        }
