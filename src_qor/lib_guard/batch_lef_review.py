"""Run explicitly selected LEF pairs independently using the existing checker."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from . import lef_review


def analyze_pairs(pairs: list[dict[str, Any]], evidence_dir: str | Path) -> dict[str, Any]:
    ids = [str(pair.get("pair_id") or "") for pair in pairs]
    if not ids or len(set(ids)) != len(ids) or any(not re.fullmatch(r"[A-Za-z0-9_-]+", value) for value in ids):
        raise ValueError("LEF 配对标识为空、重复或包含不安全字符")
    target = Path(evidence_dir)
    target.mkdir(parents=True, exist_ok=True)
    results = []
    for pair, pair_id in zip(pairs, ids):
        entry = {"pair_id": pair_id, "file_key": str(pair.get("file_key") or ""),
                 "old_file": str(pair.get("old_file") or ""),
                 "new_file": str(pair.get("new_file") or ""), "evidence_ref": None}
        try:
            if not entry["old_file"] or not entry["new_file"]:
                raise ValueError("配对必须指定两份 LEF")
            report = lef_review.analyze(entry["old_file"], entry["new_file"])
            evidence_ref = f"{pair_id}.json"
            (target / evidence_ref).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            entry.update({"execution_status": "COMPLETE", "evidence_ref": evidence_ref,
                          "sources": report.get("sources") or {}, "comparison": report.get("comparison") or {}})
        except Exception as exc:
            entry.update({"execution_status": "FAILED", "error": str(exc)})
        results.append(entry)
    return {"schema_version": "batch_lef_review.v1", "status": "COMPLETE" if all(
        item["execution_status"] == "COMPLETE" for item in results) else "INCOMPLETE", "pairs": results}
